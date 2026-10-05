"""Text block'ları y-koordinatına göre satırlara gruplayarak content oluşturur."""


def content_from_text_blocks_with_bbox(
    text_blocks: list[dict],
    y_threshold: float | None = None,
) -> str:
    """
    text_blocks'tan tam bbox bilgisi kullanarak doğru boşluklu content üretir.
    """
    if not text_blocks:
        return ""

    items = []  # (y0, x0, x1, text)
    heights = []
    for blk in text_blocks:
        text = (blk.get("text") or "").strip()
        if not text:
            continue
        bbox = blk.get("bbox")
        if bbox is None:
            items.append((0.0, 0.0, 0.0, text))
            continue
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        elif isinstance(bbox, dict):
            x0 = float(bbox.get("x0", 0))
            y0 = float(bbox.get("y0", bbox.get("top", 0)))
            x1 = float(bbox.get("x1", 0))
            y1 = float(bbox.get("y1", bbox.get("bottom", 0)))
        else:
            items.append((0.0, 0.0, 0.0, text))
            continue
        items.append((y0, x0, x1, text))
        h = y1 - y0
        # Tablo satırı blokları (source="table") bir hücre yüksekliğindedir; medyana
        # girerlerse y-eşiği şişer ve tablo dışı komşu satırlar birleşir (Findeks
        # altbilgisi ölçümü: eşik 8.4pt, satır aralığı 8.0pt). Eşik metin satırlarından.
        if h > 0 and blk.get("source") != "table":
            heights.append(h)

    if not items:
        return ""

    if y_threshold is None:
        if heights:
            sorted_h = sorted(heights)
            mid = len(sorted_h) // 2
            median_h = sorted_h[mid] if len(sorted_h) % 2 else (sorted_h[mid - 1] + sorted_h[mid]) / 2
            y_threshold = median_h * 0.4
        else:
            y_threshold = 4.0

    items.sort(key=lambda it: (it[0], it[1]))

    rows: list[list[tuple[float, float, float, str]]] = []
    current_row: list[tuple[float, float, float, str]] = [items[0]]
    # Satir referansi: ilk bloga sabitlemek yerine satirin calisan ORTALAMA y'si.
    # Boylece hafif egik/taranmis belgede satir basi ile sonu arasindaki y kaymasi
    # birikip blogu yanlislikla alt satira dusurmez (kayma onleme).
    row_y_sum = items[0][0]
    row_y_cnt = 1

    for it in items[1:]:
        avg_y = row_y_sum / row_y_cnt
        if abs(it[0] - avg_y) <= y_threshold:
            current_row.append(it)
            row_y_sum += it[0]
            row_y_cnt += 1
        else:
            rows.append(current_row)
            current_row = [it]
            row_y_sum = it[0]
            row_y_cnt = 1
    rows.append(current_row)

    # Ortalama karakter genişliği hesapla
    char_widths = []
    for y0, x0, x1, text in items:
        if len(text) > 0 and x1 > x0:
            char_widths.append((x1 - x0) / len(text))
    if char_widths:
        sorted_cw = sorted(char_widths)
        mid = len(sorted_cw) // 2
        avg_cw = sorted_cw[mid]
    else:
        avg_cw = 6.0

    lines = []
    for row in rows:
        row.sort(key=lambda it: it[1])
        parts = []
        prev_x1 = None
        for y0, x0, x1, text in row:
            if prev_x1 is not None:
                gap = x0 - prev_x1
                if gap > avg_cw * 0.5:
                    spaces = max(1, round(gap / avg_cw))
                    parts.append(" " * spaces)
                elif parts and not parts[-1].endswith(" ") and not text.startswith(" "):
                    parts.append(" ")
            parts.append(text)
            prev_x1 = x1
        lines.append("".join(parts).rstrip())

    return "\n".join(lines)


def _bb(b) -> list[float] | None:
    if isinstance(b, (list, tuple)) and len(b) >= 4:
        return [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
    if isinstance(b, dict):
        return [float(b.get("x0", 0)), float(b.get("y0", b.get("top", 0))),
                float(b.get("x1", 0)), float(b.get("y1", b.get("bottom", 0)))]
    return None


def compose_content(text_blocks: list[dict], tables: list[dict] | None) -> str:
    """Tablo-farkında okuma sırası.

    Yalnız y-gruplama yan yana iki kutuyu (sol "Müşteri", sağ "e-Arşiv") satır satır
    birbirine karıştırıyordu. Burada dikeyde örtüşen tablolar bir "küme" olur; küme
    içindeki her tablo (ve tablonun yanındaki serbest metin) BÜTÜN olarak, soldan sağa
    yazılır. Kümeler arası serbest metin eskisi gibi y-gruplamayla okunur.
    Tablo satırı yoksa davranış content_from_text_blocks_with_bbox ile birebir aynıdır.
    """
    tbs = [b for b in (_bb(t.get("bbox")) for t in (tables or [])) if b]
    rows_by_t: dict[int, list[dict]] = {}
    free: list[dict] = []
    for blk in text_blocks:
        b = _bb(blk.get("bbox"))
        if blk.get("source") == "table" and b:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            hit = next((i for i, t in enumerate(tbs) if t[0] - 2 <= cx <= t[2] + 2 and t[1] - 2 <= cy <= t[3] + 2), None)
            if hit is not None:
                rows_by_t.setdefault(hit, []).append(blk)
                continue
        free.append(blk)
    if not rows_by_t:
        return content_from_text_blocks_with_bbox(text_blocks)

    # Dikeyde örtüşen tabloları kümele
    order = sorted(rows_by_t, key=lambda i: tbs[i][1])
    clusters: list[dict] = []
    for i in order:
        t = tbs[i]
        if clusters and t[1] < clusters[-1]["y1"] - 2:
            clusters[-1]["tables"].append(i)
            clusters[-1]["y1"] = max(clusters[-1]["y1"], t[3])
        else:
            clusters.append({"y0": t[1], "y1": t[3], "tables": [i], "free": []})

    # Serbest metni küme içine (yanındaki metin) veya kümeler arası boşluğa dağıt
    gaps: list[list[dict]] = [[] for _ in range(len(clusters) + 1)]
    for blk in free:
        b = _bb(blk.get("bbox"))
        cy = (b[1] + b[3]) / 2 if b else 0.0
        k = next((n for n, c in enumerate(clusters) if c["y0"] <= cy <= c["y1"]), None)
        if k is not None:
            clusters[k]["free"].append(blk)
        else:
            gaps[sum(1 for c in clusters if c["y1"] < cy)].append(blk)

    def _rows_text(i: int) -> str:
        rows = sorted(rows_by_t[i], key=lambda r: (_bb(r["bbox"])[1], _bb(r["bbox"])[0]))
        return "\n".join((r.get("text") or "").strip() for r in rows if (r.get("text") or "").strip())

    parts: list[str] = []
    for n, c in enumerate(clusters):
        if gaps[n]:
            parts.append(content_from_text_blocks_with_bbox(gaps[n]))
        units = [(tbs[i][0], _rows_text(i)) for i in c["tables"]]
        if c["free"]:
            fx = min((_bb(b["bbox"]) or [0])[0] for b in c["free"])
            units.append((fx, content_from_text_blocks_with_bbox(c["free"])))
        parts.extend(text for _x, text in sorted(units, key=lambda u: u[0]) if text)
    if gaps[-1]:
        parts.append(content_from_text_blocks_with_bbox(gaps[-1]))
    return "\n".join(p for p in parts if p)
