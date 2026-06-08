## [2.0.0] - 2026-06-08
### Added
- `from_image_urls()` / `from_image_paths()` — generate MCQs directly from images
- `from_pdf_urls()` / `from_pdf_paths()` — renamed from singular, accept `str|list[str]`
- `method="twostep"` (default) — OCR images → text → MCQ pipeline
- `method="images2mcq"` — vision model direct (bypasses OCR)
- `mcq_model` — single parameter for all MCQ generation (text + vision), replaces `model`
- `mcq_model="auto"` — tries `mcq_model_list` in order until one succeeds
- `mcq_model_list` — priority-ordered model list, runtime-reloadable via env var
- `ocr_model` — OCR backend: `"pytesseract"`, `"auto"`, or any OpenRouter model ID
- `ocr_model="auto"` — tries priority list with fallback-to-auto dedup
- `ocr_models` — priority list for auto OCR, reloadable via env var
- `prompt_log_path` — dump prompts to file or terminal (`"stdout"`/`"-"`)
- `api_key_override` — override API key per instance or per call
- `save_ocr_path` — save OCR text to file when method=twostep
- Ollama provider support (`provider="ollama"`, default model `qwen2.5:7b`)
- Parallel OCR via `ThreadPoolExecutor` in `enrich_blocks`
- `_OverrideContext` context manager for clean per-call override restore
- Per-model `max_tokens` in auto MCQ mode

### Changed
- Default provider: `"anthropic"` → `"openrouter"`
- `model` parameter renamed to `mcq_model`
- `vision_api_key` removed — primary `api_key` is used for vision calls
- `from_pdf_url` / `from_pdf_path` → `from_pdf_urls` / `from_pdf_paths` (old names kept as aliases)
- OCR default priority: `gemini-2.5-flash-lite` first (fast, cheap, $0.10/M)
- Batch mode in auto: sends all remaining questions in one call (no while-loop)
- All backends return `.content or ""` to prevent `None.strip()` crashes
- Default vision model: `google/gemini-2.5-flash-lite`
- Gemini 2.5 Flash Lite added to OCR priority list (first position)

### Removed
- `vision_api_key` parameter (redundant — primary `api_key` suffices)
- `twostep` per-call parameter (replaced by `method="twostep"` on constructor)
- `video.py` module, `from_video_url()`, `youtube-transcript-api` dependency
- All video/YouTube references throughout codebase

## [1.3.1] - 2026-06-07

[1.3.0] - 2025-01-01
### Changed
- Simplified installation: `pip install html2mcq` now includes all features
  (beautifulsoup4, lxml, anthropic, openai, openai, youtube-transcript-api, pymupdf)
- Docling remains optional: `pip install html2mcq docling` for scanned PDF support
- Removed optional dependency extras ([anthropic], [openai], [video], [pdf], [all])

# Changelog

## [1.2.0] - 2025-01-01
### Added
- `PDFExtractor` with three backends: PyMuPDF (default), Docling Local, Docling Serve
- Auto-fallback from PyMuPDF → Docling when extracted text is insufficient
- `MCQGenerator.from_pdf_url()` — generate MCQs directly from a PDF URL
- `MCQGenerator.from_pdf_path()` — generate MCQs from a local PDF file
- `enrich_pdfs=True` parameter on `from_url()` and `from_html()`
- PDF content blocks (`pdf_text`) in prompt builder

## [1.1.0] - 2025-01-01
### Added
- `VideoTranscriptExtractor` — fetches YouTube transcripts via youtube-transcript-api
- `MCQGenerator.from_video_url()` — generate MCQs directly from a YouTube URL
- Auto-routing: `from_url()` detects YouTube links and fetches transcripts
- `enrich_videos=True` parameter auto-enriches video links in HTML pages
- Transcript chunking with sentence-boundary splitting and overlap
- `preserve_timestamps` and `max_duration` options

## [1.0.0] - 2025-01-01
### Added
- Initial release
- `ContentExtractor` — extracts text, images, video links, PDF links, code, tables from HTML
- `MCQGenerator` — supports Anthropic, OpenAI, OpenRouter backends
- `MCQSet` output with `total_exam_time`, multi-answer support, difficulty levels
- CLI: `html2mcq <url> --n 10 --output quiz.json`
