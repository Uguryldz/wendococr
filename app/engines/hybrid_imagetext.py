"""
imagetexthybrid motoru: Dijital metin + görsel-içi metni TEK geçişte, doğru okuma
sırasıyla birleştirir.

Neden gerekli:
  Resmi yazışmalarda (mahkeme/savcılık/belediye/birlik yazıları) sayfa çoğunlukla
  dijital metindir AMA antet/logo/kaşe bölgesi yalnızca GÖRSEL olarak gömülüdür.
  - pdftext  → görseldeki anteti tamamen kaçırır.
  - pdfimagev5 → tüm sayfayı OCR'lar; dijital metnin kesinliğini kaybeder.
  - pdftxtimage → tam-sayfa gömülü görselde metnin tamamını ikinci kez OCR'layıp
    çift kayıt üretir.

Yöntem (sayfa başına):
  1. Dijital metin satırları bbox'larıyla çıkarılır (kesin, hızlı).
  2. Metnin KAPLAMADIĞI yatay boşluk bantları bulunur (gap band).
  3. Bu bantlar gömülü görsel alanlarıyla kesiştirilir → aday bölgeler.
  4. Aday bölgede gerçekten mürekkep var mı diye ucuz bir ön kontrol yapılır.
  5. Sadece bu bölgeler OCR'lanır (RapidOCR), koordinatlar sayfa uzayına geri map'lenir.
  6. Dijital satırlar + OCR satırları y/x'e göre birleştirilip layout korunarak yazılır.

Neden "bant" temelli (2B maske değil):
  Tam sayfayı kaplayan görselde metnin komplementi tek bir bağlantılı "çerçeve"dir;
  2B bileşen analizi bunu tüm sayfa olarak döndürür ve her şeyi ikinci kez OCR'lar.
  Bant yaklaşımı bu tuzağa düşmez: metin içeren y aralıkları baştan elenir.

Kullanılan kütüphaneler:
  - PyMuPDF (fitz): dijital metin/görsel geometrisi, bölgesel render
  - app.engines.ocr_rapid: RapidOCR (Türkçe ayarlı, postprocess dahil)
  - app.utils.text_layout: bbox'a göre layout korumalı metin üretimi
"""
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import numpy as np

from app.config import (
    HYBRID_DEDUP,
    HYBRID_DPI,
    HYBRID_GAP_MIN_HEIGHT,
    HYBRID_MIN_INK_RATIO,
    HYBRID_MIN_NATIVE_CHARS,
    HYBRID_MIN_REGION_AREA,
    HYBRID_MIN_REGION_WIDTH,
    HYBRID_TEXT_PAD,
    RAPIDOCR_DET_LIMIT_SIDE_LEN,
)
from app.utils.text_layout import content_from_text_blocks_with_bbox

_NORM_RE = re.compile(r"[^0-9a-zçğıöşü]+")


def _norm(text: str) -> str:
    """Karşılaştırma için sadeleştirme (Türkçe duyarlı küçültme + alfanümerik dışı at)."""
    return _NORM_RE.sub("", (text or "").replace("I", "ı").replace("İ", "i").lower())


# ── 1. Dijital metin ────────────────────────────────────────────────────────

def _native_lines(page) -> list[dict[str, Any]]:
    """Sayfadaki dijital metin satırları: [{"text", "bbox", "source"}]."""
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if not text:
                continue
            b = line["bbox"]
            lines.append({
                "text": text,
                "bbox": [float(b[0]), float(b[1]), float(b[2]), float(b[3])],
                "source": "native",
            })
    return lines


# ── 2. Görsel alanları ve boşluk bantları ───────────────────────────────────

def _image_rects(page) -> list[fitz.Rect]:
    """Sayfadaki gömülü görsellerin dikdörtgenleri (sayfa sınırına kırpılmış)."""
    rects: list[fitz.Rect] = []
    for info in page.get_image_info(hashes=False):
        try:
            r = fitz.Rect(info["bbox"]) & page.rect
        except Exception:
            continue
        if r.is_empty or r.width < 5 or r.height < 5:
            continue
        rects.append(r)
    return rects


