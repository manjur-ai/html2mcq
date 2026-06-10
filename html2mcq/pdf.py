"""
PDFExtractor: Downloads and extracts text from PDF links found in HTML pages.

Backend:
1. PyMuPDF — default, fast, no setup, handles clean digital PDFs

Auto-detection routing:
  When backend="pymupdf" (or "priority_list"), the extractor detects the PDF type:
  - "text" → extracts via PyMuPDF
  - "scanned" → renders pages as PNG images → vision API (GPT-4o mini / Gemma / pytesseract)
  - "mixed" → combines text extraction + scanned page OCR
"""
from __future__ import annotations

import io
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Tuple, Dict

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


# ── PDF→Image rendering (for scanned PDFs) ────────────────────────────────────

def _parse_page_range(range_str: Optional[str]) -> Optional[List[int]]:
    """
    Parse a page range string into zero-indexed page numbers.

    Examples
    --------
    "1-5"      → [0, 1, 2, 3, 4]
    "1,3,5"    → [0, 2, 4]
    "1-3,7-9"  → [0, 1, 2, 6, 7, 8]
    "" / None  → None (all pages)
    """
    if not range_str or not range_str.strip():
        return None
    pages: List[int] = []
    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_str, end_str = part.split("-", 1)
                start, end = int(start_str.strip()), int(end_str.strip())
                if start < 1 or end < start:
                    raise ValueError
                pages.extend(range(start - 1, end))
            except (ValueError, TypeError):
                raise ValueError(
                    f"Invalid page range: '{part}'. Use format like '1-10' or '1,3,5'."
                )
        else:
            try:
                p = int(part)
                if p < 1:
                    raise ValueError
                pages.append(p - 1)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Invalid page number: '{part}'. Pages are 1-indexed."
                )
    return sorted(set(pages))


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = len(doc)
    doc.close()
    return n


def _render_specific_pages(pdf_bytes: bytes, page_nums: List[int], max_pages: int = 0) -> List[bytes]:
    """
    Render specific page numbers as PNG images.

    Parameters
    ----------
    pdf_bytes : bytes
        Raw PDF bytes.
    page_nums : list[int]
        Zero-indexed page numbers to render.
    max_pages : int
        Maximum number of pages to render (0 = all).

    Returns
    -------
    list[bytes]
        PNG bytes for each requested page.
    """
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for i, page_num in enumerate(page_nums):
        if max_pages and i >= max_pages:
            break
        if page_num < len(doc):
            pix = doc[page_num].get_pixmap(dpi=200)
            images.append(pix.tobytes("png"))
    doc.close()
    return images


