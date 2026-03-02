"""PyMuPDF ile dijital PDF'ten metin çıkarımı (koordinatlı)."""
from pathlib import Path
from typing import Any

import fitz


def _bbox_union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    """Birden fazla bbox'ı tek bbox'ta birleştirir."""
    if not boxes:
        return (0, 0, 0, 0)
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def extract(
    file_path: Path | str,
    page_numbers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Dijital (searchable) PDF'ten sayfa bazlı metin + koordinatlar.
    Dönen her öğe: {"page_number", "content", "tables": [], "text_blocks": [{"text", "bbox": [x0,y0,x1,y1]}], "page_width", "page_height"}
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []
    results = []
    try:
        doc = fitz.open(file_path)
        indices = page_numbers if page_numbers is not None else list(range(len(doc)))
        for i in indices:
            if i < 0 or i >= len(doc):
                continue
            page = doc[i]
            rect = page.rect
            page_width = rect.width
            page_height = rect.height

            text_blocks: list[dict[str, Any]] = []
            full_text_parts: list[str] = []

            # get_text("dict") -> blocks -> lines -> spans (bbox, text)
            try:
                raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            except Exception:
                raw = page.get_text("dict")
            blocks = raw.get("blocks") or []
            for block in blocks:
                for line in block.get("lines") or []:
                    spans = line.get("spans") or []
                    line_text = "".join(s.get("text", "") for s in spans)
                    if not line_text.strip():
                        continue
                    bboxes = []
                    for s in spans:
                        b = s.get("bbox")
                        if b and len(b) >= 4:
                            bboxes.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
                    if bboxes:
                        x0, y0, x1, y1 = _bbox_union(bboxes)
                        text_blocks.append({
                            "text": line_text,
                            "bbox": [x0, y0, x1, y1],
                        })
                    full_text_parts.append(line_text)
            content = "\n".join(full_text_parts).strip()
            if not content and page.get_text().strip():
                content = page.get_text().strip()
                if not text_blocks:
                    text_blocks = [{"text": content, "bbox": [0, 0, page_width, page_height]}]

            results.append({
                "page_number": i + 1,
                "content": content,
                "tables": [],
                "text_blocks": text_blocks,
                "page_width": page_width,
                "page_height": page_height,
            })
        doc.close()
    except Exception:
        pass
    return results