def _gap_bands(text_bboxes: list[list[float]], page_rect) -> list[tuple[float, float]]:
    """
    Dijital metnin kaplamadığı yatay bantlar.
    Metin y-aralıkları HYBRID_TEXT_PAD kadar şişirilip birleştirilir; kalan boşluklar
    aday banttır. Bu sayede metin satırlarının kenarından kırpılmış harf parçaları
    OCR'a girmez.
    """
    spans = sorted(
        (max(page_rect.y0, b[1] - HYBRID_TEXT_PAD), min(page_rect.y1, b[3] + HYBRID_TEXT_PAD))
        for b in text_bboxes
    )
    merged: list[list[float]] = []
    for y0, y1 in spans:
        if merged and y0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])

    bands: list[tuple[float, float]] = []
    cursor = float(page_rect.y0)
    for y0, y1 in merged:
        if y0 - cursor >= HYBRID_GAP_MIN_HEIGHT:
            bands.append((cursor, y0))
        cursor = max(cursor, y1)
    if page_rect.y1 - cursor >= HYBRID_GAP_MIN_HEIGHT:
        bands.append((cursor, float(page_rect.y1)))
    return bands


def _candidate_regions(page, native: list[dict[str, Any]]) -> list[fitz.Rect]:
    """Boşluk bantları × görsel alanları kesişimi → OCR'lanacak bölgeler."""
    img_rects = _image_rects(page)
    if not img_rects:
        return []
    bands = _gap_bands([l["bbox"] for l in native], page.rect)

    regions: list[fitz.Rect] = []
    for y0, y1 in bands:
        band = fitz.Rect(page.rect.x0, y0, page.rect.x1, y1)
        hits = [r & band for r in img_rects]
        hits = [r for r in hits if not r.is_empty and r.width >= HYBRID_MIN_REGION_WIDTH]
        if not hits:
            continue
        # Aynı bantta örtüşen görselleri tek bölgeye indir (mükerrer OCR olmasın)
        merged = fitz.Rect(hits[0])
        for r in hits[1:]:
            merged |= r
        # Logo/kaşe kenarındaki ince dilimler metin taşımaz, sadece süre yakar
        if merged.height < HYBRID_GAP_MIN_HEIGHT or merged.get_area() < HYBRID_MIN_REGION_AREA:
            continue
        regions.append(merged)
    return regions


# ── 3. Mürekkep ön kontrolü ────────────────────────────────────────────────

def _has_ink(page, clip: fitz.Rect) -> bool:
    """
    Bölgede yazı olabilecek kadar koyu piksel var mı? Düşük çözünürlükte bakılır —
    boş sayfa boşluklarını OCR'lamamak için ucuz bir eleme.
    """
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), clip=clip, colorspace=fitz.csGRAY)
        if pix.width == 0 or pix.height == 0:
            return False
        arr = np.frombuffer(pix.samples, dtype=np.uint8)
        return float((arr < 200).mean()) >= HYBRID_MIN_INK_RATIO
    except Exception:
        return True  # emin değilsek OCR'la — içerik kaybetmektense fazladan bakarız


# ── 4. Bölgesel OCR ────────────────────────────────────────────────────────

