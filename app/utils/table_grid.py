"""Görüntüde çizgi tabanlı tablo ızgarası tespiti + OCR kutularını hücreye yerleştirme.

Taranmış/fotoğraf fatura gibi çizgili tablolarda OCR kutuları y-gruplamayla
okununca çok satırlı hücre (uzun ürün adı, "24.166,6667 / TL") aynı satırdaki
rakamlardan kopar ve fatura kalemi 3-4 parçaya bölünür. Bu modül:

1. Yatay/dikey çizgileri (OpenCV morfoloji) bulur, tablo bölgelerini çıkarır.
2. Yatay çizgilerden SATIR BANTLARI, dikey çizgilerden SÜTUN ayraçları üretir;
   her bantta hangi ayraçların gerçekten var olduğuna bakar (birleşik hücreler:
   "Mal Hizmet Toplam Tutarı" satırları).
3. OCR kutularını merkez noktasına göre (bant, hücre)'ye yerleştirir; hücre
   içindeki kutular (y, x) sırasıyla boşlukla birleşir → her tablo satırı tek
   content satırı (hücreler " | " ile), dijital pdftexttable ile aynı format.

Çizgisiz tablolar tespit edilmez (yanlış pozitif önleme); o durumda çağıran
eski y-gruplamaya döner. Sayfanın %85'inden büyük çerçeveler tablo sayılmaz.
"""
from typing import Any

import cv2
import numpy as np

CELL_SEP = " | "
MAX_TABLE_AREA_FRAC = 0.85
MIN_TABLE_W_FRAC = 0.15
MIN_TABLE_H_FRAC = 0.03
MIN_BAND_PX = 8
SEP_PRESENT_COVERAGE = 0.7


def _cluster_positions(idx: np.ndarray, merge_gap: int = 6) -> list[float]:
    """Ardışık (ya da merge_gap içinde) indeksleri tek çizgi merkezine indirger."""
    if idx.size == 0:
        return []
    out: list[float] = []
    start = prev = int(idx[0])
    for v in idx[1:]:
        v = int(v)
        if v - prev <= merge_gap:
            prev = v
            continue
        out.append((start + prev) / 2.0)
        start = prev = v
    out.append((start + prev) / 2.0)
    return out


