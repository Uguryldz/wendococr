"""Sayfa icindeki gorsel objeleri tespit et — logo/qr/barkod/damga/imza vb.

PDF icin pymupdf (fitz) ile gercek embedded image XObject'leri ve vector drawings
direkt cikarilir. Raster (PNG/JPG) icin OpenCV ile contour detection yapilir.

Donen format:
    [{"type": str, "bbox": [x0,y0,x1,y1], "page_index": int, "preview": str, "reason": str}]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # pymupdf
import cv2
import numpy as np


def _classify_object(width: float, height: float, page_w: float, page_h: float) -> tuple[str, str]:
    """Bbox boyutuna gore kabaca tip ve gerekce uret."""
    if width <= 0 or height <= 0:
        return "junk", "Sifir alan"
    aspect = width / max(height, 1)
    area_ratio = (width * height) / max(page_w * page_h, 1)
    # QR: kare oran + makul boyut
    if 0.7 <= aspect <= 1.4 and 0.005 <= area_ratio <= 0.15:
        return "qr", "Kare oran (QR/2D barkod)"
    # Barkod: cok yatay
    if aspect > 4 and area_ratio < 0.1:
        return "barcode", "Yatay oran (1D barkod)"
    # Damga/imza: orta boyut, dikdortgenimsi
    if 1.0 <= aspect <= 3.0 and 0.01 <= area_ratio <= 0.2:
        return "stamp", "Damga/imza ihtimali"
    # Diger image objeler logo varsayilir
    return "logo", "Sayfada gomulu gorsel"


def detect_pdf_objects(file_path: str | Path, page_numbers: list[int] | None = None) -> list[dict[str, Any]]:
    """
    PDF icindeki embedded image XObject'lerin bbox'larini cikar.
    Sadece dijital PDF'lerde calisir (raster/scan PDF'lerde page tek bir buyuk image olur).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        doc = fitz.open(file_path)
        indices = page_numbers if page_numbers is not None else list(range(len(doc)))
        for i in indices:
            if i < 0 or i >= len(doc):
                continue
            page = doc[i]
            page_w = page.rect.width
            page_h = page.rect.height
            try:
                images = page.get_images(full=True)
            except Exception:
                images = []
            seen_keys: set[str] = set()
            for img_info in images:
                xref = img_info[0] if img_info else None
                if xref is None:
                    continue
                # Bbox'i bul — pymupdf'in get_image_bbox'i transform-aware
                try:
                    bboxes = page.get_image_rects(xref)  # 1.23+
                except AttributeError:
                    try:
                        bboxes = [page.get_image_bbox(img_info)]
                    except Exception:
                        continue
                except Exception:
                    continue
                for rect in bboxes:
                    if rect is None:
                        continue
                    try:
                        x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
                    except Exception:
                        continue
                    if x1 <= x0 or y1 <= y0:
                        continue
                    # Tum sayfayi kaplayan image (raster pdf): atla
                    if (x1 - x0) >= page_w * 0.95 and (y1 - y0) >= page_h * 0.95:
                        continue
                    key = f"{i}:{round(x0)}:{round(y0)}:{round(x1)}:{round(y1)}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    obj_type, reason = _classify_object(x1 - x0, y1 - y0, page_w, page_h)
                    out.append({
                        "id": f"pdfimg_{i}_{xref}_{len(out)}",
                        "type": obj_type,
                        "bbox": [x0, y0, x1, y1],
                        "page_index": i,
                        "preview": f"PDF image xref={xref}",
                        "reason": f"PDF embedded image — {reason}",
                    })
        doc.close()
    except Exception:
        pass
    return out


def detect_image_objects(image_path: str | Path, page_index: int = 0) -> list[dict[str, Any]]:
    """
    Raster image (PNG/JPG/scan PDF render) icinde gorsel obje contour detection.
    Stratejii: edge detection -> contour -> filtre (yeterince buyuk + dikdortgenimsi).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return []
    img = cv2.imread(str(image_path))
    if img is None:
        return []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # QR/barkod blokları icin: yuksek frekansli gradyan bolgeleri
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(grad_x, grad_y)
    grad = np.clip(grad, 0, 255).astype(np.uint8)
    _, thresh = cv2.threshold(grad, 50, 255, cv2.THRESH_BINARY)
    # Morfolojik close: yakin gradyanlari birlestir
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[dict[str, Any]] = []
    page_area = w * h
    for idx, c in enumerate(contours):
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        area_ratio = area / max(page_area, 1)
        # Cok kucuk veya cok buyuk olanlari at
        if area_ratio < 0.005 or area_ratio > 0.4:
            continue
        # Cok ince/uzun seritleri at (text satirlari)
        aspect = cw / max(ch, 1)
        if 0.05 < aspect < 20.0:
            obj_type, reason = _classify_object(cw, ch, w, h)
            out.append({
                "id": f"img_{page_index}_{idx}",
                "type": obj_type,
                "bbox": [float(x), float(y), float(x + cw), float(y + ch)],
                "page_index": page_index,
                "preview": f"contour {cw}x{ch}",
                "reason": f"Raster contour — {reason}",
            })
    # Cok sayida kucuk contour text yuzunden cikabilir; sayiyi sinirla
    out.sort(key=lambda o: -(o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]))
    return out[:20]
