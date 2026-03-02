"""pdfplumber ile dijital PDF'ten tablo + metin çıkarımı (koordinatlı)."""
from pathlib import Path
from typing import Any

import pdfplumber


def _table_to_rows(table: list) -> list[list[str]]:
    """pdfplumber tablo çıktısını rows yapısına çevirir."""
    if not table:
        return []
    rows = []
    for row in table:
        if isinstance(row, (list, tuple)):
            rows.append([str(cell) if cell is not None else "" for cell in row])
        elif isinstance(row, dict):
            rows.append([str(row.get(k, "")) for k in sorted(row.keys())])
        else:
            rows.append([str(row)])
    return rows


def _bbox_to_list(bbox: tuple[float, float, float, float] | None) -> list[float] | None:
    if bbox is None or len(bbox) < 4:
        return None
    return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]


def extract(
    file_path: Path | str,
    page_numbers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Tablo ağırlıklı dijital PDF: sayfa bazlı metin + tablolar (tablo ve hücre bbox ile).
    Dönen: text_blocks (sayfa metni satır koordinatlı), tables (rows, bbox, cells_bbox).
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

                text = page.extract_text() or ""
                text_blocks = []
                try:
                    chars = getattr(page, "chars", None) or []
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
                            line_text = "".join(c.get("text", "") for c in sorted(ch_list, key=itemgetter("x0")))
                            if line_text.strip():
                                text_blocks.append({"text": line_text, "bbox": [x0, y0, x1, y1]})
                except Exception:
                    pass

                tables_data: list[dict[str, Any]] = []
                found = page.find_tables()
                for table in found:
                    tbl_bbox = _bbox_to_list(table.bbox)
                    rows = table.extract()
                    if not rows:
                        continue
                    row_texts = _table_to_rows(rows)
                    cells_bbox: list[list[list[float] | None]] = []
                    for row in table.rows:
                        cell_list = []
                        for cell in row.cells:
                            if cell is None:
                                cell_list.append(None)
                            else:
                                cell_list.append(_bbox_to_list(cell))
                        cells_bbox.append(cell_list)
                    tables_data.append({
                        "rows": row_texts,
                        "bbox": tbl_bbox,
                        "cells_bbox": cells_bbox,
                    })

                results.append({
                    "page_number": i + 1,
                    "content": text.strip(),
                    "tables": tables_data,
                    "text_blocks": text_blocks,
                    "page_width": page_width,
                    "page_height": page_height,
                })
    except Exception:
        pass
    return results
