"""
Tablo yapısını koruyan hibrit motor: pdfplumber ile tablo/metin yapısı, fitz ile gömülü
resim çıkarımı ve OCR. PDF sayfa düzeni bozulmaz.
"""
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pdfplumber
import fitz
import traceback

from rapidocr_onnxruntime import RapidOCR

_rapid_engine = None


def _get_rapid_engine():
    """OCR engine tekilleştirir (lazy)."""
    global _rapid_engine
    if _rapid_engine is None:
        try:
            _rapid_engine = RapidOCR(det_limit_side_len=960)
        except Exception:
            pass
    return _rapid_engine


def _bbox_to_list(bbox: tuple[float, float, float, float] | None) -> list[float] | None:
    if bbox is None or len(bbox) < 4:
        return None
    return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]


def _table_to_rows(table_raw) -> list[list[str]]:
    """pdfplumber tablo çıktısını rows yapısına çevirir."""
    if not table_raw:
        return []
    rows = []
    for row in table_raw:
        if isinstance(row, (list, tuple)):
            rows.append([str(c) if c is not None else "" for c in row])
        elif isinstance(row, dict):
            rows.append([str(row.get(k, "")) for k in sorted(row.keys())])
        else:
            rows.append([str(row)])
    return rows


def _bbox_overlap_area(a: list[float], b: list[float]) -> float:
    """İki bbox [x0,y0,x1,y1] kesişim alanı."""
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _find_cell_for_image(
    img_bbox: list[float],
    tables_with_cells: list[tuple[list[list[str]], list[list[list[float] | None]], list[float]]],
) -> tuple[int, int, int] | None:
    """
    Gömülü resmin bbox'ı hangi tablonun hangi hücresine düşüyor?
    tables_with_cells: [(rows, cells_bbox, table_bbox), ...]
    Döner: (table_idx, row_idx, col_idx) veya None.
    """
    for ti, (rows, cells_bbox, tbl_bbox) in enumerate(tables_with_cells):
        for ri, row_cells in enumerate(cells_bbox):
            for ci, cell_bbox in enumerate(row_cells):
                if cell_bbox is None or len(cell_bbox) < 4:
                    continue
                area = _bbox_overlap_area(img_bbox, cell_bbox)
                cell_area = (cell_bbox[2] - cell_bbox[0]) * (cell_bbox[3] - cell_bbox[1])
                if cell_area <= 0:
                    continue
                # Resmin önemli kısmı bu hücrede (örn. %30 üzeri kesişim)
                if area / cell_area >= 0.2 or area / (
                    (img_bbox[2] - img_bbox[0]) * (img_bbox[3] - img_bbox[1])
                ) >= 0.5:
                    return (ti, ri, ci)
    return None


