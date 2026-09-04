# Graph Report - wendococr  (2026-08-30)

## Corpus Check
- Corpus is ~33,286 words - fits in a single context window. You may not need a graph.

## Summary
- 380 nodes · 645 edges · 18 communities (14 shown, 4 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 21 edges (avg confidence: 0.86)
- Token cost: 60,000 input · 9,946 output

## Community Hubs (Navigation)
- API Layer & Endpoints
- Hybrid Image-Text Engine
- RapidOCR & Auto-Rotate
- Worker Pool & Queue
- Findeks Report Extractor
- ICR Handwriting (Tesseract)
- Decision Engine (Brain)
- Image Preprocessing
- Image-Table OCR Engine
- JSON-to-Text Visualizers
- Output Schema (bbox)
- Deployment & Docker Stack
- Visual Object Detection
- Build Script
- Entrypoint Script
- Run Script
- Stop Script

## God Nodes (most connected - your core abstractions)
1. `_process_upload()` - 20 edges
2. `process_document()` - 16 edges
3. `process_findeks()` - 14 edges
4. `extract()` - 14 edges
5. `postprocess_turkish()` - 14 edges
6. `content_from_text_blocks_with_bbox()` - 12 edges
7. `_process_page()` - 11 edges
8. `_process_page_imagetable()` - 11 edges
9. `page_result_from_engine()` - 11 edges
10. `preprocess_image()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Docker Compose Redis Stack (password-optional)` --semantically_similar_to--> `Docker Compose Stack (Redis + API + workers)`  [INFERRED] [semantically similar]
  docker-compose.redis.yml → docker-compose.yml
- `OCR Docker Compose Stack (Nexus registry, 3 named workers)` --semantically_similar_to--> `Docker Compose Stack (Redis + API + workers)`  [INFERRED] [semantically similar]
  ocr.docker.compose.yml → docker-compose.yml
- `run_in_executor Non-blocking Pattern` --semantically_similar_to--> `Redis Distributed Work Queue`  [INFERRED] [semantically similar]
  DEV_NOTES.md → docker-compose.yml
- `PageResult Engine Interface (page_number, content, tables)` --conceptually_related_to--> `Standardized JSON Output Schema (pages/content/text_blocks/tables/bbox)`  [INFERRED]
  DEV_NOTES.md → Project.md
- `Decision Engine (Auto-Router Brain)` --conceptually_related_to--> `Auto Mode Decision Flow (MIME → text layer → table density)`  [EXTRACTED]
  Project.md → DEV_NOTES.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **OCR/Extraction Engine Family (Strategy Pattern implementations)** — project_engine_pdftext, project_engine_pdftexttable, project_engine_pdfimagev5, project_engine_pdfimagets, readme_engine_pdftxtimage, readme_engine_pdfimagetable, readme_engine_findeksexport [EXTRACTED 0.85]
- **Distributed Redis Worker Deployment Flow** — docker_compose_stack, docker_compose_redis_queue, docker_compose_wendococr_worker, docker_compose_kvkk_tmpfs_volume [EXTRACTED 0.85]
- **Client-side JSON→Text Visualization Tools** — app_static_jsontotext_grid_mapper, app_static_rawjsontotext_viewer, project_standardized_json_output [INFERRED 0.75]

## Communities (18 total, 4 thin omitted)

### Community 0 - "API Layer & Endpoints"
Cohesion: 0.07
Nodes (46): _check_rapidocr(), _check_tesseract(), _check_upload_dir(), health(), _process_upload(), get, FastAPI endpoint'leri: OCR, ICR, Findeks Export, Sistem., Servisin ayakta olduğunu ve tüm motor bağımlılıklarını doğrular. (+38 more)

### Community 1 - "Hybrid Image-Text Engine"
Cohesion: 0.07
Nodes (46): _candidate_regions(), _dedup(), _gap_bands(), _has_ink(), _image_rects(), _in_regions(), _max_image_ratio(), _native_lines() (+38 more)

### Community 2 - "RapidOCR & Auto-Rotate"
Cohesion: 0.08
Nodes (36): Uygulama ayarları (sabit değerler, .env kullanılmaz)., _clean_text(), _enhance_and_ocr(), _enhance_for_turkish_rapid(), _four_way_vote(), _get_rapid_engine(), _oriented_ocr(), ndarray (+28 more)

### Community 3 - "Worker Pool & Queue"
Cohesion: 0.08
Nodes (24): get_pool(), LocalWorkerPool, Redis-backed pool — main (API) tarafı. İşi Redis'e atar, sonucu bekler. OCR…, Process-based worker pool (tek makine, n8n'e gerek yok)., RedisWorkerPool, custom_swagger_ui(), global_exception_handler(), jsontotext_page() (+16 more)

