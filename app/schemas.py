"""API istek/yanıt şemaları. Tüm metin ve tablolar koordinat (bbox) ile döner."""
from typing import Any

from pydantic import BaseModel, Field

# bbox: [x0, y0, x1, y1] — sol üst (x0,y0), sağ alt (x1,y1). PDF: point, resim: pixel.


class BBox(BaseModel):
    """Sol üst (x0,y0) ve sağ alt (x1,y1). Sayfa koordinatları."""
    x0: float = Field(description="Sol")
    y0: float = Field(description="Üst")
    x1: float = Field(description="Sağ")
    y1: float = Field(description="Alt")


class TextBlock(BaseModel):
    """Koordinatlı metin parçası (satır veya blok)."""
    text: str = ""
    bbox: BBox = Field(description="Metin kutusu koordinatları")


class PageTable(BaseModel):
    """Tek bir tablo: satırlar + tablo ve hücre koordinatları."""
    rows: list[list[str]] = Field(description="Tablo satırları; her satır hücre string listesi")
    bbox: BBox | None = Field(default=None, description="Tablonun sayfadaki kutusu")
    cells_bbox: list[list[BBox | None]] | None = Field(
        default=None,
        description="Hücre koordinatları: cells_bbox[satır][sütun]; yoksa None",
    )


class PageResult(BaseModel):
    """Tek sayfa çıktısı: metin, koordinatlı metin blokları, koordinatlı tablolar."""
    page_number: int
    content: str = Field(default="", description="Tüm metnin birleşik hali (kolay okuma)")
    text_blocks: list[TextBlock] = Field(
        default_factory=list,
        description="Metin parçaları ve koordinatları — ne nerede",
    )
    tables: list[PageTable] = Field(default_factory=list, description="Sayfadaki tablolar (koordinatlı)")
    page_width: float | None = Field(default=None, description="Sayfa genişliği (koordinat birimi)")
    page_height: float | None = Field(default=None, description="Sayfa yüksekliği (koordinat birimi)")


class ExtractResponse(BaseModel):
    """POST /v1/* başarılı yanıtı."""
    filename: str
    method_used: str = Field(description="Kullanılan motor: auto, pdftext, pdftexttable, pdfimagev5, pdfimagets, pdftxtimage")
    processing_time_sec: float
    pages: list[PageResult]


def _to_bbox(v: Any) -> BBox | None:
    """Tuple/list [x0,y0,x1,y1] veya dict -> BBox."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 4:
        return BBox(x0=float(v[0]), y0=float(v[1]), x1=float(v[2]), y1=float(v[3]))
    if isinstance(v, dict):
        return BBox(
            x0=float(v.get("x0", v.get(0, 0))),
            y0=float(v.get("y0", v.get("top", v.get(1, 0)))),
            x1=float(v.get("x1", v.get(2, 0))),
            y1=float(v.get("y1", v.get("bottom", v.get(3, 0)))),
        )
    return None


def page_result_from_engine(
    page_number: int,
    content: str,
    tables: list[Any] | None = None,
    text_blocks: list[Any] | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
) -> PageResult:
    """Engine'den gelen ham çıktıyı PageResult'a çevirir (koordinatlar dahil)."""
    if tables is None:
        tables = []
    if text_blocks is None:
        text_blocks = []

    normalized_blocks: list[TextBlock] = []
    for b in text_blocks:
        if isinstance(b, dict):
            txt = b.get("text", "")
            box = _to_bbox(b.get("bbox"))
            if box is not None:
                normalized_blocks.append(TextBlock(text=txt, bbox=box))
            else:
                normalized_blocks.append(TextBlock(text=txt, bbox=BBox(x0=0, y0=0, x1=0, y1=0)))
        elif isinstance(b, (list, tuple)) and len(b) >= 2:
            normalized_blocks.append(
                TextBlock(text=str(b[0]), bbox=_to_bbox(b[1]) or BBox(x0=0, y0=0, x1=0, y1=0))
            )

    normalized_tables: list[PageTable] = []
    for t in tables:
        if isinstance(t, dict):
            rows = t.get("rows", [])
            if isinstance(rows, list) and rows and not isinstance(rows[0], list):
                rows = [rows]
            tbl_bbox = _to_bbox(t.get("bbox"))
            cells_bbox_raw = t.get("cells_bbox")
            cells_bbox: list[list[BBox | None]] | None = None
            if cells_bbox_raw and isinstance(cells_bbox_raw, list):
                cells_bbox = []
                for row in cells_bbox_raw:
                    if isinstance(row, list):
                        cells_bbox.append([_to_bbox(c) for c in row])
                    else:
                        cells_bbox.append([_to_bbox(row)])
            normalized_tables.append(
                PageTable(rows=rows, bbox=tbl_bbox, cells_bbox=cells_bbox)
            )
        elif isinstance(t, (list, tuple)) and len(t) > 0:
            rows = [list(row) if isinstance(row, (list, tuple)) else [str(row)] for row in t]
            normalized_tables.append(PageTable(rows=rows, bbox=None, cells_bbox=None))
        else:
            normalized_tables.append(PageTable(rows=[], bbox=None, cells_bbox=None))

    return PageResult(
        page_number=page_number,
        content=content or "",
        text_blocks=normalized_blocks,
        tables=normalized_tables,
        page_width=page_width,
        page_height=page_height,
    )
