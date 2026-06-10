## [3.3.0] - 2026-06-10
### Added
- **Priority list fallback in `_vision_mcq`/`_vision_mcq_pdf`**: Vision methods now iterate through the full `ocr_models` priority list when the primary model fails (previously returned `[]` immediately on non-retryable errors like 402).

### Fixed
- **`_parse_response` handles trailing text**: Improved JSON parsing to strip trailing characters after valid JSON arrays (fixes "Extra data" `json.JSONDecodeError`). Also validates that the response is a JSON array, rejecting non-array responses with a clear error.
- **`_DEFAULT_VISION` provider prefix**: Changed from `google/gemini-2.5-flash-lite` to `(gemini)/gemini-2.5-flash-lite` to route directly to Gemini, avoiding unnecessary OpenRouter 402 failures.
- **Updated `_vision_free_model`**: Changed to `(openrouter)/google/gemma-4-26b-a4b-it:free` for a newer, faster free-tier model.
- **Windows Unicode compatibility**: Replaced all `\u26a0` (⚠) characters with `!` in print statements across `generator.py`, `image_ocr.py`, and `pdf.py` to fix `UnicodeEncodeError` on CP1252 terminals.

## [3.2.0] - 2026-06-10
### Added
- **Configurable `max_tokens`**: Now fully propagated to all vision and OCR tasks.
- **`ocr_model_list` Support**: Consistent API for defining priority fallback for OCR tasks.

### Fixed
- **Improved Fallback**: Error 402 (Insufficient Credits) now correctly triggers fallback to the next model in `priority_list`.
- **Better Error Reporting**: Standardized, compact, and explicit error messages including operator and model names.
- **Fixed Hardcoded Limits**: Replaced hardcoded 8192 token limit in vision paths with configurable `max_tokens`.

## [3.1.1] - 2026-06-10
### Fixed
- Fixed bug where `priority_list` was incorrectly treated as a literal model name in vision-based generation paths.

## [3.1.0] - 2026-06-10
### Added
- **Operator Auto-Detection**: Use `--operator auto` to scan environment variables and dynamically route requests across multiple AI providers (OpenAI, Gemini, Groq, etc.) based on available keys.
- **Independent Provider Routing**: `ocr_model` and `mcq_model` can now use separate AI providers in the same run via the `(provider)/model_id` syntax.
- **ManualAI Provider**: Added support for generic OpenAI-compatible APIs via the `manualai` provider and `MANUALAI_BASE_URL`.

## [3.0.0] - 2026-06-10
### Added
- **Native Async Support**: New `AsyncMCQGenerator` class for non-blocking usage.
- **LMS Exporting**: Direct export to Aiken and Moodle XML formats via `--format`.
- **Hybrid Vision Mode**: `onestep` method now combines HTML text and raw images in a single multi-modal prompt.
- **Native PDF Vision**: Support for sending raw PDF bytes directly to Gemini/OpenRouter in `onestep` mode.
- **Resilient Retries**: Automatic exponential backoff for rate limits (429) and server overloads (503).
- **New Providers**: Native support for `gemini`, `deepseek`, `groq`, and `manualai`.
- **Operator-Aware Selection**: Target specific models for specific providers using `(provider)/model_id` syntax.

### Changed
- **Breaking**: `method` parameter is now **mandatory** in both CLI and library.
- **Breaking**: `images2mcq` method renamed to `onestep`.
- **Breaking**: `auto` value for model parameters renamed to `priority_list`.
- **Breaking**: `pytesseract` is no longer a valid model name; use `method="tesseract"` instead.
- Refined `auto` method resolution logic to intelligently choose strategy based on provided models.

## [2.0.0] - 2026-06-08
### Added
- `from_image_urls()` / `from_image_paths()` — generate MCQs directly from images
- `from_pdf_urls()` / `from_pdf_paths()` — renamed from singular, accept `str|list[str]`
- `method="twostep"` (default) — OCR images → text → MCQ pipeline
- `method="onestep"` — vision model direct (bypasses OCR)
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
