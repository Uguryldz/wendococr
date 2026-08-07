"""
pdfimagev5 motoru: RapidOCR ile hızlı OCR (Türkçe iyileştirme + gürültü filtreleme).

KİLİTLİ: Bu modül mevcut ayarlarla stabil; sonraki işlemlerde müdahale etmeyin.
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Any
from rapidocr import RapidOCR
import re

from app.utils.text_layout import content_from_text_blocks_with_bbox

from app.config import (
    RAPIDOCR_DET_LIMIT_SIDE_LEN,
    RAPIDOCR_DET_UNCLIP_RATIO,
    RAPIDOCR_DET_BOX_THRESH,
    RAPIDOCR_DETECT_TABLES,
    RAPIDOCR_ENHANCE,
    RAPIDOCR_MIN_BOX_AREA,
    RAPIDOCR_MIN_CONFIDENCE,
    RAPIDOCR_MIN_TOKEN_LEN,
    RAPIDOCR_NUM_THREADS,
    AUTO_ROTATE_MIN_CONF,
    AUTO_ROTATE_VERIFY,
    AUTO_ROTATE_VERIFY_MARGIN,
    AUTO_ROTATE_VOTE,
    RAPIDOCR_THRESHOLD,
    RAPIDOCR_TEXT_SCORE,
)

try:
    from app.utils.image_preprocess import preprocess_image, load_image
except ImportError:
    def load_image(p): return cv2.imread(str(p))
    def preprocess_image(img, **kwargs): return img

from app.utils.turkish_postprocess import postprocess_turkish

_rapid_engine = None

def _get_rapid_engine():
    """RapidOCR örneğini Türkçe/Latin dahil çok dilli kullanım için başlatır."""
    global _rapid_engine
    if _rapid_engine is None:
        try:
            # det_limit_side_len: taranmış sayfa boyutu (960 hız/kalite dengesi)
            # text_score: 0.4 — Türkçe/Latin karakterlerde daha toleranslı tanıma
            # Thread havuzunu konteyner CPU kotasına sabitle: ONNX varsayılanı host
            # çekirdek sayısıdır, cgroup limitli konteynerde aşırı-abonelik yapıp
            # OCR'i kat kat yavaşlatır (cpus=2'de 13.4s -> 3.1s ölçüldü).
            from app.utils.cpu_limit import effective_cpus
            n_threads = RAPIDOCR_NUM_THREADS or effective_cpus()
            _rapid_engine = RapidOCR(params={
                "Det.limit_side_len": RAPIDOCR_DET_LIMIT_SIDE_LEN,
                # unclip_ratio: kesik harf/kenar kurtarma, box_thresh: soluk metin yakalama
                "Det.unclip_ratio": RAPIDOCR_DET_UNCLIP_RATIO,
                "Det.box_thresh": RAPIDOCR_DET_BOX_THRESH,
                "EngineConfig.onnxruntime.intra_op_num_threads": n_threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": n_threads,
            })
            _rapid_engine.text_score = RAPIDOCR_TEXT_SCORE
        except Exception:
            pass
    return _rapid_engine


_WHITESPACE_RE = re.compile(r"\s+")


def _enhance_for_turkish_rapid(gray: np.ndarray) -> np.ndarray:
    """
    Türkçe diakritiklerini koruyacak iyileştirme.
    - Küçük metinlerde upscale (diacritikler daha görünür)
    - CLAHE ile lokal kontrast artırma
    - Unsharp mask ile diacritik keskinleştirme (ö/ü/ç/ş/ğ/İ noktaları)
    """
    if gray is None or gray.size == 0:
        return gray
    h, w = gray.shape[:2]
    out = gray
    # Küçük görüntüleri büyüt — diacritik noktaları daha net olur
    if max(h, w) < 1400:
        out = cv2.resize(out, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        out = clahe.apply(out)
    except Exception:
        pass
    # Unsharp mask: diacritik detaylarını vurgula
    blurred = cv2.GaussianBlur(out, (0, 0), sigmaX=2.0)
    out = cv2.addWeighted(out, 1.4, blurred, -0.4, 0)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def _clean_text(text: str) -> str:
    """OCR metnini katı filtre için normalize eder."""
    text = _WHITESPACE_RE.sub(" ", (text or "").strip())
    return text

def _enhance_and_ocr(engine, img: np.ndarray):
    """CLAHE (Türkçe diacritik koruma) + RapidOCR. Döner: (result, w, h)."""
    h, w = img.shape[:2]
    if RAPIDOCR_ENHANCE and max(h, w) < 2000:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
        except Exception:
            pass
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    elif len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    result = engine(img, text_score=RAPIDOCR_TEXT_SCORE)
    return result, w, h


_QUALWORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]{3,}")


def _score(result) -> float:
    """
    Yön doğrulama metriği: 3+ harfli GERÇEK KELİME sayısı. Skor toplamından iyi ayırır —
    yanlış yönde OCR kısa/karışık token üretir; doğru yönde okunaklı kelimeler çıkar
    (ölçüm: doğru dönüş +85 kelime, yanlış dönüş -7 kelime; skor toplamı bunu kaçırıyordu).
    """
    try:
        if not result or not result.txts:
            return 0.0
        return float(sum(len(_QUALWORD_RE.findall(t or "")) for t in result.txts))
    except Exception:
        return 0.0


def _four_way_vote(engine, img, apply_rotation):
    """0/90/180/270'i OCR'layıp en çok gerçek kelime üreteni seç (OSD çökünce fallback).
    0°'ye MARJIN kadar öncelik verilir -> eşit/belirsizde döndürme yok (güvenli)."""
    best = None  # (score, img, result, w, h)
    for ang in (0, 90, 180, 270):
        cand = img if ang == 0 else apply_rotation(img, ang)
        r, w, h = _enhance_and_ocr(engine, cand)
        s = _score(r) * (1.0 + AUTO_ROTATE_VERIFY_MARGIN) if ang == 0 else _score(r)
        if best is None or s > best[0]:
            best = (s, cand, r, w, h)
    return best[1], best[2], best[3], best[4]


