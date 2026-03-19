import json
import os
import time
import sys
from pathlib import Path

import cv2
import numpy as np
from paddleocr import PaddleOCR


def to_json_serializable(value):
    """Numpy ve benzeri tipleri JSON uyumlu hale getirir."""
    if isinstance(value, dict):
        return {str(k): to_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_serializable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _to_api_bbox(box):
    """[x0,y0,x1,y1] benzeri veriyi API bbox objesine çevirir."""
    if box is None:
        return {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}
    box = to_json_serializable(box)
    if isinstance(box, dict):
        return {
            "x0": float(box.get("x0", 0.0)),
            "y0": float(box.get("y0", 0.0)),
            "x1": float(box.get("x1", 0.0)),
            "y1": float(box.get("y1", 0.0)),
        }
    if isinstance(box, list) and len(box) >= 4:
        return {
            "x0": float(box[0]),
            "y0": float(box[1]),
            "x1": float(box[2]),
            "y1": float(box[3]),
        }
    return {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}


def build_api_compatible_output(raw_result, image_path, processing_time_sec):
    res = raw_result.get("res", {})
    texts = res.get("rec_texts", [])
    boxes = res.get("rec_boxes", [])

    text_blocks = []
    for i, text in enumerate(texts):
        box = boxes[i] if i < len(boxes) else None
        text_blocks.append(
            {
                "text": text,
                "bbox": _to_api_bbox(box),
            }
        )

    content = "\n".join([block["text"] for block in text_blocks if block["text"]])
    img = cv2.imread(str(image_path))
    page_height, page_width = (0.0, 0.0) if img is None else (float(img.shape[0]), float(img.shape[1]))

    return {
        "filename": image_path.name,
        "method_used": "pdfimagev5",
        "processing_time_sec": round(float(processing_time_sec), 3),
        "pages": [
            {
                "page_number": 1,
                "content": content,
                "text_blocks": text_blocks,
                "tables": [],
                "page_width": page_width,
                "page_height": page_height,
            }
        ],
    }


def _resize_if_needed(image_path: Path, *, max_side: int, output_dir: Path) -> Path:
    """
    Çok büyük görsellerde RAM patlamasını önlemek için indirgeme yapar.
    PaddleOCR bbox koordinatları küçültülmüş görüntüye göre olur.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return image_path

    h, w = img.shape[:2]
    max_dim = max(h, w)
    if max_dim <= max_side:
        return image_path

    scale = float(max_side) / float(max_dim)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    resized_path = output_dir / f"{image_path.stem}_resized_max{max_side}.png"
    cv2.imwrite(str(resized_path), resized)
    return resized_path


def main():
    # Bu ortamda oneDNN/PIR kaynaklı runtime hatasını azaltmak için CPU+MKLDNN kapatılır.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")

    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "test" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    input_arg = sys.argv[1] if len(sys.argv) > 1 else str(project_root / "test" / "aa.jpg")
    image_path = Path(input_arg).resolve()
    output_json = output_dir / f"{image_path.stem}_ocr_result.json"

    # Bellek için: çok büyük görselleri küçült.
    max_side = int(os.environ.get("PADDLEOCR_MAX_SIDE", "2000"))
    image_path_for_ocr = _resize_if_needed(
        image_path,
        max_side=max_side,
        output_dir=output_dir,
    )

    text_det_limit_side_len = int(os.environ.get("PADDLEOCR_TEXT_DET_LIMIT", str(max_side)))
    text_det_limit_type = os.environ.get("PADDLEOCR_TEXT_DET_LIMIT_TYPE", "min")

    ocr = PaddleOCR(
        # Bellek/hız için hafif mod başlangıcı.
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        device="cpu",
        # Text detector input boyutunu sınırlayarak RAM kullanımını düşürür.
        text_det_limit_side_len=text_det_limit_side_len,
        text_det_limit_type=text_det_limit_type,
    )

    start = time.perf_counter()
    result = ocr.predict(input=str(image_path_for_ocr))
    first_result = next(iter(result))
    raw_result = first_result.json
    elapsed = time.perf_counter() - start

    clean_output = build_api_compatible_output(raw_result, image_path_for_ocr, elapsed)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(clean_output, f, ensure_ascii=False, indent=2)

    print(f"JSON çıktı yazıldı: {output_json}")
    print(f"Toplam sayfa: {len(clean_output['pages'])}")


if __name__ == "__main__":
    main()