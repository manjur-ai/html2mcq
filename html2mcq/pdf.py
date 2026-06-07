"""
PDFExtractor: Downloads and extracts text from PDF links found in HTML pages.

Backends (in priority order):
1. PyMuPDF  — default, fast, no setup, handles clean digital PDFs
2. Docling local — deep-learning layout + OCR, handles scanned/complex PDFs
3. Docling Serve — self-hosted REST API (e.g. on your Contabo VPS)

Auto-fallback logic:
  PyMuPDF → if extracted text is empty/too short → Docling local/serve
"""
from __future__ import annotations

import io
import re
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from .models import ContentBlock


# ── Helpers ───────────────────────────────────────────────────────────────────

_MIN_MEANINGFUL_CHARS = 100   # below this PyMuPDF result is considered "failed"


def _is_pdf_url(url: str) -> bool:
    return bool(re.search(r"\.pdf($|\?|#)", url, re.IGNORECASE))


def _fetch_bytes(url: str, timeout: int = 30, user_agent: str = "html2mcq/1.1") -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/pdf,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 150) -> List[str]:
    """Split text into overlapping chunks at sentence boundaries."""
    chunks, start = [], 0
    text = text.strip()
    n = len(text)
    while start < n:
        end = start + chunk_size
        if end >= n:
            chunks.append(text[start:].strip())
            break
        boundary = max(
            text.rfind(". ", start, end),
            text.rfind("! ", start, end),
            text.rfind("? ", start, end),
            text.rfind("\n", start, end),
        )
        if boundary > start + chunk_size // 2:
            end = boundary + 1
        else:
            wb = text.rfind(" ", start, end)
            if wb > start:
                end = wb
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return [c for c in chunks if c]


# ── Backend: PyMuPDF ──────────────────────────────────────────────────────────

class _PyMuPDFBackend:
    """
    Fast extraction using the MuPDF C library.
    Handles clean digital PDFs perfectly.
    Falls back gracefully on scanned PDFs (returns empty string).
    """

    name = "pymupdf"

    def __init__(self):
        try:
            import fitz  # noqa: F401
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for PDF extraction.\n"
                "Install with:  pip install html2mcq[pdf]  or  pip install pymupdf"
            )

    def extract(self, pdf_bytes: bytes, source_url: str = "") -> Tuple[str, List[Dict]]:
        """
        Returns (full_text, page_data_list).
        page_data_list: [{"page": N, "text": "...", "tables": [...]}]
        """
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        full_parts = []

        for page_num, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            # Also try to extract tables via fitz dict mode
            tables = []
            try:
                page_dict = page.get_text("dict")
                tables = self._extract_tables(page_dict)
            except Exception:
                pass

            pages.append({
                "page": page_num,
                "text": text,
                "tables": tables,
            })
            if text:
                full_parts.append(f"[Page {page_num}]\n{text}")

        doc.close()
        return "\n\n".join(full_parts), pages

    @staticmethod
    def _extract_tables(page_dict: dict) -> List[str]:
        """Heuristic table extraction from PyMuPDF dict output."""
        # Collect text blocks grouped by vertical position
        lines: Dict[int, List[str]] = {}
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                y = round(line["bbox"][1] / 5) * 5  # snap to 5px grid
                spans = [s["text"].strip() for s in line.get("spans", []) if s["text"].strip()]
                if spans:
                    lines.setdefault(y, []).extend(spans)
        # Rows with 3+ columns look like tables
        table_rows = [
            " | ".join(cells)
            for cells in lines.values()
            if len(cells) >= 3
        ]
        return table_rows


# ── Backend: Docling Local ────────────────────────────────────────────────────

