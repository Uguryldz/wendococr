#!/usr/bin/env python3
"""
GLM-OCR (Ollama) ile basit belge OCR.
  ollama pull glm-ocr
  ollama serve

Layout: GLM-OCR tarzı (index, label, content, bbox_2d) ile layout koruyan JSON üretir;
JavaScript tarafında aynı yapı kullanılabilir (kaynak: https://github.com/zai-org/GLM-OCR).

Kullanım:
  python test/glm_ocr_ollama_test.py resim.png
  python test/glm_ocr_ollama_test.py belge.pdf -o ./cikti/
  python test/glm_ocr_ollama_test.py belge.pdf -o ./cikti/ --layout-json   # layout JSON + .layout.js
"""
import argparse
import base64
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import ollama
    from ollama import ResponseError
except ImportError:
    print("pip install ollama", file=sys.stderr)
    sys.exit(1)

from app.utils.pdf_convert import iter_pdf_pages_as_images, pdf_page_count

PROMPT = "Text recognition and Table recognition. Extract all text and tables. Output in Markdown."
MODEL = "glm-ocr"


# --- Layout: GLM-OCR tarzı çıktı (https://github.com/zai-org/GLM-OCR) ---
# Sayfa başına: [[{ "index", "label", "content", "bbox_2d" }, ...]]
# Ollama çıktısında bbox yok; label'ları Markdown/HTML'den çıkarıyoruz.

def content_to_layout_blocks(content: str, page: int = 1) -> list[dict]:
    """
    Tek sayfa OCR metnini (Markdown veya HTML) GLM-OCR layout bloklarına çevirir.
    Döner: [{ "index", "label", "content", "bbox_2d" }, ...]
    """
    blocks = []
    idx = 0

    # HTML tablo: label "table", content ham HTML
    table_pattern = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
    for m in table_pattern.finditer(content):
        blocks.append({
            "index": idx,
            "label": "table",
            "content": m.group(0).strip(),
            "bbox_2d": None,
        })
        idx += 1

    # Tabloları çıkarılmış metin
    rest = table_pattern.sub("\n\n", content)

    # Markdown tablo (önce tabloları topla, sonra rest'ten çıkar)
    md_table_pattern = re.compile(r"(\|[^\n]+\|\n)((?:\|[^\n]+\|\n?)+)", re.MULTILINE)
    for m in md_table_pattern.finditer(rest):
        full = m.group(0)
        blocks.append({
            "index": idx,
            "label": "table",
            "content": full.strip(),
            "bbox_2d": None,
        })
        idx += 1
    rest = md_table_pattern.sub("\n\n", rest)
    rest = rest.strip()

    # Başlık ve paragrafları sırayla tara (layout sırası korunsun)
    # Önce satır/blok bazlı böl, sonra her birini title veya text olarak etiketle
    for part in re.split(r"\n\s*\n", rest):
        part = part.strip()
        if not part:
            continue
        if re.match(r"^#{1,3}\s", part):
            title_match = re.match(r"^#{1,3}\s+(.+)$", part, re.DOTALL)
            content = title_match.group(1).strip() if title_match else part
            label = "title"
        else:
            content = part
            label = "text"
        blocks.append({
            "index": idx,
            "label": label,
            "content": content,
            "bbox_2d": None,
        })
        idx += 1

    return blocks


def build_layout_json(pages: list[dict]) -> dict:
    """
    Sayfa listesinden GLM-OCR uyumlu layout JSON üretir.
    Yapı: { "filename", "pages": [ { "page", "content", "layout": [ { index, label, content, bbox_2d }, ... ] } ], "layout_pages": [[ {...}, ... ], ...] }
    layout_pages: sayfa başına blok listesi (SDK tarzı).
    """
    layout_pages = []
    for p in pages:
        blocks = content_to_layout_blocks(p["content"], p.get("page", 1))
        layout_pages.append(blocks)
        p["layout"] = blocks
    return {"layout_pages": layout_pages}


def ocr(image: Path | bytes, prompt: str = PROMPT) -> str:
    """Tek görüntüyü GLM-OCR ile işler."""
    if isinstance(image, bytes):
        payload = [base64.b64encode(image).decode("ascii")]
    else:
        if not Path(image).exists():
            raise FileNotFoundError(str(image))
        payload = [str(Path(image).resolve())]

    try:
        r = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt, "images": payload}])
        return (r.message.content or "").strip()
    except ResponseError as e:
        if getattr(e, "status_code", -1) == 500 or "ggml" in (getattr(e, "error", "") or str(e)).lower():
            raise RuntimeError("GLM-OCR hatası (GGML). Ollama 0.16.3/0.17.0 deneyin veya: ollama pull glm-ocr:bf16") from e
        raise RuntimeError(str(e)) from e


def run(
    path: Path,
    output_dir: Path | None = None,
    prompt: str = PROMPT,
    dpi: int = 150,
    layout_json: bool = False,
) -> dict:
    """Dosyayı (görüntü veya PDF) işler. Döner: {filename, pages: [{page, content, layout?}], full_markdown, layout_pages?}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    pages = []
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        for i, png_bytes in iter_pdf_pages_as_images(path, dpi=dpi):
            content = ocr(png_bytes, prompt=prompt)
            pages.append({"page": i + 1, "content": content})
            if output_dir:
                (output_dir / f"{path.stem}_p{i + 1}.md").write_text(content, encoding="utf-8")
    else:
        content = ocr(path, prompt=prompt)
        pages.append({"page": 1, "content": content})
        if output_dir:
            (output_dir / f"{path.stem}.md").write_text(content, encoding="utf-8")

    full_markdown = "\n\n---\n\n".join(p["content"] for p in pages)
    result = {"filename": path.name, "pages": pages, "full_markdown": full_markdown}

    # Layout koruyan JSON (GLM-OCR tarzı: index, label, content, bbox_2d)
    layout_data = build_layout_json(pages)
    result["layout_pages"] = layout_data["layout_pages"]

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{path.stem}_full.md").write_text(full_markdown, encoding="utf-8")
        (output_dir / f"{path.stem}_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if layout_json:
            layout_export = {
                "filename": path.name,
                "layout_pages": result["layout_pages"],
            }
            (output_dir / f"{path.stem}_layout.json").write_text(
                json.dumps(layout_export, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # JavaScript'e doğrudan kopyalanabilir / import edilebilir format
            js_content = (
                "/** GLM-OCR layout (layout koruyan) - https://github.com/zai-org/GLM-OCR */\n"
                "export const glmOcrLayout = "
                + json.dumps(layout_export, ensure_ascii=False, indent=2)
                + ";\n"
            )
            (output_dir / f"{path.stem}_layout.js").write_text(js_content, encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description="GLM-OCR (Ollama) test")
    p.add_argument("path", type=Path, help="PDF veya görüntü")
    p.add_argument("-o", "--output", type=Path, help="Çıktı klasörü")
    p.add_argument("--prompt", default=PROMPT, help="Prompt")
    p.add_argument("--dpi", type=int, default=150, help="PDF DPI")
    p.add_argument("--json-only", action="store_true", help="Sadece JSON, dosya yazma")
    p.add_argument("--layout-json", action="store_true", help="Layout koruyan _layout.json ve _layout.js yaz")
    args = p.parse_args()

    if not args.path.exists():
        print(f"Dosya yok: {args.path}", file=sys.stderr)
        sys.exit(1)

    out = None if args.json_only else (args.output or Path("."))
    try:
        result = run(
            args.path,
            output_dir=out,
            prompt=args.prompt,
            dpi=args.dpi,
            layout_json=args.layout_json,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
