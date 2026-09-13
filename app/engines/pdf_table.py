"""pdfplumber ile dijital PDF'ten tablo + metin çıkarımı (koordinatlı).

content üretimi tablo-satırı-farkındadır (fatura satırı bölünmesi düzeltmesi):

- VERİ TABLOSU (fatura kalemleri, "Fatura Tipi | SATIS" kutusu gibi kısa hücreli
  tablolar): her tablo satırı content'te TEK satır olur, hücreler " | " ile
  birleştirilir, çok satırlı hücre ("24.166,6667\\nTL", uzun ürün adı) tek satıra
  iner. Aksi hâlde y-gruplama ürün adını parçalara böler ve araya giren rakamlar
  (sıra no, miktar, tutar) satırı dağıtır ("3GB GRAPHITE ...", "TL", "SAMSUNG").
- DÜZEN KONTEYNERİ (CV gibi, hücreleri paragraf olan 1-2 sütunlu "tablolar"):
  eskisi gibi serbest metin olarak y-gruplama ile okunur; paragraf satırları
  korunur. tables[].rows'ta hücre içi satır sonları ("\\n") korunur.
- Hücre metni pdfplumber'ın hücre kırpmasından değil, merkezi hücreye düşen
  KELİMELERDEN üretilir: kırpma ilk harfi yutabiliyordu ("Özelleştirme" ->
  "zelleştirme"). Hücre kenarına boşluksuz yapışık kelime ("Zamanı:16:43:00")
  karakter merkezine göre hücre sınırında bölünür.
- Tablo dışı metin kelime bazlı alınıp satıra kümelenir; sütun boşlukları
  korunur ("SıraMalzeme" gibi yapışmalar olmaz, Dekont'un iki sütunu bozulmaz).
- Soft hyphen (U+00AD) "-" yapılır: "14\\xad01\\xad2025" -> "14-01-2025".
"""
from pathlib import Path
from typing import Any

import pdfplumber

from app.utils.text_layout import content_from_text_blocks_with_bbox

_SOFT_HYPHEN = "\xad"
CELL_SEP = " | "
# Veri tablosu ölçütleri: >= DATA_TABLE_MIN_COLS sütun VEYA tüm hücreler kısa
DATA_TABLE_MIN_COLS = 3
DATA_CELL_MAX_CHARS = 80
DATA_CELL_MAX_LINES = 2
# Tablo bbox'ına bu kadar (pt) yakın kelimeler de hücreye aday olur
TABLE_MEMBER_TOL = 6.0
LINE_Y_TOL = 3.0


def _norm(text: str | None) -> str:
    """Soft hyphen -> '-', çoklu boşlukları tek boşluğa indirger (tek satır)."""
    if not text:
        return ""
    return " ".join(str(text).replace(_SOFT_HYPHEN, "-").split())


def _norm_keep_lines(text: str | None) -> str:
    if not text:
        return ""
    return "\n".join(ln for ln in (_norm(l) for l in str(text).splitlines()) if ln)


def _bbox_to_list(bbox) -> list[float] | None:
    if bbox is None or len(bbox) < 4:
        return None
    return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]


def _in_bbox(cx: float, cy: float, b: list[float] | None, tol: float = 0.5) -> bool:
    return bool(b) and (b[0] - tol) <= cx <= (b[2] + tol) and (b[1] - tol) <= cy <= (b[3] + tol)


def _union(boxes: list[list[float]]) -> list[float] | None:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


# --------------------------------------------------------------------------- kelimeler
def _page_words(page) -> list[dict]:
    try:
        words = page.extract_words(
            x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=False, return_chars=True
        )
    except Exception:
        return []
    out = []
    for w in words:
        if not _norm(w.get("text")):
            continue
        w["_cx"] = (float(w["x0"]) + float(w["x1"])) / 2
        w["_cy"] = (float(w["top"]) + float(w["bottom"])) / 2
        out.append(w)
    return out


def _words_to_lines(words: list[dict]) -> list[list[dict]]:
    """Kelimeleri y'ye göre satırlara kümeler (her satır x sıralı)."""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
    lines: list[list[dict]] = [[ws[0]]]
    cur_top = float(ws[0]["top"])
    for w in ws[1:]:
        if abs(float(w["top"]) - cur_top) <= LINE_Y_TOL:
            lines[-1].append(w)
        else:
            lines.append([w])
            cur_top = float(w["top"])
    for ln in lines:
        ln.sort(key=lambda w: float(w["x0"]))
    return lines