class _DoclingLocalBackend:
    """
    Deep-learning document understanding via the local Docling library.
    Downloads ~2GB ONNX models on first use.
    Best for: scanned PDFs, complex layouts, academic papers.
    """

    name = "docling_local"

    def __init__(self, ocr: bool = True):
        self.ocr = ocr
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
        except ImportError:
            raise ImportError(
                "Docling is required for the docling_local backend.\n"
                "Install with:  pip install html2mcq[docling]  or  pip install docling"
            )

    def extract(self, pdf_bytes: bytes, source_url: str = "") -> Tuple[str, List[Dict]]:
        """
        Write PDF to a temp file, run Docling converter, return structured output.
        """
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_opts = PdfPipelineOptions()
        pipeline_opts.do_ocr = self.ocr
        pipeline_opts.do_table_structure = True

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
            }
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            result = converter.convert(tmp_path)
            doc = result.document

            # Export to markdown — preserves headings, tables, lists
            full_text = doc.export_to_markdown()

            # Build per-page data
            pages = []
            for i, page in enumerate(doc.pages, 1):
                page_text = "\n".join(
                    item.text for item in doc.texts
                    if hasattr(item, "prov") and any(
                        p.page_no == i for p in (item.prov or [])
                    )
                )
                pages.append({"page": i, "text": page_text, "tables": []})

            return full_text, pages
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ── Backend: Docling Serve (REST API) ─────────────────────────────────────────

class _DoclingServeBackend:
    """
    Calls a self-hosted Docling Serve REST API.

    Run on your VPS:
        docker run -p 5001:5001 quay.io/docling/docling-serve

    Then pass:
        PDFExtractor(backend="docling_serve", docling_api_url="http://your-vps:5001")

    This keeps the heavy 2GB models on your server — no local install needed
    on client machines.
    """

    name = "docling_serve"

    def __init__(self, api_url: str, timeout: int = 120):
        if not api_url:
            raise ValueError(
                "docling_api_url is required for the docling_serve backend.\n"
                "Example: PDFExtractor(backend='docling_serve', docling_api_url='http://localhost:5001')"
            )
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def extract(self, pdf_bytes: bytes, source_url: str = "") -> Tuple[str, List[Dict]]:
        """
        POST the PDF bytes to Docling Serve and parse the response.
        Docling Serve v2 API: POST /v1alpha/convert/file
        """
        import json
        import urllib.request
        import urllib.parse

        # Build multipart/form-data manually (no requests dependency)
        boundary = "----html2mcqboundary"
        body_parts = []

        # options part
        options = json.dumps({
            "to_formats": ["md"],
            "do_ocr": True,
            "do_table_structure": True,
        }).encode()
        body_parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="options"\r\n'
            f'Content-Type: application/json\r\n\r\n'.encode() + options + b'\r\n'
        )

        # file part
        filename = "document.pdf"
        body_parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            f'Content-Type: application/pdf\r\n\r\n'.encode() + pdf_bytes + b'\r\n'
        )
        body_parts.append(f'--{boundary}--\r\n'.encode())
        body = b''.join(body_parts)

        endpoint = f"{self.api_url}/v1alpha/convert/file"
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            raise RuntimeError(
                f"Docling Serve returned HTTP {e.code}: {body_text[:300]}"
            )
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not connect to Docling Serve at {self.api_url}: {e.reason}\n"
                "Make sure the server is running: docker run -p 5001:5001 quay.io/docling/docling-serve"
            )

        # Extract markdown from response
        # Docling Serve v2 response structure:
        # {"document": {"md_content": "..."}} or {"output": "..."}
        full_text = (
            result.get("document", {}).get("md_content")
            or result.get("output")
            or result.get("markdown")
            or ""
        )

        if not full_text:
            # Try iterating pages if present
            pages_raw = result.get("pages", [])
            full_text = "\n\n".join(
                f"[Page {p.get('page_no', i+1)}]\n{p.get('text','')}"
                for i, p in enumerate(pages_raw)
            )

        pages = [
            {"page": i + 1, "text": p.get("text", ""), "tables": []}
            for i, p in enumerate(result.get("pages", []))
        ]

        return full_text, pages


# ── PDFExtractor (orchestrator) ───────────────────────────────────────────────