def _oriented_ocr(engine, img: np.ndarray, auto_rotate: bool):
    """
    Yön kararı + OCR. Döner: (kullanılan_img, result, w, h).
    Düşük güvende OCR-skoru ile doğrulama yapar (bkz. config AUTO_ROTATE_VERIFY).
    OSD çökerse 4-yön OCR oylamasına düşer (AUTO_ROTATE_VOTE).
    """
    if not auto_rotate:
        r, w, h = _enhance_and_ocr(engine, img)
        return img, r, w, h
    try:
        from app.utils.orientation import detect_rotation_candidate, apply_rotation, OSD_UNKNOWN
    except Exception:
        r, w, h = _enhance_and_ocr(engine, img)
        return img, r, w, h

    angle, conf = detect_rotation_candidate(img)
    if angle == OSD_UNKNOWN:
        # OSD karar veremedi -> 4-yön oylama (açıksa); değilse dokunma.
        if AUTO_ROTATE_VOTE:
            return _four_way_vote(engine, img, apply_rotation)
        r, w, h = _enhance_and_ocr(engine, img)
        return img, r, w, h
    if angle == 0:
        r, w, h = _enhance_and_ocr(engine, img)
        return img, r, w, h
    if conf >= AUTO_ROTATE_MIN_CONF:
        # OSD emin: doğrudan döndür, tek geçiş
        rimg = apply_rotation(img, angle)
        r, w, h = _enhance_and_ocr(engine, rimg)
        return rimg, r, w, h
    if not AUTO_ROTATE_VERIFY:
        r, w, h = _enhance_and_ocr(engine, img)
        return img, r, w, h
    # Düşük güven + sıfırdan farklı açı: OSD yönüne GÜVEN, ama 0° ile karşılaştır.
    # OSD yönü fişlerde bile doğru; sadece 0° skoru öneriyi MARJIN kadar AŞARSA 0°'de kal
    # (OSD'nin nadiren dik belgeyi yanlış döndürmesine karşı emniyet).
    r0, w0, h0 = _enhance_and_ocr(engine, img)
    rimg = apply_rotation(img, angle)
    rr, wr, hr = _enhance_and_ocr(engine, rimg)
    # Döndürülmüş yön SADECE belirgin daha çok gerçek kelime üretirse seçilir; aksi halde 0°.
    if _score(rr) > _score(r0) * (1.0 + AUTO_ROTATE_VERIFY_MARGIN):
        return rimg, rr, wr, hr
    return img, r0, w0, h0