def _words_to_block(words: list[dict]) -> dict[str, Any]:
    return {
        "text": " ".join(_norm(w["text"]) for w in words),
        "bbox": [
            min(float(w["x0"]) for w in words),
            min(float(w["top"]) for w in words),
            max(float(w["x1"]) for w in words),
            max(float(w["bottom"]) for w in words),
        ],
    }


def _free_text_blocks(words: list[dict]) -> list[dict[str, Any]]:
    """Tablo dışı kelimeleri satır parçaları (bbox'lı) olarak döndürür.

    Satır içinde büyük x boşluğu (sütun arası) varsa ayrı blok olur; böylece
    content üretimi sütun boşluklarını korur.
    """
    blocks: list[dict[str, Any]] = []
    for line in _words_to_lines(words):
        cws = sorted((float(w["x1"]) - float(w["x0"])) / max(1, len(w["text"])) for w in line)
        cw = cws[len(cws) // 2] if cws else 5.0
        split_gap = max(2.5 * cw, 6.0)
        seg: list[dict] = []
        prev_x1 = None
        for w in line:
            if seg and prev_x1 is not None and float(w["x0"]) - prev_x1 > split_gap:
                blocks.append(_words_to_block(seg))
                seg = []
            seg.append(w)
            prev_x1 = float(w["x1"])
        if seg:
            blocks.append(_words_to_block(seg))
    return blocks


# --------------------------------------------------------------------------- tablolar
def _split_word_at_cells(w: dict, cells: list[list[float]]) -> list[dict]:
    """Kelime birden fazla hücreye yayılıyorsa karakter merkezine göre hücre sınırında böler."""
    chars = w.get("chars") or []
    if len(chars) < 2 or len(cells) < 2:
        return [w]

    def cell_of(ch):
        cx = (float(ch["x0"]) + float(ch["x1"])) / 2
        for idx, c in enumerate(cells):
            if c[0] - 0.5 <= cx <= c[2] + 0.5:
                return idx
        return None

    groups: list[tuple[int | None, list[dict]]] = []
    for ch in chars:
        idx = cell_of(ch)
        if groups and (idx is None or idx == groups[-1][0]):
            groups[-1][1].append(ch)
        else:
            groups.append((idx, [ch]))
    if len({g[0] for g in groups if g[0] is not None}) < 2:
        return [w]
    pieces = []
    for _idx, chs in groups:
        text = "".join(c.get("text", "") for c in chs)
        if not text.strip():
            continue
        x0 = min(float(c["x0"]) for c in chs)
        x1 = max(float(c["x1"]) for c in chs)
        pieces.append({
            "text": text, "x0": x0, "x1": x1,
            "top": min(float(c["top"]) for c in chs),
            "bottom": max(float(c["bottom"]) for c in chs),
            "_cx": (x0 + x1) / 2, "_cy": w["_cy"], "chars": chs,
        })
    return pieces or [w]


def _assign_words_to_cells(
    words: list[dict],
    cells_bbox: list[list[list[float] | None]],
) -> tuple[dict[tuple[int, int], list[dict]], set[int], int]:
    """Kelimeleri (merkez noktasına göre) hücrelere dağıtır.
    Döner: {(row, col): [kelimeler]}, yerleşen kelimelerin id()'leri, hücre sınırında
    bölünen kelime sayısı (yüksekse "tablo" aslında kelimeleri kesen çizgi/kutucuk)."""
    buckets: dict[tuple[int, int], list[dict]] = {}
    placed_ids: set[int] = set()
    split_count = 0
    row_ranges: list[tuple[float, float] | None] = []
    for cells in cells_bbox:
        u = _union([c for c in cells if c])
        row_ranges.append((u[1], u[3]) if u else None)

    # Sütun şablonu: en çok hücresi olan satır (genelde başlık). Sadece yatay çizgili
    # satırlarda (dikey çizgi yalnız başlıkta) pdfplumber tüm satırı TEK geniş hücre verir;
    # o satırların kelimeleri şablon sütun aralıklarına göre dağıtılır.
    template: list[list[float] | None] | None = None
    tbl_u = _union([c for cells in cells_bbox for c in cells if c])
    tbl_w = (tbl_u[2] - tbl_u[0]) if tbl_u else 0.0
    best = max(cells_bbox, key=lambda cells: sum(1 for c in cells if c), default=None)
    if best is not None and sum(1 for c in best if c) >= 3:
        template = best

    def _row_cells_for(r_idx: int) -> list[list[float] | None]:
        cells = cells_bbox[r_idx]
        real = [c for c in cells if c]
        if template is not None and len(real) <= 1 and real and tbl_w > 0 and (real[0][2] - real[0][0]) >= 0.9 * tbl_w:
            rng = row_ranges[r_idx]
            return [[c[0], rng[0], c[2], rng[1]] if c else None for c in template]
        return cells

    for w in words:
        cx, cy = w["_cx"], w["_cy"]
        # 1) Tam hücre isabeti (satır-birleşik uzun hücreler için doğru satırı verir)
        r_hit = None
        for r_idx, cells in enumerate(cells_bbox):
            if any(c is not None and _in_bbox(cx, cy, c) for c in cells):
                r_hit = r_idx
                break
        # 2) Hücre yoksa satır y-aralığına göre
        if r_hit is None:
            for r_idx, rng in enumerate(row_ranges):
                if rng and rng[0] - 0.5 <= cy <= rng[1] + 0.5:
                    r_hit = r_idx
                    break
        if r_hit is None:
            continue
        eff_cells = _row_cells_for(r_hit)
        row_cells = [c for c in eff_cells if c]
        pieces = _split_word_at_cells(w, row_cells) if row_cells else [w]
        if len(pieces) > 1:
            split_count += 1
        for piece in pieces:
            pcx = piece["_cx"]
            c_hit = None
            for c_idx, c in enumerate(eff_cells):
                if c is not None and (c[0] - 0.5) <= pcx <= (c[2] + 0.5):
                    c_hit = c_idx
                    break
            if c_hit is None:
                # Hücresi olmayan (birleşik/None) bölge veya kenar taşması: en yakın hücre
                cands = [(abs(pcx - (c[0] + c[2]) / 2), c_idx) for c_idx, c in enumerate(eff_cells) if c]
                if not cands:
                    continue
                c_hit = min(cands)[1]
            buckets.setdefault((r_hit, c_hit), []).append(piece)
            placed_ids.add(id(w))
    return buckets, placed_ids, split_count


def _cell_text(ws: list[dict], keep_lines: bool) -> str:
    lines = [" ".join(_norm(w["text"]) for w in ln) for ln in _words_to_lines(ws)]
    return "\n".join(lines) if keep_lines else " ".join(lines)


def _fallback_rows(table_rows: list) -> list[list[str]]:
    rows = []
    for row in table_rows or []:
        if isinstance(row, (list, tuple)):
            rows.append([_norm_keep_lines(c) for c in row])
        else:
            rows.append([_norm_keep_lines(row)])
    return rows


def _is_data_table(rows_raw: list[list[str]]) -> bool:
    """Kısa hücreli / çok sütunlu tablo = veri tablosu (satır bazlı render edilir).
    Tek hücrelik çerçeveler ve paragraf hücreli 1-2 sütunlu düzen kutuları değildir."""
    if not rows_raw or sum(len(r) for r in rows_raw) < 2:
        return False
    n_cols = max(len(r) for r in rows_raw)
    if n_cols >= DATA_TABLE_MIN_COLS:
        return True
    for r in rows_raw:
        for c in r:
            if len(c) > DATA_CELL_MAX_CHARS or c.count("\n") + 1 > DATA_CELL_MAX_LINES:
                return False
    return True


def _extract_tables(
    page, words: list[dict]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict], list[list[float]]]:
    """Döner: tables_data, content için satır blokları, tablo dışında kalan kelimeler,
    satır bazlı render edilen (veri tablosu) bbox'ları."""
    tables_data: list[dict[str, Any]] = []
    row_blocks: list[dict[str, Any]] = []
    data_bboxes: list[list[float]] = []
    consumed: set[int] = set()
    try:
        found = page.find_tables()
    except Exception:
        found = []
    for table in found:
        tbl_bbox = _bbox_to_list(table.bbox)
        try:
            raw_rows = table.extract()
        except Exception:
            raw_rows = None
        if not raw_rows:
            continue
        cells_bbox: list[list[list[float] | None]] = [
            [_bbox_to_list(c) if c is not None else None for c in row.cells] for row in table.rows
        ]
        fallback = _fallback_rows(raw_rows)

        cand = [w for w in words if id(w) not in consumed and _in_bbox(w["_cx"], w["_cy"], tbl_bbox, TABLE_MEMBER_TOL)]
        buckets, placed, n_split = _assign_words_to_cells(cand, cells_bbox) if cells_bbox else ({}, set(), 0)

        # Önce satır sonları korunarak hücre metni (veri tablosu kararı için)
        rows_ml: list[list[str]] = []
        for r_idx, cells in enumerate(cells_bbox):
            row: list[str] = []
            for c_idx, _c in enumerate(cells):
                ws = buckets.get((r_idx, c_idx))
                if ws:
                    row.append(_cell_text(ws, keep_lines=True))
                elif r_idx < len(fallback) and c_idx < len(fallback[r_idx]):
                    row.append(fallback[r_idx][c_idx])
                else:
                    row.append("")
            rows_ml.append(row)
        if not rows_ml:
            rows_ml = fallback

        # Veri tablosu: en az 2 satır; kelimelerin >%15'i hücre sınırında bölünüyorsa bu
        # "tablo" kelimeleri kesen kutucuk/çizgi demektir (CV yetenek etiketleri) -> değil.
        data_table = (
            _is_data_table(rows_ml)
            and len(rows_ml) >= 2
            and (not placed or n_split <= 0.15 * len(placed))
        )
        rows_out = [[_norm(c) for c in r] for r in rows_ml] if data_table else rows_ml
        tables_data.append({"rows": rows_out, "bbox": tbl_bbox, "cells_bbox": cells_bbox})

        if not data_table or tbl_bbox is None:
            # Düzen konteyneri: kelimeler serbest metin olarak kalır
            continue
        consumed |= placed
        data_bboxes.append(tbl_bbox)
        for r_idx, row_cells in enumerate(rows_out):
            line = CELL_SEP.join(row_cells).strip()
            if not line.strip("| "):
                continue
            rb = _union([c for c in (cells_bbox[r_idx] if r_idx < len(cells_bbox) else []) if c]) or tbl_bbox
            row_blocks.append({"text": line, "bbox": rb})

    free_words = [w for w in words if id(w) not in consumed]
    return tables_data, row_blocks, free_words, data_bboxes