def _process_page_imagetable(
    pdf_path: Path,
    page_idx: int,
    pdfplumber_page,
    ocr_engine,
) -> dict[str, Any]:
    """
    Tek sayfa: pdfplumber ile tablo + metin yapısı, fitz ile gömülü resimleri OCR'layıp
    tablo hücreleriyle eşleştirir. PDF yapısı korunur.
    """
    page_bbox = pdfplumber_page.bbox
    page_width = page_bbox[2] - page_bbox[0] if page_bbox else None
    page_height = page_bbox[3] - page_bbox[1] if page_bbox else None

    # 1) pdfplumber: metin blokları (chars -> satır)
    text_blocks: list[dict] = []
    try:
        chars = getattr(pdfplumber_page, "chars", None) or []
        if chars:
            from operator import itemgetter
            import itertools
            by_top = itertools.groupby(sorted(chars, key=itemgetter("top")), key=itemgetter("top"))
            for _top, grp in by_top:
                ch_list = list(grp)
                if not ch_list:
                    continue
                x0 = min(c["x0"] for c in ch_list)
                y0 = min(c["top"] for c in ch_list)
                x1 = max(c["x1"] for c in ch_list)
                y1 = max(c["bottom"] for c in ch_list)
                line_text = "".join(
                    c.get("text", "") for c in sorted(ch_list, key=itemgetter("x0"))
                )
                if line_text.strip():
                    text_blocks.append({"text": line_text.strip(), "bbox": [x0, y0, x1, y1]})
    except Exception:
        pass

    # 2) pdfplumber: tablolar (yapı + hücre bbox)
    tables_found = pdfplumber_page.find_tables()
    tables_with_cells: list[tuple[list[list[str]], list[list[list[float] | None]], list[float]]] = []
    tables_data: list[dict[str, Any]] = []

    for table in tables_found:
        tbl_bbox = _bbox_to_list(table.bbox)
        rows_raw = table.extract()
        if not rows_raw:
            continue
        row_texts = _table_to_rows(rows_raw)
        cells_bbox: list[list[list[float] | None]] = []
        for row in table.rows:
            cell_list = []
            for cell in row.cells:
                if cell is None:
                    cell_list.append(None)
                else:
                    cell_list.append(_bbox_to_list(cell))
            cells_bbox.append(cell_list)
        tables_with_cells.append((row_texts, cells_bbox, tbl_bbox or [0, 0, 0, 0]))
        tables_data.append({
            "rows": [r[:] for r in row_texts],
            "bbox": tbl_bbox,
            "cells_bbox": cells_bbox,
        })

    # 3) fitz: gömülü resimleri çıkar, OCR yap, hücreye veya text_block'a yaz
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_idx)
        image_list = page.get_image_info(hashes=False)
        for img_info in image_list:
            bbox = list(img_info["bbox"])
            if (bbox[2] - bbox[0]) < 5 or (bbox[3] - bbox[1]) < 5:
                continue
            zoom = 5
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(bbox))
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            processed = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
            ocr_result, _ = ocr_engine(processed)
            ocr_text = ""
            if ocr_result:
                ocr_text = " ".join(item[1].strip() for item in ocr_result if item[1]).strip()

            cell_ref = _find_cell_for_image(bbox, tables_with_cells)
            if cell_ref is not None and ocr_text:
                ti, ri, ci = cell_ref
                if ti < len(tables_data) and ri < len(tables_data[ti]["rows"]) and ci < len(
                    tables_data[ti]["rows"][ri]
                ):
                    existing = tables_data[ti]["rows"][ri][ci]
                    tables_data[ti]["rows"][ri][ci] = (
                        (existing + " " + ocr_text).strip() if existing else ocr_text
                    )
            elif ocr_text:
                text_blocks.append({
                    "text": ocr_text,
                    "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                })
    finally:
        doc.close()

    # 4) content: tüm metin + tablo satırları
    content_parts = [tb["text"] for tb in text_blocks]
    for t in tables_data:
        for row in t["rows"]:
            content_parts.append(" | ".join(str(c) for c in row))
    content = "\n".join(content_parts).strip()

    return {
        "page_number": page_idx + 1,
        "content": content,
        "tables": tables_data,
        "text_blocks": text_blocks,
        "page_width": page_width,
        "page_height": page_height,
    }


def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Proje engine arayüzü: pdfplumber ile tablo yapısı, gömülü resimler OCR ile hücreye/metne dönüşür.
    PDF yapısı bozulmaz. Döner: list[dict] with page_number, content, tables, text_blocks, page_width, page_height.
    """
    path = Path(file_path) if file_path else None
    if not path or not path.exists():
        return []

    engine = _get_rapid_engine()
    if engine is None:
        return []

    out = []
    try:
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            indices = (
                page_numbers
                if page_numbers is not None
                else list(range(total))
            )
            indices = [i for i in indices if 0 <= i < total]
            for page_idx in indices:
                page = pdf.pages[page_idx]
                result = _process_page_imagetable(path, page_idx, page, engine)
                out.append(result)
    except Exception:
        traceback.print_exc()
        return []
    return out
