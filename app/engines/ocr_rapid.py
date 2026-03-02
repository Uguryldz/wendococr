import cv2
import numpy as np
from pathlib import Path
from typing import Any
from rapidocr_onnxruntime import RapidOCR

# Gerekli yardımcı fonksiyonları projenden alıyoruz
# Eğer preprocess_image hala yavaşsa, aşağıda nasıl devre dışı bırakacağını belirttim.
try:
    from app.utils.image_preprocess import preprocess_image, load_image
except ImportError:
    # Yedek fonksiyonlar (Eğer import hata verirse diye)
    def load_image(p): return cv2.imread(str(p))
    def preprocess_image(img, **kwargs): return img

_rapid_engine = None

def _get_rapid_engine():
    """RapidOCR örneğini optimize edilmiş parametrelerle başlatır."""
    global _rapid_engine
    if _rapid_engine is None:
        try:
            # det_limit_side_len: Yazı alanı ararken resmin uzun kenarını bu değere sabitler.
            # 720 veya 960 hızı %300-400 artırır. 1280 çok keskindir ama yavaştır.
            _rapid_engine = RapidOCR(det_limit_side_len=960) 
        except Exception:
            pass
    return _rapid_engine

def _run_rapidocr(
    image_bytes: bytes | None = None,
    image_array: np.ndarray | None = None,
) -> tuple[list[tuple[list[float], str]], int, int]:
    """
    Hız odaklı RapidOCR motoru.
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

    h, w = img.shape[:2]

    # 2. Ön İşleme (DARBOĞAZ BURASI OLABİLİR)
    # Eğer hala yavaşsa: grayscale=False, threshold=False yaparak dene.
    # Yüksek çözünürlükte threshold işlemi CPU'yu çok yorar.
    if max(h, w) > 2000:
        # Çok büyük resimlerde ön işlemeyi sadece basit gri tonlamaya indiriyoruz
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        img = preprocess_image(img, grayscale=True, threshold=True, deskew=False)

    # RapidOCR 3 kanal (BGR) beklediği için gerekirse dönüştür
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # 3. OCR İşlemi
    # det_limit_side_len zaten engine içinde set edildiği için burada hızlı çalışacaktır.
    result, _ = engine(img)
    
    if not result:
        return [], w, h

    # 4. Koordinatları Topla (NumPy ile hızlandırılmış)
    out = []
    for line in result:
        box, text = line[0], line[1]
        if not text:
            continue
        
        # Bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        box_arr = np.array(box)
        x_min, y_min = np.min(box_arr, axis=0)
        x_max, y_max = np.max(box_arr, axis=0)
        
        bbox = [float(x_min), float(y_min), float(x_max), float(y_max)]
        out.append((bbox, text))

    return out, w, h

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

    if image_bytes:
        lines_bbox, page_width, page_height = _run_rapidocr(image_bytes=image_bytes)
    elif file_path:
        file_path = Path(file_path)
        if not file_path.exists(): return []
        img = load_image(str(file_path))
        lines_bbox, page_width, page_height = _run_rapidocr(image_array=img)
    else:
        return []

    text_blocks = [{"text": t, "bbox": b} for b, t in lines_bbox]
    content = "\n".join(t for _, t in lines_bbox)

    return [{
        "page_number": page_no,
        "content": content,
        "tables": [],
        "text_blocks": text_blocks,
        "page_width": float(page_width),
        "page_height": float(page_height),
    }]