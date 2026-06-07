## [1.3.0] - 2025-01-01
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
