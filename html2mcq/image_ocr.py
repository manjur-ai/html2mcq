"""
ImageOCRExtractor: Downloads images found in HTML and extracts text via OCR / vision API.

Backends:
1. "pytesseract" — Tesseract OCR (lightweight, needs tesseract binary).
2. "auto" — tries models in priority order until one succeeds.
             Default priority: gemini-2.5-flash-lite → gemma-27b → gemma-12b → gpt-4o → pytesseract.
             Override via ocr_models param or HTML2MCQ_OCR_MODELS env var.
3. Any OpenRouter model ID (e.g. "google/gemini-2.5-flash-lite", "openai/gpt-4o") —
   sends images directly to that vision model via OpenRouter.

Usage
-----
ocr = ImageOCRExtractor(backend="auto")
enriched = ocr.enrich_blocks(extracted_blocks)

ocr = ImageOCRExtractor(backend="openai/gpt-4o")
enriched = ocr.enrich_blocks(extracted_blocks)
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .models import ContentBlock

_PIL_AVAILABLE = False
try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    pass


def _download_image(url: str, timeout: int = 15, max_bytes: int = 10 * 1024 * 1024) -> bytes:
    """Download image bytes from URL. Returns empty bytes on failure or if too large."""
    if url.startswith("data:"):
        # data:image/png;base64,<base64data>
        try:
            _, b64data = url.split(",", 1)
            return base64.b64decode(b64data)
        except Exception:
            return b""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "html2mcq/1.3 (image OCR)",
                "Accept": "image/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) > max_bytes:
            return b""
        return data
    except Exception:
        return b""


# ── Backend: vision API (OpenRouter / OpenAI-compatible) ───────────────────────

_DEFAULT_VISION_MODEL = "google/gemini-2.5-flash-lite"
_FREE_VISION_MODEL = "google/gemma-3-12b-it"

# Default priority list for ocr_model="auto".
# Entries can be full OpenRouter model IDs or "pytesseract" for local Tesseract OCR.
# Override via ocr_models parameter or HTML2MCQ_OCR_MODELS env var (comma-separated).
_DEFAULT_OCR_PRIORITY = [
    "google/gemini-2.5-flash-lite",
    "google/gemma-3-27b-it",
    "google/gemma-3-12b-it",
    "openai/gpt-4o",
    "pytesseract",
]
_OCR_MODELS_ENV_VAR = "HTML2MCQ_OCR_MODELS"

def _ocr_vision_api(
    image_bytes_list: List[bytes],
    model: str = _DEFAULT_VISION_MODEL,
    api_key: str = "",
    provider: str = "openrouter",
    max_tokens: int = 4096,
) -> str:
    """
    Send one or more images to a vision model via an OpenAI-compatible API.

    Parameters
    ----------
    image_bytes_list : list[bytes]
        PNG image bytes for each image/page.
    model : str
        Model name (e.g. "openai/gpt-4o-mini", "google/gemma-3-12b-it").
    api_key : str
        API key. Falls back to OPENROUTER_API_KEY env var.
    provider : str
        "openrouter" (default) uses https://openrouter.ai/api/v1.
    max_tokens : int
        Max tokens for the response.

    Returns
    -------
    str
        Extracted text from the image(s).
    """
    try:
        import openai
    except ImportError:
        raise ImportError("pip install openai")

    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError(
            "No API key for vision API. Pass api_key= or set OPENROUTER_API_KEY env var."
        )

    if provider == "openrouter":
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
    else:
        client = openai.OpenAI(api_key=api_key)

    content: list = [
        {
            "type": "text",
            "text": (
                "You are an OCR tool. Read the text from this image. "
                "Preserve headings, paragraphs, bullet points, and list items. "
                "If the image contains multiple boxes, dialogs, or columns, "
                "preserve the order as a human would read them naturally. "
                "For book scans, extract only the main page content and "
                "ignore partly visible pages, overlapping pages, "
                "handwritten notes, and any side objects or artifacts. "
                "If the image contains figures, diagrams, or charts, "
                "describe each one concisely. "
                "Output plain text only, no markdown formatting, "
                "no explanations, no commentary."
            ),
        }
    ]
    for img_bytes in image_bytes_list:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _ocr_vision_with_fallback(
    image_bytes_list: List[bytes],
    primary_model: str = _DEFAULT_VISION_MODEL,
    free_model: str = _FREE_VISION_MODEL,
    api_key: str = "",
    provider: str = "openrouter",
    fallback_to_tesseract: bool = True,
    tesseract_lang: str = "eng",
) -> str:
    """
    Try primary vision model, fall back to free model, then pytesseract.

    Returns empty string if all fail.
    """
    # 1. Primary model
    if primary_model:
        try:
            return _ocr_vision_api(
                image_bytes_list, model=primary_model,
                api_key=api_key, provider=provider,
            )
        except Exception as e:
            err_msg = str(e)
            # Common "no balance" indicators
            no_balance = any(
                kw in err_msg.lower()
                for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
            )
            if no_balance:
                print(f"  [html2mcq] ⚠ {primary_model}: insufficient balance")
            else:
                print(f"  [html2mcq] ⚠ {primary_model} failed: {err_msg[:120]}")

    # 2. Free fallback model
    if free_model and free_model != primary_model:
        try:
            return _ocr_vision_api(
                image_bytes_list, model=free_model,
                api_key=api_key, provider=provider,
            )
        except Exception as e:
            print(f"  [html2mcq] ⚠ {free_model} fallback failed: {str(e)[:120]}")

    # 3. pytesseract last resort
    if fallback_to_tesseract:
        try:
            import pytesseract
            from PIL import Image

            texts = []
            for img_bytes in image_bytes_list:
                img = Image.open(io.BytesIO(img_bytes))
                text = pytesseract.image_to_string(img, lang=tesseract_lang)
                if text.strip():
                    texts.append(text.strip())
            if texts:
                print(f"  [html2mcq] ✓ pytesseract fallback: {sum(len(t) for t in texts)} chars")
                return "\n\n".join(texts)
        except Exception as e:
            print(f"  [html2mcq] ⚠ pytesseract fallback failed: {str(e)[:120]}")

    return ""


# ── Backend: pytesseract ───────────────────────────────────────────────────────

def _ocr_pytesseract(image_bytes: bytes, lang: str = "eng") -> str:
    """OCR using pytesseract + Pillow."""
    try:
        import pytesseract
    except ImportError:
        raise ImportError(
            "pytesseract is required for image OCR.\n"
            "Install with:  pip install pytesseract Pillow\n"
            "Also install Tesseract binary: https://github.com/tesseract-ocr/tesseract"
        )
    if not _PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    img = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(img, lang=lang)
    return text.strip()


# ── ImageOCRExtractor ─────────────────────────────────────────────────────────

class ImageOCRExtractor:
    """
    Downloads images from ContentBlocks and extracts text via OCR / vision API.

    Backends
    --------
    "pytesseract" — Tesseract OCR (lightweight, needs tesseract binary).
    "auto"        — Tries models in priority order until one succeeds.
                    Default: gpt-4o → gemma-27b → gemma-12b → pytesseract.
                    Override via ocr_models param or HTML2MCQ_OCR_MODELS env var.
    Any model ID — Sends images directly to that OpenRouter model (e.g. "openai/gpt-4o").

    Usage
    -----
    ocr = ImageOCRExtractor(backend="auto")
    blocks = ocr.enrich_blocks(extracted_blocks)
    """

    def __init__(
        self,
        backend: str = "auto",
        min_text_length: int = 15,
        max_image_size_mb: int = 10,
        timeout: int = 15,
        lang: str = "eng",
        vision_provider: str = "openrouter",
        vision_model: str = _DEFAULT_VISION_MODEL,
        vision_free_model: str = _FREE_VISION_MODEL,
        vision_api_key: str = "",
        ocr_fallback: bool = True,
        ocr_models: Optional[List[str]] = None,
    ):
        """
        Parameters
        ----------
        backend : str
            "pytesseract" | "auto" | any OpenRouter model ID (e.g. "openai/gpt-4o").
        min_text_length : int
            Minimum characters of extracted text to consider useful.
        max_image_size_mb : int
            Skip images larger than this (download size).
        timeout : int
            HTTP download timeout in seconds.
        lang : str
            Tesseract language code (e.g. "eng", "fra").
        vision_provider : str
            "openrouter" (default) uses https://openrouter.ai/api/v1.
        vision_model : str
            Primary vision model for vision_api backend.
        vision_free_model : str
            Free fallback vision model for vision_api backend.
        vision_api_key : str
            API key for vision provider. Falls back to OPENROUTER_API_KEY env.
        ocr_fallback : bool
            Fall back to Tesseract when vision API fails (vision_api backend).
        ocr_models : list[str], optional
            Priority-ordered model list for backend="auto".
            Entries are OpenRouter model IDs or "pytesseract".
            Falls back to HTML2MCQ_OCR_MODELS env var, then built-in default.
        """
        self.backend = backend.lower()
        self.min_text_length = min_text_length
        self.max_image_size_mb = max_image_size_mb
        self.timeout = timeout
        self.lang = lang
        self.vision_provider = vision_provider
        self.vision_model = vision_model
        self.vision_free_model = vision_free_model
        self.vision_api_key = vision_api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.ocr_fallback = ocr_fallback

        # Parse the priority-ordered model list for "auto" backend
        self.ocr_models = self._resolve_ocr_models(ocr_models)

    @staticmethod
    def _resolve_ocr_models(ocr_models: Optional[List[str]] = None) -> List[str]:
        """Resolve the priority-ordered model list.

        Precedence: explicit param > HTML2MCQ_OCR_MODELS env var > built-in default.
        """
        if ocr_models:
            return list(ocr_models)
        env = os.environ.get(_OCR_MODELS_ENV_VAR, "").strip()
        if env:
            return [m.strip() for m in env.split(",") if m.strip()]
        return list(_DEFAULT_OCR_PRIORITY)

        # Parse the priority-ordered model list for "auto" backend
        self.ocr_models = self._resolve_ocr_models(ocr_models)

    def enrich_blocks(
        self, blocks: List[ContentBlock], replace: bool = True
    ) -> List[ContentBlock]:
        """
        Walk a list of ContentBlocks, find all image blocks, download and OCR
        them in parallel, and return an enriched block list.

        Parameters
        ----------
        blocks : list[ContentBlock]
            Existing blocks from ContentExtractor.
        replace : bool
            If True (default), replace the original image block with image_ocr block.
            If False, keep the original image block and append image_ocr after it.
        """
        # ── Collect image blocks that need OCR ──
        image_tasks: List[Tuple[int, str, str]] = []
        for i, block in enumerate(blocks):
            if block.type == "image" and block.content:
                image_tasks.append((i, block.content, block.alt_text or ""))

        if not image_tasks:
            return list(blocks)

        # ── OCR all images in parallel ──
        ocr_results: Dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=len(image_tasks)) as pool:
            fut_to_idx = {
                pool.submit(self._ocr, url, alt): idx
                for idx, url, alt in image_tasks
            }
            for fut in as_completed(fut_to_idx):
                idx = fut_to_idx[fut]
                try:
                    text = fut.result()
                    if text:
                        ocr_results[idx] = text
                except Exception:
                    pass

        # ── Rebuild block list ──
        enriched: List[ContentBlock] = []
        for i, block in enumerate(blocks):
            if i in ocr_results:
                text = ocr_results[i]
                ocr_block = ContentBlock(
                    type="image_ocr",
                    content=text,
                    caption=block.alt_text or block.caption or "",
                    metadata={
                        "source_url": block.content,
                        "backend": self.backend,
                        "char_count": len(text),
                    },
                )
                if replace:
                    enriched.append(ocr_block)
                else:
                    enriched.append(block)
                    enriched.append(ocr_block)
            else:
                enriched.append(block)
        return enriched

    def _ocr_bytes(self, image_bytes: bytes) -> str:
        """OCR a single image from raw PNG bytes."""
        if self.backend == "auto":
            return self._ocr_auto([image_bytes])
        elif self.backend == "pytesseract":
            return _ocr_pytesseract(image_bytes, lang=self.lang)
        else:
            # Treat backend as a direct model name
            try:
                result = _ocr_vision_api(
                    [image_bytes],
                    model=self.backend,
                    api_key=self.vision_api_key,
                    provider=self.vision_provider,
                )
                if result.strip():
                    return result
            except Exception as e:
                err_msg = str(e)
                no_balance = any(
                    kw in err_msg.lower()
                    for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                )
                if no_balance:
                    print(f"  [html2mcq] ⚠ {self.backend}: insufficient balance")
                else:
                    print(f"  [html2mcq] ⚠ {self.backend} failed: {err_msg[:120]}")
            # Fall back to auto, skipping the failed model to avoid retrying
            fallback = [m for m in self.ocr_models if m != self.backend]
            if fallback:
                print(f"  [html2mcq] → falling back to auto (skipping {self.backend})")
                return self._ocr_auto([image_bytes], models=fallback)
            return ""

    def ocr_image_bytes(self, image_bytes_list: List[bytes]) -> str:
        """
        OCR one or more images from raw PNG bytes (for scanned PDF pipeline).

        All images are sent together in one API call (multi-image vision) to
        avoid duplicate content across pages.
        """
        if not image_bytes_list:
            return ""

        if self.backend == "auto":
            return self._ocr_auto(image_bytes_list)
        elif self.backend == "pytesseract":
            texts = [_ocr_pytesseract(img, lang=self.lang) for img in image_bytes_list]
            return "\n\n".join(t for t in texts if t.strip())
        else:
            # Treat backend as a direct model name
            try:
                result = _ocr_vision_api(
                    image_bytes_list,
                    model=self.backend,
                    api_key=self.vision_api_key,
                    provider=self.vision_provider,
                )
                if result.strip():
                    return result
            except Exception as e:
                err_msg = str(e)
                no_balance = any(
                    kw in err_msg.lower()
                    for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                )
                if no_balance:
                    print(f"  [html2mcq] ⚠ {self.backend}: insufficient balance")
                else:
                    print(f"  [html2mcq] ⚠ {self.backend} failed: {err_msg[:120]}")
            # Fall back to auto, skipping the failed model to avoid retrying
            fallback = [m for m in self.ocr_models if m != self.backend]
            if fallback:
                print(f"  [html2mcq] → falling back to auto (skipping {self.backend})")
                return self._ocr_auto(image_bytes_list, models=fallback)
            return ""

    def _ocr(self, url: str, alt_text: str = "") -> str:
        """Download and OCR a single image."""
        max_bytes = self.max_image_size_mb * 1024 * 1024
        image_bytes = _download_image(url, timeout=self.timeout, max_bytes=max_bytes)
        if not image_bytes:
            return ""
        return self._ocr_bytes(image_bytes)

    def _ocr_auto(self, image_bytes_list: List[bytes],
                   models: Optional[List[str]] = None) -> str:
        """Try each model in *models* (or self.ocr_models) priority order until one succeeds."""
        for model in models or self.ocr_models:
            if model.lower() == "pytesseract":
                try:
                    texts = []
                    for img_bytes in image_bytes_list:
                        text = _ocr_pytesseract(img_bytes, lang=self.lang)
                        if text.strip():
                            texts.append(text.strip())
                    if texts:
                        result = "\n\n".join(texts)
                        print(f"  [html2mcq] ✓ {model}: {len(result)} chars")
                        return result
                except Exception as e:
                    print(f"  [html2mcq] ⚠ {model} failed: {str(e)[:120]}")
                    continue
            else:
                try:
                    result = _ocr_vision_api(
                        image_bytes_list, model=model,
                        api_key=self.vision_api_key, provider=self.vision_provider,
                    )
                    if result:
                        print(f"  [html2mcq] ✓ {model}: {len(result)} chars")
                        return result
                except Exception as e:
                    err_msg = str(e)
                    no_balance = any(
                        kw in err_msg.lower()
                        for kw in ("insufficient", "balance", "quota", "credits", "402", "payment")
                    )
                    if no_balance:
                        print(f"  [html2mcq] ⚠ {model}: insufficient balance")
                    else:
                        print(f"  [html2mcq] ⚠ {model} failed: {err_msg[:120]}")
                    continue
        return ""
