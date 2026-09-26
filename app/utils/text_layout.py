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