class PDFExtractor:
    """
    Downloads and extracts text from PDF URLs, returning ContentBlocks.

    Backend selection
    -----------------
    "pymupdf"        — fast C library, best for clean digital PDFs (default)
    "docling_local"  — local Docling models, best for scanned/complex PDFs
    "docling_serve"  — Docling Serve REST API (self-hosted on your VPS)
    "auto"           — tries PyMuPDF first; falls back to Docling on failure

    Auto-fallback
    -------------
    When backend="pymupdf" (or "auto"), if the extracted text is empty or
    shorter than MIN_MEANINGFUL_CHARS characters, the extractor automatically
    retries with the Docling backend (local or serve, whichever is available).

    Usage
    -----
    # Default
    extractor = PDFExtractor()
    blocks = extractor.from_url("https://example.com/tutorial.pdf")

    # With Docling Serve on your VPS
    extractor = PDFExtractor(
        backend="docling_serve",
        docling_api_url="http://your-vps:5001"
    )

    # Enrich existing ContentBlocks (auto-downloads any PDF links found)
    enriched = extractor.enrich_blocks(existing_blocks)
    """

    def __init__(
        self,
        backend: str = "pymupdf",
        docling_api_url: str = "",
        docling_ocr: bool = True,
        chunk_size: int = 1500,
        chunk_overlap: int = 150,
        min_meaningful_chars: int = _MIN_MEANINGFUL_CHARS,
        timeout: int = 30,
        user_agent: str = "html2mcq/1.1",
        fallback_to_docling: bool = True,
    ):
        """
        Parameters
        ----------
        backend : str
            "pymupdf" | "docling_local" | "docling_serve" | "auto"
        docling_api_url : str
            Required when backend="docling_serve".
            E.g. "http://your-contabo-vps:5001"
        docling_ocr : bool
            Enable OCR in Docling local/serve (default True).
        chunk_size : int
            Characters per ContentBlock chunk.
        chunk_overlap : int
            Overlap between consecutive chunks.
        min_meaningful_chars : int
            If PyMuPDF extracts fewer chars than this, trigger fallback.
        timeout : int
            HTTP timeout for downloading PDFs and calling Docling Serve.
        fallback_to_docling : bool
            If True (default), automatically retry with Docling when PyMuPDF
            returns insufficient text.
        """
        self.backend = backend.lower()
        self.docling_api_url = docling_api_url
        self.docling_ocr = docling_ocr
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_meaningful_chars = min_meaningful_chars
        self.timeout = timeout
        self.user_agent = user_agent
        self.fallback_to_docling = fallback_to_docling

        # Initialise primary backend eagerly (validates deps)
        self._primary = self._make_backend(self.backend)

        # Docling fallback — lazily initialised only when needed
        self._docling_fallback: Optional[Any] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def from_url(self, url: str) -> List[ContentBlock]:
        """Download a PDF from *url* and return ContentBlocks."""
        print(f"  [html2mcq] Downloading PDF: {url}")
        pdf_bytes = _fetch_bytes(url, timeout=self.timeout, user_agent=self.user_agent)
        return self.from_bytes(pdf_bytes, source_url=url)

    def from_bytes(self, pdf_bytes: bytes, source_url: str = "") -> List[ContentBlock]:
        """Extract text from raw PDF bytes and return ContentBlocks."""
        full_text, pages, backend_used = self._extract_with_fallback(pdf_bytes, source_url)

        if not full_text.strip():
            print(f"  [html2mcq] ⚠ No text extracted from PDF: {source_url}")
            return []

        chunks = _chunk_text(full_text, self.chunk_size, self.chunk_overlap)
        blocks = []
        for i, chunk in enumerate(chunks):
            blocks.append(ContentBlock(
                type="pdf_text",
                content=chunk,
                metadata={
                    "source_url": source_url,
                    "backend": backend_used,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "total_pages": len(pages),
                    "char_count": len(chunk),
                },
            ))

        print(
            f"  [html2mcq] ✓ PDF extracted via {backend_used}: "
            f"{len(pages)} pages → {len(blocks)} chunks ({len(full_text)} chars)"
        )
        return blocks

    def from_path(self, path: str) -> List[ContentBlock]:
        """Extract text from a local PDF file path."""
        pdf_bytes = Path(path).read_bytes()
        return self.from_bytes(pdf_bytes, source_url=f"file://{path}")

    def enrich_blocks(
        self, blocks: List[ContentBlock], replace: bool = True
    ) -> List[ContentBlock]:
        """
        Walk a list of ContentBlocks, find all pdf blocks, download and
        extract their text, and return an enriched block list.

        Parameters
        ----------
        blocks : list[ContentBlock]
            Existing blocks from ContentExtractor.
        replace : bool
            If True (default), replace the original pdf block with pdf_text blocks.
            If False, keep the original pdf block and append pdf_text blocks after it.
        """
        enriched: List[ContentBlock] = []
        for block in blocks:
            if block.type == "pdf" and _is_pdf_url(block.content):
                try:
                    pdf_blocks = self.from_url(block.content)
                    if replace:
                        enriched.extend(pdf_blocks)
                    else:
                        enriched.append(block)
                        enriched.extend(pdf_blocks)
                except Exception as e:
                    # Keep original block on failure
                    enriched.append(block)
                    print(f"  [html2mcq] ⚠ Could not extract PDF {block.content}: {e}")
            else:
                enriched.append(block)
        return enriched

    # ── Private helpers ───────────────────────────────────────────────────────

    def _make_backend(self, name: str):
        if name in ("pymupdf", "auto"):
            return _PyMuPDFBackend()
        if name == "docling_local":
            return _DoclingLocalBackend(ocr=self.docling_ocr)
        if name == "docling_serve":
            return _DoclingServeBackend(
                api_url=self.docling_api_url,
                timeout=self.timeout,
            )
        raise ValueError(
            f"Unknown PDF backend '{name}'. "
            "Choose: pymupdf | docling_local | docling_serve | auto"
        )

    def _get_docling_fallback(self):
        """Lazily initialise Docling fallback backend."""
        if self._docling_fallback is None:
            if self.docling_api_url:
                self._docling_fallback = _DoclingServeBackend(
                    api_url=self.docling_api_url,
                    timeout=self.timeout,
                )
                print("  [html2mcq] Falling back to Docling Serve...")
            else:
                self._docling_fallback = _DoclingLocalBackend(ocr=self.docling_ocr)
                print("  [html2mcq] Falling back to Docling local...")
        return self._docling_fallback

    def _extract_with_fallback(
        self, pdf_bytes: bytes, source_url: str
    ) -> Tuple[str, List[Dict], str]:
        """
        Try primary backend. If result is insufficient AND fallback is enabled,
        retry with Docling.

        Returns (full_text, pages, backend_name_used)
        """
        # Try primary
        try:
            full_text, pages = self._primary.extract(pdf_bytes, source_url)
        except Exception as e:
            print(f"  [html2mcq] ⚠ {self._primary.name} failed: {e}")
            full_text, pages = "", []

        # Check if result is meaningful
        meaningful = len(full_text.strip()) >= self.min_meaningful_chars

        if meaningful:
            return full_text, pages, self._primary.name

        # Trigger fallback if enabled
        if self.fallback_to_docling and self.backend in ("pymupdf", "auto"):
            try:
                fallback = self._get_docling_fallback()
                full_text, pages = fallback.extract(pdf_bytes, source_url)
                return full_text, pages, fallback.name
            except ImportError as e:
                print(f"  [html2mcq] ⚠ Docling fallback unavailable: {e}")
            except Exception as e:
                print(f"  [html2mcq] ⚠ Docling fallback failed: {e}")

        # Return whatever we got (may be empty)
        return full_text, pages, self._primary.name