def _render_pdf_pages_to_pngs(pdf_bytes: bytes, max_pages: int = 0) -> List[bytes]:
    """
    Render each page of a PDF as a PNG image (bytes).

    Parameters
    ----------
    pdf_bytes : bytes
        Raw PDF file bytes.
    max_pages : int
        Maximum pages to render (0 = all).

    Returns
    -------
    list[bytes]
        PNG image bytes, one per page.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for i, page in enumerate(doc):
        if max_pages and i >= max_pages:
            break
        pix = page.get_pixmap(dpi=200)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


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

    def extract(self, pdf_bytes: bytes, source_url: str = "",
                page_numbers: Optional[List[int]] = None) -> Tuple[str, List[Dict]]:
        """
        Returns (full_text, page_data_list).
        page_data_list: [{"page": N, "text": "...", "tables": [...]}]
        page_numbers: zero-indexed page numbers to extract (None = all).
        """
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        full_parts = []

        for page_num, page in enumerate(doc, 1):
            if page_numbers is not None and (page_num - 1) not in page_numbers:
                continue
            text = page.get_text("text").strip()
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
    def detect_scan_type(pdf_bytes: bytes) -> str:
        """
        Determine if a PDF is scanned (image-only), text-based, or mixed.

        Examines every page: counts text characters and embedded images.
        A page is classified as "scanned" if it has < 10 text chars and >= 1 image.

        Returns one of: "text", "scanned", "mixed"
        """
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total = len(doc)
        scanned_pages = 0
        text_pages = 0

        for page in doc:
            text_len = len(page.get_text("text").strip())
            # page.get_images(full=True) returns list of (xref, ...) tuples
            img_count = len(page.get_images())
            if text_len < 10 and img_count >= 1:
                scanned_pages += 1
            elif text_len >= 100:
                text_pages += 1

        doc.close()

        if total == 0:
            return "text"

        scanned_ratio = scanned_pages / total
        text_ratio = text_pages / total

        if scanned_ratio >= 0.8:
            return "scanned"
        if text_ratio >= 0.8:
            return "text"

        # Blank / ambiguous PDF with neither images nor substantial text
        if scanned_pages == 0 and text_pages == 0:
            return "text"

        return "mixed"

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


# ── PDFExtractor (orchestrator) ───────────────────────────────────────────────

class PDFExtractor:
    """
    Downloads and extracts text from PDF URLs, returning ContentBlocks.

    Routing
    -------
    When backend="auto_detect", the extractor detects the PDF type via
    detect_scan_type() and routes accordingly:

    - "text"    → extracts via PyMuPDF
    - "scanned" → renders pages as PNG images → vision API / pytesseract
    - "mixed"   → PyMuPDF for text pages + OCR for scanned pages

    Backend selection
    -----------------
    "auto_detect" — (default) detect PDF type and route automatically
    "pymupdf"     — force PyMuPDF only (no image fallback)
    "image"       — treat all PDFs as scanned images, render & OCR every page
    "priority_list"        — alias for "auto_detect"

    Scanned PDF pipeline
    --------------------
    Scanned pages are rendered as 200 DPI PNG images and sent to the vision
    API in a single multi-image call.  Fallback chain:
    GPT-4o mini → Gemma 3 12B (free) → pytesseract

    Usage
    -----
    extractor = PDFExtractor()
    blocks = extractor.from_url("https://example.com/tutorial.pdf")
    """

    def __init__(
        self,
        backend: str = "auto_detect",
        chunk_size: int = 1500,
        chunk_overlap: int = 150,
        min_meaningful_chars: int = _MIN_MEANINGFUL_CHARS,
        timeout: int = 30,
        user_agent: str = "html2mcq/1.1",
        scanned_backend: str = "vision_api",
        scanned_max_pages: int = 50,
        vision_provider: str = "openrouter",
        vision_model: str = "openai/gpt-4o-mini",
        vision_free_model: str = "google/gemma-3-12b-it",
        vision_api_key: str = "",
        ocr_fallback: bool = True,
        ocr_lang: str = "eng",
        ocr_models: Optional[List[str]] = None,
        available_keys: Optional[dict] = None,
        max_tokens: int = 4096,
    ):
        """
        Parameters
        ----------
        backend : str
            "auto_detect" (default) | "pymupdf" | "image" | "priority_list"
        chunk_size : int
            Characters per ContentBlock chunk.
        chunk_overlap : int
            Overlap between consecutive chunks.
        min_meaningful_chars : int
            If PyMuPDF extracts fewer chars than this, trigger fallback.
        timeout : int
            HTTP timeout for downloading PDFs.
        scanned_backend : str
            Backend for scanned/mixed PDF pages: "pytesseract" | "priority_list" | any model ID.
        scanned_max_pages : int
            Max pages to render as images for scanned PDFs (0 = unlimited).
        vision_provider : str
            "openrouter" (default) for vision API.
        vision_model : str
            Primary vision model for scanned pages (default "openai/gpt-4o-mini").
        vision_free_model : str
            Free fallback vision model (default "google/gemma-3-12b-it").
        vision_api_key : str
            API key for vision provider. Falls back to OPENROUTER_API_KEY env.
        ocr_fallback : bool
            If True (default), fall back to Tesseract OCR when vision API fails.
        ocr_lang : str
            Tesseract language code for pytesseract fallback.
        available_keys : dict, optional
            Map of provider -> key for 'auto' provider mode.
        max_tokens : int
            Max tokens for vision API response.
        """
        self.backend = backend.lower()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_meaningful_chars = min_meaningful_chars
        self.timeout = timeout
        self.user_agent = user_agent
        self.scanned_backend = scanned_backend.lower()
        self.scanned_max_pages = scanned_max_pages
        from .image_ocr import ImageOCRExtractor
        self._ocr_models = ImageOCRExtractor._resolve_ocr_models(ocr_models)
        self.vision_provider = vision_provider
        self.vision_model = vision_model
        self.vision_free_model = vision_free_model
        self.vision_api_key = vision_api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.ocr_fallback = ocr_fallback
        self.ocr_lang = ocr_lang
        self.available_keys = available_keys or {}
        self.max_tokens = max_tokens

        # Initialise primary backend eagerly (validates deps)
        self._primary = self._make_backend(self.backend)

    # ── Public API ────────────────────────────────────────────────────────────

    def from_url(self, url: str,
                 page_numbers: Optional[List[int]] = None) -> List[ContentBlock]:
        """Download a PDF from *url* and return ContentBlocks."""
        print(f"  [html2mcq] Downloading PDF: {url}")
        pdf_bytes = _fetch_bytes(url, timeout=self.timeout, user_agent=self.user_agent)
        return self.from_bytes(pdf_bytes, source_url=url, page_numbers=page_numbers)

    def from_bytes(self, pdf_bytes: bytes, source_url: str = "",
                   page_numbers: Optional[List[int]] = None) -> List[ContentBlock]:
        """
        Extract text from raw PDF bytes and return ContentBlocks.

        Routing depends on ``backend``:
        - "image"       → render all pages as images, OCR via vision / pytesseract
        - "pymupdf"     → force PyMuPDF, skip auto-detection
        - "auto_detect" → detect PDF type and route accordingly

        page_numbers: zero-indexed page numbers to process (None = all).
        """
        if self.backend == "image":
            return self._extract_scanned(pdf_bytes, source_url, page_numbers=page_numbers)

        if self.backend == "pymupdf":
            full_text, pages, backend_used = self._extract_with_fallback(
                pdf_bytes, source_url, page_numbers=page_numbers)
            if not full_text.strip():
                print(f"  [html2mcq] ⚠ No text extracted from PDF: {source_url}")
                return []
            return self._make_blocks(full_text, pages, backend_used, source_url)

        # auto_detect (default)
        scan_type = self.detect_scan_type(pdf_bytes)
        print(f"  [html2mcq] PDF scan type: {scan_type} ({source_url})")

        if scan_type == "scanned":
            return self._extract_scanned(pdf_bytes, source_url, page_numbers=page_numbers)
        elif scan_type == "mixed":
            blocks = self._extract_mixed(pdf_bytes, source_url, page_numbers=page_numbers)
            if blocks:
                return blocks
            # Mixed yielded nothing → fall through to text pipeline

        # "text" PDF — use PyMuPDF pipeline
        full_text, pages, backend_used = self._extract_with_fallback(
            pdf_bytes, source_url, page_numbers=page_numbers)

        if not full_text.strip():
            print(f"  [html2mcq] ⚠ No text extracted from PDF: {source_url}")
            return []

        return self._make_blocks(full_text, pages, backend_used, source_url)

    def from_path(self, path: str,
                  page_numbers: Optional[List[int]] = None) -> List[ContentBlock]:
        """Extract text from a local PDF file path."""
        pdf_bytes = Path(path).read_bytes()
        return self.from_bytes(pdf_bytes, source_url=f"file://{path}",
                               page_numbers=page_numbers)

    # ── Scan-type detection ──────────────────────────────────────────────────

    def detect_scan_type(self, pdf_bytes: bytes) -> str:
        """
        Classify a PDF as ``"text"``, ``"scanned"``, or ``"mixed"``.

        Uses PyMuPDF to check each page: if a page has fewer than 10
        extractable text characters **and** at least one embedded image,
        it is counted as scanned.  Ratios >= 80% in either direction
        determine the classification.
        """
        return self._primary.detect_scan_type(pdf_bytes)

    def detect_scan_type_from_path(self, path: str) -> str:
        """Like :meth:`detect_scan_type` but accepts a local file path."""
        return self.detect_scan_type(Path(path).read_bytes())

    # ── Enrich ───────────────────────────────────────────────────────────────

    def render_blocks_to_images(
        self, blocks: List[ContentBlock]
    ) -> List[ContentBlock]:
        """
        Walk a list of ContentBlocks, find all pdf blocks, download and
        render them to PNG images. Returns image blocks with base64 data.
        """
        import base64
        result: List[ContentBlock] = []
        for block in blocks:
            if block.type != "pdf" or not block.content:
                result.append(block)
                continue

            try:
                if block.content.startswith("http"):
                    pdf_bytes = _fetch_bytes(block.content, timeout=self.timeout)
                else:
                    # Treat as local path if file:// or relative
                    p = block.content.replace("file://", "")
                    pdf_bytes = Path(p).read_bytes()

                pngs = _render_pdf_pages_to_pngs(pdf_bytes, max_pages=self.scanned_max_pages)
                for i, png in enumerate(pngs):
                    b64 = base64.b64encode(png).decode("utf-8")
                    result.append(ContentBlock(
                        type="image",
                        content=f"Rendered Page {i+1}",
                        metadata={"image_data": b64, "source": block.content}
                    ))
            except Exception as e:
                print(f"  [html2mcq] ⚠ Failed to render PDF {block.content}: {e}")
                result.append(block)
        return result

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

    # ── Scanned / mixed PDF extraction ────────────────────────────────────────

    def _extract_scanned(self, pdf_bytes: bytes, source_url: str,
                         page_numbers: Optional[List[int]] = None) -> List[ContentBlock]:
        """Render scanned PDF pages as images, OCR via vision API / pytesseract."""
        page_count = _count_pdf_pages(pdf_bytes)
        if page_numbers is not None:
            page_numbers = [p for p in page_numbers if p < page_count]
            print(f"  [html2mcq] Rendering {len(page_numbers)}/{page_count} pages as images for vision OCR...")
            pngs = _render_specific_pages(pdf_bytes, page_numbers, max_pages=self.scanned_max_pages)
        else:
            print(f"  [html2mcq] Rendering {page_count} pages as images for vision OCR...")
            pngs = _render_pdf_pages_to_pngs(pdf_bytes, max_pages=self.scanned_max_pages)
        if not pngs:
            return []

        if self.scanned_backend == "priority_list":
            text = self._ocr_scanned_via_auto(pngs)
        elif self.scanned_backend == "pytesseract":
            text = self._ocr_scanned_via_pytesseract(pngs)
        else:
            # Treat scanned_backend as a direct model name
            from .image_ocr import _ocr_vision_api
            try:
                text = _ocr_vision_api(
                    pngs, model=self.scanned_backend,
                    api_key=self.vision_api_key, provider=self.vision_provider,
                    max_tokens=self.max_tokens,
                )
                if text.strip():
                    pass  # use it
            except Exception as e:
                err_msg = str(e)
                no_balance = any(
                    kw in err_msg.lower()
                    for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                )
                if no_balance:
                    print(f"  [html2mcq] \u26a0 ({self.vision_provider}) '{self.scanned_backend}': insufficient balance")
                else:
                    err_msg_line = err_msg.split('\n')[0][:100]
                    print(f"  [html2mcq] \u26a0 ({self.vision_provider}) '{self.scanned_backend}' failed: {err_msg_line}")
                # Fall back to auto, skipping the failed model
                fallback = [m for m in self._ocr_models if m != self.scanned_backend]
                if fallback:
                    print(f"  [html2mcq] → falling back to auto (skipping {self.scanned_backend})")
                    text = self._ocr_scanned_via_auto(pngs, models=fallback)
                else:
                    text = ""

        if not text.strip():
            print(f"  [html2mcq] ⚠ No text extracted from scanned PDF: {source_url}")
            return []

        backend_name = f"scanned_{self.scanned_backend}"
        chunks = _chunk_text(text, self.chunk_size, self.chunk_overlap)
        blocks = []
        for i, chunk in enumerate(chunks):
            blocks.append(ContentBlock(
                type="pdf_text",
                content=chunk,
                metadata={
                    "source_url": source_url,
                    "backend": backend_name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "total_pages": page_count,
                    "char_count": len(chunk),
                    "scanned": True,
                },
            ))

        print(
            f"  [html2mcq] ✓ Scanned PDF extracted via {backend_name}: "
            f"{page_count} pages → {len(blocks)} chunks ({len(text)} chars)"
        )
        return blocks

    def _extract_mixed(self, pdf_bytes: bytes, source_url: str,
                       page_numbers: Optional[List[int]] = None) -> List[ContentBlock]:
        """
        Mixed PDF: extract text pages via PyMuPDF, OCR scanned pages via vision.

        Uses PyMuPDF's detect_scan_type internally to identify which pages
        are scanned (text_len < 10 + image) and renders only those pages.
        """
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        scanned_page_nums = []
        text_page_texts = {}
        for i, page in enumerate(doc):
            if page_numbers is not None and i not in page_numbers:
                continue
            text_len = len(page.get_text("text").strip())
            img_count = len(page.get_images())
            if text_len < 10 and img_count >= 1:
                scanned_page_nums.append(i)
            elif text_len >= 10:
                text_page_texts[i] = page.get_text("text").strip()
        total_pages = len(doc)
        doc.close()

        # Extract text pages via PyMuPDF
        text_content = "\n\n".join(
            f"[Page {n+1}]\n{t}" for n, t in sorted(text_page_texts.items())
        )

        # OCR scanned pages
        scanned_content = ""
        if scanned_page_nums:
            print(f"  [html2mcq] Mixed PDF: {len(text_page_texts)} text pages, "
                  f"{len(scanned_page_nums)} scanned pages → rendering...")
            pngs = _render_specific_pages(pdf_bytes, scanned_page_nums,
                                          max_pages=self.scanned_max_pages)
            if pngs:
                from .image_ocr import _ocr_vision_api
                if self.scanned_backend == "priority_list":
                    scanned_content = self._ocr_scanned_via_auto(pngs)
                elif self.scanned_backend == "pytesseract":
                    scanned_content = self._ocr_scanned_via_pytesseract(pngs)
                else:
                    try:
                        scanned_content = _ocr_vision_api(
                            pngs, model=self.scanned_backend,
                            api_key=self.vision_api_key, provider=self.vision_provider,
                            max_tokens=self.max_tokens,
                        )
                        if scanned_content.strip():
                            pass
                    except Exception as e:
                        err_msg = str(e)
                        no_balance = any(
                            kw in err_msg.lower()
                            for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                        )
                        if no_balance:
                            print(f"  [html2mcq] \u26a0 ({self.vision_provider}) '{self.scanned_backend}': insufficient balance")
                        else:
                            err_msg_line = err_msg.split('\n')[0][:100]
                            print(f"  [html2mcq] \u26a0 ({self.vision_provider}) '{self.scanned_backend}' failed: {err_msg_line}")
                        # Fall back to auto, skipping the failed model
                        fallback = [m for m in self._ocr_models if m != self.scanned_backend]
                        if fallback:
                            print(f"  [html2mcq] → falling back to auto (skipping {self.scanned_backend})")
                            scanned_content = self._ocr_scanned_via_auto(pngs, models=fallback)
                        else:
                            scanned_content = ""

        full_text = text_content
        if scanned_content.strip():
            full_text += "\n\n[Scanned pages OCR]\n" + scanned_content

        if not full_text.strip():
            return []

        backend_name = f"mixed_pymupdf+{self.scanned_backend}"
        chunks = _chunk_text(full_text, self.chunk_size, self.chunk_overlap)
        blocks = []
        for i, chunk in enumerate(chunks):
            blocks.append(ContentBlock(
                type="pdf_text",
                content=chunk,
                metadata={
                    "source_url": source_url,
                    "backend": backend_name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "total_pages": total_pages,
                    "char_count": len(chunk),
                    "scanned_pages_ocr": len(scanned_page_nums),
                    "text_pages": len(text_page_texts),
                },
            ))

        print(
            f"  [html2mcq] ✓ Mixed PDF extracted via {backend_name}: "
            f"{total_pages} pages ({len(text_page_texts)} text + "
            f"{len(scanned_page_nums)} scanned) → {len(blocks)} chunks ({len(full_text)} chars)"
        )
        return blocks

    def _ocr_scanned_via_vision(self, pngs: List[bytes]) -> str:
        """Send rendered page images to vision API with fallback chain."""
        from .image_ocr import _ocr_vision_with_fallback

        return _ocr_vision_with_fallback(
            pngs,
            primary_model=self.vision_model,
            free_model=self.vision_free_model,
            api_key=self.vision_api_key,
            provider=self.vision_provider,
            fallback_to_tesseract=self.ocr_fallback,
            tesseract_lang=self.ocr_lang,
            max_tokens=self.max_tokens,
        )

    def _ocr_scanned_via_pytesseract(self, pngs: List[bytes]) -> str:
        """OCR rendered pages directly with pytesseract."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            raise ImportError("pip install pytesseract Pillow")

        texts = []
        for img_bytes in pngs:
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang=self.ocr_lang)
            if text.strip():
                texts.append(text.strip())
        return "\n\n".join(texts)

    def _ocr_scanned_via_auto(self, pngs: List[bytes],
                               models: Optional[List[str]] = None) -> str:
        """Try each model in *models* (or self._ocr_models) priority order until one succeeds."""
        from .image_ocr import _ocr_vision_api, _ocr_pytesseract, parse_operator_model

        for model in models or self._ocr_models:
            res = parse_operator_model(model, self.vision_provider, self.available_keys)
            if not res:
                continue
            
            p_target, current_model = res
            
            # Determine API key for this specific model call
            if self.vision_provider == "auto":
                p_key = self.available_keys.get(p_target, "")
            else:
                p_key = self.vision_api_key

            try:
                result = _ocr_vision_api(
                    pngs, model=current_model,
                    api_key=p_key, provider=p_target,
                    max_tokens=self.max_tokens,
                )
                if result:
                    print(f"  [html2mcq] ✓ ({p_target}) {current_model}: {len(result)} chars")
                    return result
            except Exception as e:
                err_msg = str(e)
                no_balance = any(
                    kw in err_msg.lower()
                    for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                )
                if no_balance:
                    print(f"  [html2mcq] \u26a0 ({p_target}) '{current_model}': insufficient balance")
                else:
                    err_msg_line = err_msg.split('\n')[0][:100]
                    print(f"  [html2mcq] \u26a0 ({p_target}) '{current_model}' failed: {err_msg_line}")
                continue
        return ""

    def _make_blocks(
        self, full_text: str, pages: List[Dict], backend_used: str, source_url: str
    ) -> List[ContentBlock]:
        """Split text into chunks and wrap in ContentBlocks."""
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

    # ── Private helpers ───────────────────────────────────────────────────────

    def _make_backend(self, name: str):
        if name in ("pymupdf", "auto_detect", "priority_list"):
            return _PyMuPDFBackend()
        if name == "image":
            return None
        raise ValueError(
            f"Unknown PDF backend '{name}'. "
            "Choose: auto_detect | pymupdf | image"
        )

    def _extract_with_fallback(
        self, pdf_bytes: bytes, source_url: str,
        page_numbers: Optional[List[int]] = None
    ) -> Tuple[str, List[Dict], str]:
        """
        Try primary backend.

        Returns (full_text, pages, backend_name_used)
        """
        try:
            full_text, pages = self._primary.extract(pdf_bytes, source_url,
                                                     page_numbers=page_numbers)
        except Exception as e:
            print(f"  [html2mcq] ⚠ {self._primary.name} failed: {e}")
            full_text, pages = "", []

        return full_text, pages, self._primary.name