def detect_grid_tables(img: np.ndarray) -> list[dict[str, Any]]:
    """Çizgili tablo ızgaralarını döndürür:
    [{"bbox":[x0,y0,x1,y1], "xs":[sütun çizgisi x'leri], "bands":[{"y0","y1","seps":[x]}]}]"""
    if img is None or img.size == 0:
        return []
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape[:2]
        if h < 50 or w < 50:
            return []
        # Koyu piksel = 255. Pozitif C şart: C<0 beyaz zemini de ön plan sayar
        # (eski _detect_tables'ın sessiz hatası — tüm sayfa "çizgi" oluyordu).
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15)
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 40)))
        horiz = cv2.dilate(cv2.erode(bw, hk), hk)
        vert = cv2.dilate(cv2.erode(bw, vk), vk)
        grid = cv2.bitwise_or(horiz, vert)
        # Kırık çizgileri birleştir (tarama/foto)
        grid = cv2.dilate(grid, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        tables: list[dict[str, Any]] = []
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw < w * MIN_TABLE_W_FRAC or ch < h * MIN_TABLE_H_FRAC:
                continue
            if cw * ch > MAX_TABLE_AREA_FRAC * w * h:
                continue
            sub_h = horiz[y:y + ch, x:x + cw]
            sub_v = vert[y:y + ch, x:x + cw]
            row_prof = (sub_h > 0).sum(axis=1)
            col_prof = (sub_v > 0).sum(axis=0)
            # 0.3: toplam bloğu gibi tablonun sadece sağ kısmını kaplayan satır çizgileri de bant açar
            ys = _cluster_positions(np.where(row_prof >= 0.3 * cw)[0])
            xs = _cluster_positions(np.where(col_prof >= 0.12 * ch)[0])
            ys = [y + v for v in ys]
            xs = [x + v for v in xs]
            # Dış kenarlar çizgi olarak yoksa kutu kenarını ekle
            if not ys or ys[0] > y + MIN_BAND_PX:
                ys.insert(0, float(y))
            if ys[-1] < y + ch - MIN_BAND_PX:
                ys.append(float(y + ch))
            if not xs or xs[0] > x + MIN_BAND_PX:
                xs.insert(0, float(x))
            if xs[-1] < x + cw - MIN_BAND_PX:
                xs.append(float(x + cw))
            if len(ys) < 3 or len(xs) < 3:
                # < 2 satır bandı veya < 2 sütun: tablo değil (çerçeve/çizgi)
                continue
            interior_xs = xs[1:-1]
            bands = []
            for y0, y1 in zip(ys[:-1], ys[1:]):
                if y1 - y0 < MIN_BAND_PX:
                    continue
                by0, by1 = int(y0) + 2, int(y1) - 1
                present = []
                for sx in interior_xs:
                    cx0, cx1 = max(0, int(sx) - 2), min(w, int(sx) + 3)
                    strip = bw[by0:by1, cx0:cx1]
                    if strip.size == 0:
                        continue
                    coverage = float((strip.max(axis=1) > 0).mean())
                    if coverage >= SEP_PRESENT_COVERAGE:
                        present.append(sx)
                bands.append({"y0": float(y0), "y1": float(y1), "seps": present})
            if len(bands) < 2:
                continue
            tables.append({
                "bbox": [float(x), float(y), float(x + cw), float(y + ch)],
                "xs": [float(v) for v in xs],
                "bands": bands,
            })
        return tables
    except Exception:
        return []


def _cell_suspicious(ws: list[dict] | None, med_h: float) -> bool:
    """Hücre içeriği ızgara hatasına işaret ediyor mu?
    - aynı y seviyesinde aralarında 1 satır yüksekliğinden geniş boşluk olan bloklar
      (kaçırılmış sütun ayracı: etiket + tutar aynı hücreye düşmüş), veya
    - 6+ farklı y seviyesi (sarılmış ürün adı 4-5 satırı geçmez; kaçırılmış satır çizgisi).
    Sarılmış çok satırlı hücre (her seviyede tek dar blok) şüpheli sayılmaz."""
    if not ws or len(ws) < 2:
        return False
    tol = max(4.0, med_h * 0.6)
    levels: list[list[dict]] = []
    for b in sorted(ws, key=lambda b: (b["bbox"][1] + b["bbox"][3]) / 2):
        cy = (b["bbox"][1] + b["bbox"][3]) / 2
        if levels and abs(cy - (levels[-1][0]["bbox"][1] + levels[-1][0]["bbox"][3]) / 2) <= tol:
            levels[-1].append(b)
        else:
            levels.append([b])
    if len(levels) >= 6:
        return True
    for lv in levels:
        lv.sort(key=lambda b: b["bbox"][0])
        for a, b2 in zip(lv, lv[1:]):
            if b2["bbox"][0] - a["bbox"][2] > 1.0 * med_h:
                return True
    return False


def _center(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def apply_grid_tables(
    text_blocks: list[dict[str, Any]],
    grids: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """OCR kutularını ızgaralara yerleştirir.
    Döner: (tables_data, content için satır blokları, tabloya girmeyen serbest bloklar)."""
    tables_data: list[dict[str, Any]] = []
    row_blocks: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for g in grids:
        bx0, by0, bx1, by1 = g["bbox"]
        bands = g["bands"]
        xs = g["xs"]
        n_cols = len(xs) - 1
        inside = []
        for b in text_blocks:
            if id(b) in consumed:
                continue
            cx, cy = _center(b["bbox"])
            if bx0 - 3 <= cx <= bx1 + 3 and by0 - 3 <= cy <= by1 + 3:
                inside.append(b)
        if len(inside) < 2:
            continue

        buckets: dict[tuple[int, int], list[dict]] = {}
        for b in inside:
            cx, cy = _center(b["bbox"])
            r_idx = None
            for i, band in enumerate(bands):
                if band["y0"] <= cy <= band["y1"]:
                    r_idx = i
                    break
            if r_idx is None:
                r_idx = min(range(len(bands)), key=lambda i: abs((bands[i]["y0"] + bands[i]["y1"]) / 2 - cy))
            edges = [bx0] + list(bands[r_idx]["seps"]) + [bx1]
            # Yerel hücre aralığı -> global sütun indeksi (aralığın sol kenarı)
            local = 0
            for k in range(len(edges) - 1):
                if edges[k] <= cx <= edges[k + 1]:
                    local = k
                    break
            else:
                local = 0 if cx < edges[0] else len(edges) - 2
            left_edge = edges[local]
            g_col = 0
            for k in range(n_cols):
                if abs(xs[k] - left_edge) <= 3:
                    g_col = k
                    break
            else:
                g_col = max(0, min(n_cols - 1, sum(1 for v in xs[1:-1] if v < cx)))
            buckets.setdefault((r_idx, g_col), []).append(b)

        heights = sorted(b["bbox"][3] - b["bbox"][1] for b in inside)
        med_h = heights[len(heights) // 2] if heights else 20.0

        rows: list[list[str]] = []
        cells_bbox: list[list[list[float] | None]] = []
        r_blocks: list[dict[str, Any]] = []
        rejected_bands = 0
        for r_idx, band in enumerate(bands):
            # Bant güvenilirlik kontrolü: satır çizgisi/ayraç kaçırıldıysa (eğik/soluk foto)
            # bir "hücre"ye birden çok satır ve yan yana uzak bloklar dolar. Böyle bandı
            # tabloya sokma; blokları serbest metin (eski y-gruplama) olarak bırak.
            if any(_cell_suspicious(buckets.get((r_idx, c)), med_h) for c in range(n_cols)):
                rejected_bands += 1
                for c in range(n_cols):
                    buckets.pop((r_idx, c), None)
                continue
            row = [""] * n_cols
            row_cells: list[list[float] | None] = [None] * n_cols
            for c in range(n_cols):
                ws = buckets.get((r_idx, c))
                if not ws:
                    continue
                ws.sort(key=lambda b: (round(b["bbox"][1] / 6), b["bbox"][0]))
                row[c] = " ".join(b["text"].strip() for b in ws if b["text"].strip())
                row_cells[c] = [
                    min(b["bbox"][0] for b in ws), min(b["bbox"][1] for b in ws),
                    max(b["bbox"][2] for b in ws), max(b["bbox"][3] for b in ws),
                ]
            if not any(row):
                continue
            rows.append(row)
            cells_bbox.append(row_cells)
            r_blocks.append({
                "text": CELL_SEP.join(row),
                "bbox": [bx0, band["y0"], bx1, band["y1"]],
            })

        # Güvenlik: en az 2 satırda 2+ dolu hücre yoksa tablo değil (tek satırlık sahte ızgara);
        # bantların yarısından çoğu reddedildiyse ızgara güvenilmez, tabloyu bırak.
        if len(rows) < 2 or sum(1 for r in rows if sum(1 for c in r if c) >= 2) < 2:
            continue
        if rejected_bands * 2 > len(bands):
            continue
        for ws in buckets.values():
            for b in ws:
                consumed.add(id(b))
        tables_data.append({"rows": rows, "bbox": [bx0, by0, bx1, by1], "cells_bbox": cells_bbox})
        row_blocks.extend(r_blocks)

    free = [b for b in text_blocks if id(b) not in consumed]
    return tables_data, row_blocks, free

# --------------------------------------------------------------------------- deskew
DESKEW_MAX_DEG = 12.0
DESKEW_MIN_DEG = 0.3


def estimate_skew_by_lines(img: np.ndarray) -> float | None:
    """Uzun cetvel çizgilerinden (tablo kenarları) eğiklik açısı (derece, saat yönü +).
    Çizgi yoksa / çizgiler uyuşmuyorsa None (fiş fotoğrafı gibi belgelerde dokunulmaz)."""
    if img is None or img.size == 0:
        return None
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape[:2]
        scale = 1200.0 / max(h, w)
        if scale < 1.0:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h, w = gray.shape[:2]
        edges = cv2.Canny(gray, 50, 150)
        min_len = int(0.22 * max(h, w))
        lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=120, minLineLength=min_len, maxLineGap=20)
        if lines is None:
            return None
        angs: list[tuple[float, float]] = []  # (açı, uzunluk)
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            dx, dy = float(x2 - x1), float(y2 - y1)
            length = float(np.hypot(dx, dy))
            if length < min_len:
                continue
            ang = float(np.degrees(np.arctan2(dy, dx)))
            # yatay çizgiler: açı ~0; dikey çizgiler: ~±90 -> aynı eğikliğe indirge
            if abs(ang) <= DESKEW_MAX_DEG:
                angs.append((ang, length))
            elif abs(abs(ang) - 90.0) <= DESKEW_MAX_DEG:
                angs.append((ang - 90.0 if ang > 0 else ang + 90.0, length))
        if len(angs) < 3:
            return None
        angs.sort()
        total = sum(l for _, l in angs)
        if total < 1.5 * max(h, w):
            return None
        acc = 0.0
        med = angs[-1][0]
        for a, l in angs:
            acc += l
            if acc >= total / 2:
                med = a
                break
        agree = sum(l for a, l in angs if abs(a - med) <= 0.7)
        if agree < 0.8 * total:
            return None
        return med
    except Exception:
        return None


def deskew_by_lines(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Cetvel çizgilerine göre küçük açı düzeltmesi. Döner: (görüntü, uygulanan açı)."""
    ang = estimate_skew_by_lines(img)
    if ang is None or abs(ang) < DESKEW_MIN_DEG or abs(ang) > DESKEW_MAX_DEG:
        return img, 0.0
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), ang, 1.0)
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out, ang