def _ocr_region(page, clip: fitz.Rect) -> list[dict[str, Any]]:
    """Bölgeyi render edip OCR'lar; kutuları sayfa koordinat uzayına geri map'ler."""
    from app.engines.ocr_rapid import _run_rapidocr

    zoom = HYBRID_DPI / 72.0
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    except Exception:
        return []
    if pix.width == 0 or pix.height == 0:
        return []

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    else:
        # fitz RGB üretir, _run_rapidocr cv2 konvansiyonu (BGR) bekler — çevirmezsek
        # gri tonlama ağırlıkları kayar ve diacritik tespiti zayıflar.
        img = img[:, :, 2::-1]
    # RapidOCR det ayarı limit_type="min": kısa kenar limit_side_len'in altındaysa görüntüyü
    # yukarı ölçekler. İnce şeritlerde bu 6x büyütmeye ve tam sayfadan 5 kat YAVAŞ tespite yol
    # açar. Kısa kenarı beyazla limite tamamlarsak ölçek 1.0 kalır: içerik 200 DPI'da (auto ile
    # aynı kalite), maliyet tam sayfa seviyesinde. Dolgu sağ/alta olduğu için koordinatlar kaymaz.
    h, w = img.shape[:2]
    if min(h, w) < RAPIDOCR_DET_LIMIT_SIDE_LEN:
        pad_h = max(0, RAPIDOCR_DET_LIMIT_SIDE_LEN - h)
        pad_w = max(0, RAPIDOCR_DET_LIMIT_SIDE_LEN - w)
        img = np.pad(img, ((0, pad_h), (0, pad_w), (0, 0)), constant_values=255)
    img = np.ascontiguousarray(img)

    lines_bbox, _, _ = _run_rapidocr(image_array=img)

    out: list[dict[str, Any]] = []
    for bbox, text in lines_bbox:
        out.append({
            "text": text,
            "bbox": [
                clip.x0 + bbox[0] / zoom, clip.y0 + bbox[1] / zoom,
                clip.x0 + bbox[2] / zoom, clip.y0 + bbox[3] / zoom,
            ],
            "source": "ocr",
        })
    return out


# ── 5. Sayfa işleme ────────────────────────────────────────────────────────

def _dedup(ocr_lines: list[dict[str, Any]], native: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dijital metinde zaten geçen OCR satırlarını eler."""
    if not HYBRID_DEDUP or not native:
        return ocr_lines
    haystack = _norm(" ".join(l["text"] for l in native))
    kept = []
    for l in ocr_lines:
        n = _norm(l["text"])
        if len(n) >= 3 and n in haystack:
            continue
        kept.append(l)
    return kept


def _process_page(page) -> dict[str, Any]:
    native = _native_lines(page)
    native_chars = sum(len(l["text"]) for l in native)

    if native_chars < HYBRID_MIN_NATIVE_CHARS:
        # Saf taranmış sayfa: tüm sayfayı OCR'la
        lines = _ocr_region(page, fitz.Rect(page.rect))
        mode = "ocr_full"
    else:
        ocr_lines: list[dict[str, Any]] = []
        for clip in _candidate_regions(page, native):
            if not _has_ink(page, clip):
                continue
            ocr_lines.extend(_ocr_region(page, clip))
        ocr_lines = _dedup(ocr_lines, native)
        lines = native + ocr_lines
        mode = "hybrid" if ocr_lines else "native"

    lines.sort(key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    text_blocks = [{"text": l["text"], "bbox": l["bbox"], "source": l["source"]} for l in lines]
    return {
        "content": content_from_text_blocks_with_bbox(text_blocks),
        "text_blocks": text_blocks,
        "page_width": float(page.rect.width),
        "page_height": float(page.rect.height),
        "page_mode": mode,
    }


# ── 6. Motor arayüzü ───────────────────────────────────────────────────────

def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Proje motor arayüzü. PDF ise sayfa bazlı hibrit; resim ise doğrudan OCR.
    Döner: [{page_number, content, tables, text_blocks, page_width, page_height}]
    """
    path = Path(file_path) if file_path else None
    if not path or not path.exists():
        return []

    # PDF olmayan girdi (jpg/png/tiff...): hibrit ayrımı anlamsız, doğrudan OCR
    if path.suffix.lower() != ".pdf":
        from app.engines.ocr_rapid import extract as rapid_extract
        return rapid_extract(path, page_numbers=page_numbers)

    out: list[dict[str, Any]] = []
    doc = None
    try:
        doc = fitz.open(path)
        total = len(doc)
        targets = list(range(total)) if page_numbers is None else [
            i for i in page_numbers if 0 <= i < total
        ]
        for idx in targets:
            page_data = _process_page(doc.load_page(idx))
            out.append({
                "page_number": idx + 1,
                "tables": [],
                **page_data,
            })
    except Exception:
        return out
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    return out