def extract_page_tables(page) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[float]]]:
    """Diğer motorlar (imagetexthybrid) için: pdfplumber sayfasındaki veri tablolarını
    satır bloklarına çevirir. Döner: (tables_data, row_blocks, veri tablosu bbox'ları).
    Koordinatlar PDF nokta birimi, sol-üst orijin (fitz ile aynı)."""
    try:
        words = _page_words(page)
        tables_data, row_blocks, _free, data_bboxes = _extract_tables(page, words)
        return tables_data, row_blocks, data_bboxes
    except Exception:
        return [], [], []


# --------------------------------------------------------------------------- giriş
def extract(
    file_path: Path | str,
    page_numbers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Tablo ağırlıklı dijital PDF: sayfa bazlı metin + tablolar (tablo ve hücre bbox ile).
    Dönen: text_blocks (tablo dışı satırlar + veri tablosu satırları, koordinatlı),
           tables (rows, bbox, cells_bbox), content (okuma sırasında düz metin).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []
    results = []
    try:
        with pdfplumber.open(file_path) as pdf:
            indices = page_numbers if page_numbers is not None else list(range(len(pdf.pages)))
            for i in indices:
                if i < 0 or i >= len(pdf.pages):
                    continue
                page = pdf.pages[i]
                page_bbox = page.bbox
                page_width = page_bbox[2] - page_bbox[0] if page_bbox else None
                page_height = page_bbox[3] - page_bbox[1] if page_bbox else None

                words = _page_words(page)
                tables_data, row_blocks, free_words, _data_bboxes = _extract_tables(page, words)

                text_blocks = _free_text_blocks(free_words)
                text_blocks.extend(row_blocks)
                text_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

                if text_blocks:
                    content = content_from_text_blocks_with_bbox(text_blocks)
                else:
                    content = _norm_keep_lines(page.extract_text() or "")

                results.append({
                    "page_number": i + 1,
                    "content": content,
                    "tables": tables_data,
                    "text_blocks": text_blocks,
                    "page_width": page_width,
                    "page_height": page_height,
                })
    except Exception:
        pass
    return results