### Community 4 - "Findeks Report Extractor"
Cohesion: 0.10
Nodes (30): clean_page_text(), extract_banka_limit_risk(), extract_kredi_turu_bazinda(), extract_leasing_faktoring(), extract_ozet_tablo(), extract_rapor_ozeti(), extract_takip_leasing_faktoring(), extract_takip_ticari() (+22 more)

### Community 5 - "ICR Handwriting (Tesseract)"
Cohesion: 0.10
Nodes (29): _deskew_handwriting(), extract(), _preprocess_handwriting_hard(), _preprocess_handwriting_soft(), Any, ndarray, Path, ICR (Intelligent Character Recognition) motoru: Tesseract ile Türkçe el yazısı… (+21 more)

### Community 6 - "Decision Engine (Brain)"
Cohesion: 0.13
Nodes (22): _analyze_pdf_page(), _check_tables_pdfplumber(), process_document(), Any, Path, Akıllı Karar Mekanizması (Brain). Gelen belgeye göre sayfa bazlı engine seçer.…, PDF veya resim; OCR motoru lazy yüklenir., Tek bir PDF sayfası için engine seçer (zaten açık doc üzerinde). (+14 more)

### Community 7 - "Image Preprocessing"
Cohesion: 0.13
Nodes (20): _adaptive_threshold(), _deskew(), load_image(), preprocess_image(), NDArray, Path, Görüntü ön işleme: grayscale, thresholding, deskew, Türkçe diacritik koruma…, Dosyadan görüntü yükler. (+12 more)

### Community 8 - "Image-Table OCR Engine"
Cohesion: 0.15
Nodes (20): _bbox_area(), _bbox_overlap_area(), _bbox_to_list(), extract(), _find_cell_for_image(), _is_mostly_inside(), _ocr_embedded_image_tesseract(), _process_page_imagetable() (+12 more)

### Community 9 - "JSON-to-Text Visualizers"
Cohesion: 0.13
Nodes (20): RapidOCR Character Dictionary, autoEstimateParams (median-based grid parameter estimator), detectFormat (OCR vs Findeks format detector), JSON→Text Grid Mapping Tool, pageToGridText (coordinate-aligned text renderer), parseBbox (bbox normalizer, jsontotext), parseBbox (bbox normalizer, rawjsontotext), positionTextFromPage (y/x sorted text extractor) (+12 more)

### Community 10 - "Output Schema (bbox)"
Cohesion: 0.19
Nodes (17): BBox, page_result_from_engine(), PageResult, PageTable, Any, API istek/yanıt şemaları. Tüm metin ve tablolar koordinat (bbox) ile döner., Sol üst (x0,y0) ve sağ alt (x1,y1). Sayfa koordinatları., Koordinatlı metin parçası (satır veya blok). (+9 more)

### Community 11 - "Deployment & Docker Stack"
Cohesion: 0.16
Nodes (15): renderFindeks (Findeks report renderer), run_in_executor Non-blocking Pattern, KVKK RAM-backed tmpfs Shared Volume, OCR_QUEUE_TIMEOUT 300s (client-aligned), Redis Distributed Work Queue, Docker Compose Redis Stack (password-optional), Docker Compose Stack (Redis + API + workers), wendococr-worker (OCR queue consumer) (+7 more)

### Community 12 - "Visual Object Detection"
Cohesion: 0.29
Nodes (9): _classify_object(), detect_image_objects(), detect_pdf_objects(), Any, Path, Sayfa icindeki gorsel objeleri tespit et — logo/qr/barkod/damga/imza vb. PDF…, Raster image (PNG/JPG/scan PDF render) icinde gorsel obje contour detection.…, Bbox boyutuna gore kabaca tip ve gerekce uret. (+1 more)

## Knowledge Gaps
- **15 isolated node(s):** `build.sh script`, `entrypoint.sh script`, `run.sh script`, `stop.sh script`, `Hybrid OCR & Document Parser (CPU Optimized)` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `process_findeks()` connect `Findeks Report Extractor` to `API Layer & Endpoints`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `process_document()` connect `Decision Engine (Brain)` to `API Layer & Endpoints`, `Image-Table OCR Engine`, `Hybrid Image-Text Engine`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `postprocess_turkish()` connect `ICR Handwriting (Tesseract)` to `Image-Table OCR Engine`, `RapidOCR & Auto-Rotate`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `_process_upload()` (e.g. with `process_document()` and `QueueFullError`) actually correct?**
  _`_process_upload()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `build.sh script`, `entrypoint.sh script`, `run.sh script` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `API Layer & Endpoints` be split into smaller, more focused modules?**
  _Cohesion score 0.06748911465892599 - nodes in this community are weakly interconnected._
- **Should `Hybrid Image-Text Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.06509803921568627 - nodes in this community are weakly interconnected._