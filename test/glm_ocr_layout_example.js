/**
 * GLM-OCR layout çıktısını JavaScript'te kullanma örneği.
 * Kaynak: https://github.com/zai-org/GLM-OCR
 *
 * Python'dan üretim:
 *   python test/glm_ocr_ollama_test.py belge.png -o ./cikti/ --layout-json
 *   -> cikti/belge_layout.js (export const glmOcrLayout = {...})
 *
 * Kullanım:
 *   import { glmOcrLayout } from './cikti/belge_layout.js';
 *   veya fetch('/path/to/belge_layout.json') ile JSON yükle.
 */

// Örnek yapı (gerçek veri _layout.json / _layout.js'den gelir)
const exampleLayout = {
  filename: "belge.pdf",
  layout_pages: [
    [
      { index: 0, label: "title", content: "Belge Başlığı", bbox_2d: null },
      { index: 1, label: "text", content: "Paragraf metni...", bbox_2d: null },
      { index: 2, label: "table", content: "<table>...</table>", bbox_2d: null },
    ],
  ],
};

/**
 * Layout bloklarını sırayla işler; label'a göre HTML üretir (layout korunur).
 * @param {Array<Array<{index: number, label: string, content: string, bbox_2d: unknown}>>} layoutPages
 * @returns {string} HTML
 */
function layoutToHtml(layoutPages) {
  const parts = [];
  for (const pageBlocks of layoutPages) {
    const pageDiv = document.createElement("div");
    pageDiv.className = "glm-ocr-page";
    for (const block of pageBlocks) {
      const el = document.createElement(
        block.label === "table" ? "div" : block.label === "title" ? "h2" : "p"
      );
      el.dataset.index = String(block.index);
      el.dataset.label = block.label;
      if (block.label === "table") {
        el.innerHTML = block.content;
        el.classList.add("glm-ocr-table-wrap");
      } else {
        el.textContent = block.content;
      }
      pageDiv.appendChild(el);
    }
    parts.push(pageDiv.outerHTML);
  }
  return parts.join("\n");
}

/**
 * Layout'tan düz metin (sıra korunur).
 */
function layoutToPlainText(layoutPages) {
  return layoutPages
    .map((pageBlocks) =>
      pageBlocks
        .map((b) => (b.label === "table" ? stripHtml(b.content) : b.content))
        .join("\n\n")
    )
    .join("\n\n---\n\n");
}

function stripHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent || div.innerText || "";
}

// ESM export
export { exampleLayout, layoutToHtml, layoutToPlainText };
