"""Text block'ları y-koordinatına göre satırlara gruplayarak content oluşturur."""


def content_from_text_blocks(
    text_blocks: list[dict],
    y_threshold: float | None = None,
) -> str:
    """
    text_blocks listesinden koordinat-farkında düz metin üretir.

    Aynı y-koordinatındaki (y_threshold toleranslı) blokları tek satırda birleştirir.
    Örnek: "MÜŞTERİ NO" (x=32, y=46) ve ": 76741241" (x=86, y=46) →
           "MÜŞTERİ NO : 76741241"

    Args:
        text_blocks: [{"text": str, "bbox": [x0,y0,x1,y1] | {"x0","y0","x1","y1"}}]
        y_threshold: Aynı satır kabul edilen max y farkı (None = otomatik hesapla).
    """
    if not text_blocks:
        return ""

    # bbox'tan (y0, x0, text) çıkar
    items = []
    heights = []
    for blk in text_blocks:
        text = (blk.get("text") or "").strip()
        if not text:
            continue
        bbox = blk.get("bbox")
        if bbox is None:
            items.append((0.0, 0.0, text))
            continue
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        elif isinstance(bbox, dict):
            x0 = float(bbox.get("x0", 0))
            y0 = float(bbox.get("y0", bbox.get("top", 0)))
            x1 = float(bbox.get("x1", 0))
            y1 = float(bbox.get("y1", bbox.get("bottom", 0)))
        else:
            items.append((0.0, 0.0, text))
            continue
        items.append((y0, x0, text))
        h = y1 - y0
        if h > 0:
            heights.append(h)

    if not items:
        return ""

    # y_threshold otomatik hesapla: medyan yüksekliğin %40'ı
    if y_threshold is None:
        if heights:
            sorted_h = sorted(heights)
            mid = len(sorted_h) // 2
            median_h = sorted_h[mid] if len(sorted_h) % 2 else (sorted_h[mid - 1] + sorted_h[mid]) / 2
            y_threshold = median_h * 0.4
        else:
            y_threshold = 4.0

    # y'ye, sonra x'e göre sırala
    items.sort(key=lambda it: (it[0], it[1]))

    # y-threshold ile satırlara grupla
    rows: list[list[tuple[float, float, str]]] = []
    current_row: list[tuple[float, float, str]] = [items[0]]
    current_y = items[0][0]

    for it in items[1:]:
        if abs(it[0] - current_y) <= y_threshold:
            current_row.append(it)
        else:
            rows.append(current_row)
            current_row = [it]
            current_y = it[0]
    rows.append(current_row)

    # Her satırı x sırasıyla birleştir
    lines = []
    for row in rows:
        row.sort(key=lambda it: it[1])  # x sıralama
        parts = []
        prev_x1 = None
        for y0, x0, text in row:
            if prev_x1 is not None:
                # x aralığına göre boşluk ekle (yaklaşık karakter genişliği ile)
                gap = x0 - prev_x1
                if gap > 2:
                    # Her ~6pt = 1 boşluk (ortalama karakter genişliği)
                    spaces = max(1, round(gap / 6))
                    parts.append(" " * spaces)
                elif not parts[-1].endswith(" ") and not text.startswith(" "):
                    parts.append(" ")
            parts.append(text)
            # Sonraki blok için x1 tahmini: x0 + karakter sayısı * ortalama genişlik
            # Ama bbox varsa direkt kullanalım
            # Basit tahmin: text uzunluğu * yaklaşık genişlik
            avg_char_w = 6.0  # varsayılan
            if len(text) > 0:
                # Eğer blokta bbox bilgisi varsa text_blocks'tan çekebiliriz
                # Ama burada sadece (y0, x0, text) var, x1 yok
                # x1'i de taşımak lazım
                pass
            prev_x1 = x0 + len(text) * avg_char_w
        lines.append("".join(parts).rstrip())

    return "\n".join(lines)


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
        if h > 0:
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
    current_y = items[0][0]

    for it in items[1:]:
        if abs(it[0] - current_y) <= y_threshold:
            current_row.append(it)
        else:
            rows.append(current_row)
            current_row = [it]
            current_y = it[0]
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