def _run_rapidocr(
    image_bytes: bytes | None = None,
    image_array: np.ndarray | None = None,
    auto_rotate: bool = True,
) -> tuple[list[tuple[list[float], str]], int, int]:
    """
    Hız odaklı RapidOCR motoru.

    auto_rotate=False: yön düzeltme atlanır. Çağıran, kutuları ORIJINAL sayfa
    koordinatına geri map'liyorsa (hybrid _ocr_region) döndürme koordinatları
    kaydıracağı için kapatılmalı; sayfa yönü çağıran tarafta ele alınır.
    """
    engine = _get_rapid_engine()
    if engine is None:
        return [], 0, 0

    # 1. Görseli Yükle
    if image_array is not None:
        img = image_array.copy()
    elif image_bytes:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    else:
        return [], 0, 0

    if img is None:
        return [], 0, 0

    # 1b. Otomatik yön düzeltme (auto_rotate). İki mod:
    #  - OSD güveni yüksek (>=MIN_CONF) veya r0: doğrudan uygula, TEK OCR geçişi (hız aynı).
    #  - OSD sıfırdan farklı açı önerir ama güven düşük (fiş/fatura fotoğrafı): 0° ve önerilen
    #    açıda OCR'layıp güven skoru toplamı MARJIN kadar yüksek olanı seç (yanlış döndürmeyi
    #    önler). Emin olmadıkça 0°'de kalır.
    img, result, w, h = _oriented_ocr(engine, img, auto_rotate)

    if result is None or result.boxes is None or len(result.boxes) == 0:
        return [], w, h

    # 4. Koordinatları topla + katı filtre uygula
    out = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        score = float(score) if score is not None else None

        text = _clean_text(text)
        if not text:
            continue
        # Türkçe post-processing: diacritik restorasyon + artefakt temizleme
        text = postprocess_turkish(text)
        if not text:
            continue
        if len(text) < RAPIDOCR_MIN_TOKEN_LEN and not any(ch.isdigit() for ch in text):
            continue
        if score is not None and score < RAPIDOCR_MIN_CONFIDENCE:
            continue

        # Bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        box_arr = np.array(box)
        x_min, y_min = np.min(box_arr, axis=0)
        x_max, y_max = np.max(box_arr, axis=0)
        area = max(0.0, float(x_max - x_min)) * max(0.0, float(y_max - y_min))
        if area < RAPIDOCR_MIN_BOX_AREA:
            continue

        bbox = [float(x_min), float(y_min), float(x_max), float(y_max)]
        out.append((bbox, text))

    return out, w, h

def _detect_tables(img: np.ndarray, text_blocks: list[dict]) -> list[dict[str, Any]]:
    """
    OpenCV cizgi tabanli hafif tablo tespiti (resim OCR icin).
    Yatay+dikey cizgilerin kesistigi bolgeleri tablo kutusu kabul eder,
    kutu icine dusen text_block'lari satir (y) bazinda gruplayarak rows uretir.
    Cizgi yoksa bos liste doner (cizgisiz tablo tespit etmez — yanlis pozitif onleme).
    """
    if img is None or img.size == 0 or not text_blocks:
        return []
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 15, -2)
        h, w = gray.shape[:2]
        # Yatay ve dikey cizgi maskeleri (sayfa boyutuna olcekli kernel)
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 30)))
        horiz = cv2.erode(bw, hk); horiz = cv2.dilate(horiz, hk)
        vert = cv2.erode(bw, vk); vert = cv2.dilate(vert, vk)
        grid = cv2.add(horiz, vert)
        cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        tables = []
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            # Cok kucuk veya cizgi-ince bolgeleri ele (gercek tablo degil)
            if cw < w * 0.15 or ch < h * 0.04 or cw * ch < (w * h) * 0.01:
                continue
            inside = [b for b in text_blocks
                      if b["bbox"][0] >= x - 5 and b["bbox"][1] >= y - 5
                      and b["bbox"][2] <= x + cw + 5 and b["bbox"][3] <= y + ch + 5]
            if len(inside) < 2:
                continue
            # Satir bazinda grupla (y ortasi)
            inside.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
            rows, cur, cy = [], [], None
            for b in inside:
                ym = (b["bbox"][1] + b["bbox"][3]) / 2
                if cy is None or abs(ym - cy) <= (b["bbox"][3] - b["bbox"][1]) * 0.7:
                    cur.append(b); cy = ym if cy is None else (cy + ym) / 2
                else:
                    rows.append(cur); cur = [b]; cy = ym
            if cur:
                rows.append(cur)
            row_texts = [[bb["text"] for bb in sorted(r, key=lambda b: b["bbox"][0])] for r in rows]
            tables.append({
                "rows": row_texts,
                "bbox": [float(x), float(y), float(x + cw), float(y + ch)],
                "cells_bbox": [[bb["bbox"] for bb in sorted(r, key=lambda b: b["bbox"][0])] for r in rows],
            })
        return tables
    except Exception:
        return []


def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    *,
    image_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    Ana OCR fonksiyonu.
    """
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    img_for_tables = None
    if image_bytes:
        lines_bbox, page_width, page_height = _run_rapidocr(image_bytes=image_bytes)
        if RAPIDOCR_DETECT_TABLES:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img_for_tables = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif file_path:
        file_path = Path(file_path)
        if not file_path.exists(): return []
        img = load_image(str(file_path))
        lines_bbox, page_width, page_height = _run_rapidocr(image_array=img)
        if RAPIDOCR_DETECT_TABLES:
            img_for_tables = img
    else:
        return []

    text_blocks = [{"text": t, "bbox": b} for b, t in lines_bbox]
    content = content_from_text_blocks_with_bbox(text_blocks)
    tables = _detect_tables(img_for_tables, text_blocks) if RAPIDOCR_DETECT_TABLES else []

    return [{
        "page_number": page_no,
        "content": content,
        "tables": tables,
        "text_blocks": text_blocks,
        "page_width": float(page_width),
        "page_height": float(page_height),
    }]