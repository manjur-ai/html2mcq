"""
MCQGenerator: The main public API for html2mcq.
Ties together ContentExtractor + AI backend to produce MCQSets.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union

import base64 as _base64

from .extractor import ContentExtractor
from .models import ContentBlock, MCQQuestion, MCQSet
from .prompts import build_system_prompt, build_user_prompt
from .pdf import PDFExtractor
from .image_ocr import ImageOCRExtractor, _download_image


# ── AI backend registry ───────────────────────────────────────────────────────

class _AnthropicBackend:
    """Uses the official anthropic SDK."""

    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, api_key: str, mcq_model: str):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "Missing 'anthropic' package. Install it with: pip install anthropic\n"
                f"  Original error: {e}"
            ) from e
        self.client = anthropic.Anthropic(api_key=api_key)
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        msg = self.client.messages.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class _OpenAIBackend:
    """Uses the official openai SDK."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, mcq_model: str):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(api_key=api_key)
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _OpenRouterBackend:
    """
    Uses OpenRouter (https://openrouter.ai) — drop-in for any model
    including Llama, Mistral, Gemini via the OpenAI-compatible API.
    """

    DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"

    def __init__(self, api_key: str, mcq_model: str, site_url: str = "", site_name: str = "html2mcq"):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _OllamaBackend:
    """
    Uses a local Ollama instance via its OpenAI-compatible endpoint.

    Best model for 8GB VRAM: ``qwen2.5:7b`` (Q4_K_M, ~4.5 GB).
    Also good: ``llama3.1:8b`` (~4.7 GB), ``mistral:7b`` (~4.1 GB).
    """

    DEFAULT_MODEL = "qwen2.5:7b"

    def __init__(self, api_key: str, mcq_model: str, ollama_base_url: str = "http://localhost:11434/v1"):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(
            api_key=api_key or "ollama",
            base_url=ollama_base_url,
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


def _make_backend(provider: str, api_key: str, mcq_model: str, **kwargs):
    provider = provider.lower()
    if provider == "anthropic":
        return _AnthropicBackend(api_key, mcq_model)
    if provider == "openai":
        return _OpenAIBackend(api_key, mcq_model)
    if provider == "openrouter":
        return _OpenRouterBackend(api_key, mcq_model)
    if provider == "ollama":
        return _OllamaBackend(api_key, mcq_model, **kwargs)
    raise ValueError(f"Unknown provider '{provider}'. Choose: anthropic | openai | openrouter | ollama")


class _OverrideContext:
    """Temporarily overrides backend and/or prompt_log_path on MCQGenerator."""
    def __init__(self, gen, api_key_override, prompt_log_path):
        self.gen = gen
        self.api_key = api_key_override
        self.log_path = prompt_log_path
        self._orig_backend = None
        self._orig_log = None

    def __enter__(self):
        if self.api_key is not None:
            self._orig_backend = self.gen.backend
            self.gen.backend = _make_backend(
                self.gen.provider, self.api_key, self.gen.mcq_model,
            )
        if self.log_path is not None:
            self._orig_log = getattr(self.gen, "prompt_log_path", None)
            self.gen.prompt_log_path = self.log_path
        return self

    def __exit__(self, *args):
        if self._orig_backend is not None:
            self.gen.backend = self._orig_backend
        if self.log_path is not None:
            self.gen.prompt_log_path = self._orig_log


# ── MCQGenerator ──────────────────────────────────────────────────────────────

class MCQGenerator:
    """
    Generate N MCQ questions from any HTML tutorial page, PDF, or image.

    Quick start
    -----------
    >>> from html2mcq import MCQGenerator
    >>> gen = MCQGenerator(api_key="sk-or-...", provider="openrouter")
    >>> mcq_set = gen.from_url("https://docs.python.org/3/tutorial/", n=10)
    >>> print(mcq_set.to_pretty_str())

    Parameters
    ----------
    api_key : str
        Your AI provider API key. Falls back to environment variables:
        ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY.
    provider : str
        "openrouter" (default) | "anthropic" | "openai" | "ollama"
    mcq_model : str
        Model for MCQ generation (both text-based and vision-based).
        A specific model ID (e.g. "openai/gpt-4o", "google/gemini-2.5-flash-lite"),
        or "auto" to try mcq_model_list until one succeeds.
        Also controls the vision model used by ``from_image_paths`` /
        ``from_image_urls``. Defaults to the provider's default model when empty.
    mcq_model_list : list of str, optional
        Priority-ordered model list for mcq_model="auto".
        Runtime-reloadable via HTML2MCQ_MCQ_MODELS env var (comma-separated).

    --- OCR / Vision ---
    ocr_model : str
        OCR backend for extracting text from images in HTML pages.
        "pytesseract" (default, needs tesseract binary) | "auto" (tries priority list)
        | any OpenRouter model ID (e.g. "google/gemini-2.5-flash-lite").
        Does *not* affect ``from_image_paths`` / ``from_image_urls`` — those
        use ``mcq_model`` for the vision model.
    ocr_models : list of str, optional
        Priority-ordered model list for ocr_model="auto".
        Entries are OpenRouter model IDs or "pytesseract".
        Falls back to HTML2MCQ_OCR_MODELS env var, then built-in default.
    ocr_fallback : bool
        If True (default), fall back to Tesseract OCR when vision API fails.
    ocr_lang : str
        Tesseract language code (default "eng").

    --- Generation Options ---
    method : str
        Image processing method:
        - ``"twostep"`` (default) — OCR images to text, then generate MCQs from text
        - ``"images2mcq"`` — send images directly to vision model for MCQ generation
    batch_size : int
        Number of questions to request per API call (default 10).
    max_tokens : int
        Max tokens for each API response (default 4096).
    custom_instructions : str, optional
        Custom instructions appended to the AI prompt.
    prompt_log_path : str, optional
        Path to dump prompts to file. Use "-" or "stdout" to print to terminal.
    api_key_override : str, optional
        API key used instead of the primary api_key for this instance.

    --- Extraction Options ---
    extractor_kwargs : dict
        Keyword args forwarded to ContentExtractor.
    pdf_backend : str
        "auto_detect" (default) | "pymupdf" | "image"
    pdf_scanned_max_pages : int
        Max pages to render as images for scanned PDFs (default 50).

    --- Advanced ---
    pdf_chunk_size : int
        Characters per ContentBlock chunk for PDFs (default 1500).
    **backend_kwargs
        Extra args forwarded to the text-to-MCQ backend (e.g. site_url for OpenRouter).
    """

    ENV_KEYS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "ollama": "",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "openrouter",
        mcq_model: str = "",
        mcq_model_list: Optional[List[str]] = None,
        ocr_model: str = "pytesseract",
        ocr_models: Optional[List[str]] = None,
        ocr_fallback: bool = True,
        ocr_lang: str = "eng",
        method: str = "twostep",
        batch_size: int = 10,
        max_tokens: int = 4096,
        custom_instructions: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        save_ocr_path: Optional[str] = None,
        api_key_override: Optional[str] = None,
        extractor_kwargs: Optional[dict] = None,
        pdf_backend: str = "auto_detect",
        pdf_scanned_max_pages: int = 50,
        pdf_chunk_size: int = 1500,
        **backend_kwargs,
    ):
        self.provider = provider.lower()
        self.mcq_model = mcq_model
        self.mcq_model_list = mcq_model_list
        self.method = method.lower()
        if self.method not in ("twostep", "images2mcq"):
            raise ValueError(f"Unknown method '{method}'. Choose: twostep | images2mcq")
        if self.provider == "ollama":
            _key = "ollama"
            if self.mcq_model in ("", "auto"):
                self.mcq_model = _OllamaBackend.DEFAULT_MODEL
        else:
            _key = api_key or os.environ.get(self.ENV_KEYS.get(self.provider, ""), "")
            if not _key:
                raise ValueError(
                    f"No API key supplied. Pass api_key= or set "
                    f"{self.ENV_KEYS.get(self.provider, 'YOUR_API_KEY')} env var."
                )
        self.backend = _make_backend(self.provider, _key, self.mcq_model, **backend_kwargs)
        if api_key_override:
            self.backend = _make_backend(self.provider, api_key_override, self.mcq_model, **backend_kwargs)
        self.batch_size = max(1, batch_size)
        self.max_tokens = max_tokens
        self.extractor = ContentExtractor(**(extractor_kwargs or {}))

        # ── Derive downstream params ─────────────────────────────────────
        image_ocr_backend = ocr_model
        pdf_scanned_backend = ocr_model
        # For vision-based paths (images2mcq, from_image_*, scanned PDFs),
        # derive the vision model from mcq_model (same parameter for all MCQ generation)
        _DEFAULT_VISION = "google/gemini-2.5-flash-lite"
        if self.mcq_model and self.mcq_model not in ("auto",):
            _vision_model = self.mcq_model
        else:
            _vision_model = _DEFAULT_VISION
        _vision_free_model = "google/gemma-3-12b-it"

        # Image OCR / vision (for method="twostep")
        self.image_ocr_extractor = ImageOCRExtractor(
            backend=image_ocr_backend,
            lang=ocr_lang,
            vision_provider="openrouter",
            vision_model=_vision_model,
            vision_free_model=_vision_free_model,
            vision_api_key=_key,
            ocr_fallback=ocr_fallback,
            ocr_models=ocr_models,
        )

        # PDF (text + scanned)
        self.pdf_extractor = PDFExtractor(
            backend=pdf_backend,
            chunk_size=pdf_chunk_size,
            scanned_backend=pdf_scanned_backend,
            scanned_max_pages=pdf_scanned_max_pages,
            vision_provider="openrouter",
            vision_model=_vision_model,
            vision_free_model=_vision_free_model,
            vision_api_key=_key,
            ocr_fallback=ocr_fallback,
            ocr_lang=ocr_lang,
            ocr_models=ocr_models,
        )
        self.custom_instructions = custom_instructions or ""
        self.prompt_log_path = prompt_log_path
        self.save_ocr_path = save_ocr_path

    def _log_prompt(self, label: str, text: str):
        """Append *text* to the prompt log file if *prompt_log_path* is set.
        Use ``"-"`` or ``"stdout"`` as the path to print to terminal."""
        path = getattr(self, "prompt_log_path", None)
        if path:
            if path in ("-", "stdout"):
                print(f"\n===== {label} =====\n{text}")
            else:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n===== {label} =====\n{text}\n")

    # ── Public API ────────────────────────────────────────────────────────────

    def _with_overrides(self, api_key_override: Optional[str] = None,
                        prompt_log_path: Optional[str] = None):
        """Context manager for per-call overrides. Usage::

            with self._with_overrides(api_key_override, prompt_log_path):
                # existing logic …
        """
        return _OverrideContext(self, api_key_override, prompt_log_path)




    def from_html(
        self,
        html: str,
        n: int = 999,
        base_url: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_pdfs: bool = True,
        enrich_images: bool = True,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate *n* MCQs from raw HTML.

        Parameters
        ----------
        html : str
            Raw HTML content.
        n : int
            Number of questions.
        base_url : str
            Used to resolve relative links inside the HTML.
        enrich_pdfs : bool
            Auto-download and extract PDF links found in page (default True).
        enrich_images : bool
            Auto-download and OCR images found in page (default True).
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts for this call. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            title, blocks = self.extractor.from_html(html, base_url=base_url)
            if enrich_pdfs:
                blocks = self.pdf_extractor.enrich_blocks(blocks)

            if enrich_images and self.method == "twostep":
                blocks = self.image_ocr_extractor.enrich_blocks(blocks)

            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=title,
                source_url=base_url or None,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )

            if enrich_images and self.method == "images2mcq":
                img_blocks = [b for b in blocks if b.type == "image" and b.content]
                remaining = n - len(all_qs)
                if img_blocks and remaining > 0:
                    vision_qs = self._vision_mcq(img_blocks, n=remaining, page_title=title)
                    all_qs.extend(vision_qs)

            return self._build_mcq_set(all_qs, n, title, base_url or None, blocks)

    def from_blocks(
        self,
        blocks: List[ContentBlock],
        n: int = 999,
        page_title: str = "Custom Content",
        source_url: Optional[str] = None,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs from pre-extracted ContentBlocks.
        Useful when you've already parsed the page yourself.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=page_title,
                source_url=source_url,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )
            return self._build_mcq_set(all_qs, n, page_title, source_url, blocks)

    def from_url(
        self,
        url: str,
        n: int = 999,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_pdfs: bool = True,
        enrich_images: bool = True,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Fetch the page at *url*, extract content, and generate *n* MCQs.

        Parameters
        ----------
        url : str
            Tutorial page URL.
        n : int
            Number of MCQ questions to generate.
        enrich_pdfs : bool
            If True (default), automatically download and extract any PDF links
            found in the page.
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            title, blocks = self.extractor.from_url(url)

            if enrich_pdfs:
                blocks = self.pdf_extractor.enrich_blocks(blocks)

            if enrich_images and self.method == "twostep":
                blocks = self.image_ocr_extractor.enrich_blocks(blocks)

            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=title,
                source_url=url,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )

            if enrich_images and self.method == "images2mcq":
                img_blocks = [b for b in blocks if b.type == "image" and b.content]
                remaining = n - len(all_qs)
                if img_blocks and remaining > 0:
                    vision_qs = self._vision_mcq(img_blocks, n=remaining, page_title=title)
                    all_qs.extend(vision_qs)

            return self._build_mcq_set(all_qs, n, title, url, blocks)

    def from_image_urls(
        self,
        urls: Union[str, List[str]],
        n: int = 999,
        title: str = "Images",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs directly from one or more image URLs.

        Parameters
        ----------
        urls : str or list of str
            One or more image URLs.
        n : int
            Number of questions.
        title : str
            Title for the MCQSet (default "Images").
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            if isinstance(urls, str):
                urls = [urls]
            blocks = [ContentBlock(type="image", content=u) for u in urls]
            if self.method == "twostep":
                return self._image_twostep(
                    paths=None, urls=urls, blocks=blocks,
                    n=n, title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                )
            all_qs = self._vision_mcq(
                blocks, n=n, page_title=title,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )
            return self._build_mcq_set(all_qs, n, title, urls[0] if urls else None, blocks)

    def from_image_paths(
        self,
        paths: Union[str, List[str]],
        n: int = 999,
        title: str = "Images",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs directly from one or more local image files.

        Parameters
        ----------
        paths : str or list of str
            One or more local image file paths.
        n : int
            Number of questions.
        title : str
            Title for the MCQSet (default "Images").
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            if isinstance(paths, str):
                paths = [paths]
            blocks = []
            for p in paths:
                data = Path(p).read_bytes()
                b64 = _base64.b64encode(data).decode("utf-8")
                data_uri = f"data:image/png;base64,{b64}"
                blocks.append(ContentBlock(type="image", content=data_uri))
            if self.method == "twostep":
                return self._image_twostep(
                    paths=paths, urls=None, blocks=blocks,
                    n=n, title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                )
            all_qs = self._vision_mcq(
                blocks, n=n, page_title=title,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )
            return self._build_mcq_set(all_qs, n, title, paths[0] if paths else None, blocks)

    def from_pdf_urls(
        self,
        urls: Union[str, List[str]],
        n: int = 999,
        pdf_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs from one or more PDF URLs.

        Parameters
        ----------
        urls : str or list of str
            One or more direct PDF URLs.
        n : int
            Number of questions to generate.
        pdf_title : str, optional
            Title for the MCQSet. When multiple PDFs, defaults to "PDFs".
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            if isinstance(urls, str):
                urls = [urls]
            all_blocks: List[ContentBlock] = []
            for url in urls:
                blocks = self.pdf_extractor.from_url(url)
                if not blocks:
                    raise ValueError(f"No text could be extracted from PDF: {url}")
                all_blocks.extend(blocks)
            if not all_blocks:
                raise ValueError("No text could be extracted from any PDF")
            title = pdf_title or (urls[0].split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ").title()
                                  if len(urls) == 1 else "PDFs")
            all_qs, _ = self._generate(
                blocks=all_blocks,
                n=n,
                page_title=title,
                source_url=urls[0],
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )
            return self._build_mcq_set(all_qs, n, title, urls[0], all_blocks)

    def from_pdf_paths(
        self,
        paths: Union[str, List[str]],
        n: int = 999,
        pdf_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs from one or more local PDF files.

        Parameters
        ----------
        paths : str or list of str
            One or more local PDF file paths.
        n : int
            Number of questions to generate.
        pdf_title : str, optional
            Title for the MCQSet. When multiple PDFs, defaults to "PDFs".
        api_key_override : str, optional
            Temporary API key for this call only.
        prompt_log_path : str, optional
            Path to dump prompts. Use "-" or "stdout" for terminal.
        """
        with self._with_overrides(api_key_override, prompt_log_path):
            if isinstance(paths, str):
                paths = [paths]
            all_blocks: List[ContentBlock] = []
            for p in paths:
                blocks = self.pdf_extractor.from_path(p)
                if not blocks:
                    raise ValueError(f"No text could be extracted from PDF: {p}")
                all_blocks.extend(blocks)
            if not all_blocks:
                raise ValueError("No text could be extracted from any PDF")
            title = pdf_title or (Path(paths[0]).stem.replace("-", " ").replace("_", " ").title()
                                  if len(paths) == 1 else "PDFs")
            all_qs, _ = self._generate(
                blocks=all_blocks,
                n=n,
                page_title=title,
                source_url=f"file://{paths[0]}",
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
            )
            return self._build_mcq_set(all_qs, n, title, f"file://{paths[0]}", all_blocks)

    # ── Backward-compat aliases ──────────────────────────────────────────
    from_pdf_url = from_pdf_urls
    from_pdf_path = from_pdf_paths

    def _resolve_instructions(self, per_call: Optional[str]) -> str:
        """
        Merge instance-level and per-call custom instructions.
        Instance-level runs first, per-call appended after.
        Either can be empty string.
        """
        parts = []
        if self.custom_instructions and self.custom_instructions.strip():
            parts.append(self.custom_instructions.strip())
        if per_call and per_call.strip():
            parts.append(per_call.strip())
        return "\n".join(parts)

    # ── Vision → MCQ (images2mcq method) ────────────────────────────────────

    def _vision_mcq(
        self, img_blocks: List[ContentBlock], n: int, page_title: str,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> List[MCQQuestion]:
        """Send images directly to vision model and parse MCQ JSON response."""
        import urllib.request
        import urllib.error

        api_key = self.image_ocr_extractor.vision_api_key
        if not api_key:
            return []

        try:
            import openai
        except ImportError:
            return []

        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

        # Download images
        image_data: List[bytes] = []
        for block in img_blocks:
            try:
                data = _download_image(block.content, timeout=15, max_bytes=10*1024*1024)
                if data:
                    image_data.append(data)
            except Exception:
                continue
        if not image_data:
            return []

        # Build content: text instruction + all images
        instr_parts = [f"Generate {n} MCQ questions from the content in these images."]
        if page_title:
            instr_parts.insert(0, f"PAGE TITLE: {page_title}")
        if difficulty_mix:
            instr_parts.append(f"Difficulty distribution: {difficulty_mix}")
        if focus_topics:
            instr_parts.append(f"Focus especially on these topics: {', '.join(focus_topics)}")
        if custom_instructions and custom_instructions.strip():
            instr_parts.append(
                f"\n--- CUSTOM INSTRUCTIONS (highest priority) ---\n"
                f"{custom_instructions.strip()}\n"
                f"--- END CUSTOM INSTRUCTIONS ---"
            )
        instr_parts.append(
            "Return ONLY a JSON array, no markdown. "
            'Each item: {"question_html": "...", "options": ["A","B","C","D"], '
            '"answers": [0], "difficulty": "easy|medium|hard", '
            '"explaination": "..."}'
        )
        content: list = [{"type": "text", "text": "\n".join(instr_parts)}]
        for img_bytes in image_data:
            b64 = _base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        self._log_prompt("VISION INSTRUCTION",
                          f"Model: {self.image_ocr_extractor.vision_model}\n"
                          f"Images: {len(image_data)}\n"
                          f"Instruction: {content[0]['text']}")

        try:
            resp = client.chat.completions.create(
                model=self.image_ocr_extractor.vision_model,
                messages=[{"role": "user", "content": content}],
                max_tokens=8192,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                print("  [html2mcq] ⚠ vision model returned empty response")
                return []
            return self._parse_response(raw)
        except Exception as e:
            print(f"  [html2mcq] ⚠ vision MCQ failed: {e}")
            return []

    def _image_twostep(
        self,
        paths: Optional[List[str]],
        urls: Optional[List[str]],
        blocks: List[ContentBlock],
        n: int,
        title: str,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """OCR images to text, optionally save to file, then generate MCQs from text."""
        image_bytes_list: List[bytes] = []
        for block in blocks:
            try:
                data = _download_image(block.content, timeout=15, max_bytes=10*1024*1024)
                if data:
                    image_bytes_list.append(data)
            except Exception:
                continue
        if not image_bytes_list:
            raise ValueError("No image data could be downloaded for two-step processing")

        ocr_text = self.image_ocr_extractor.ocr_image_bytes(image_bytes_list)

        if self.save_ocr_path:
            Path(self.save_ocr_path).write_text(ocr_text, encoding="utf-8")
            print(f"  [html2mcq] OCR text saved to: {self.save_ocr_path}")

        text_blocks = [ContentBlock(type="text", content=ocr_text)]
        source = (paths[0] if paths else urls[0]) if (paths or urls) else None
        all_qs, _ = self._generate(
            blocks=text_blocks,
            n=n,
            page_title=title,
            source_url=source,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )
        return self._build_mcq_set(all_qs, n, title, source, blocks)

    def _build_mcq_set(
        self,
        all_questions: List[MCQQuestion],
        n: int,
        page_title: str,
        source_url: Optional[str],
        blocks: List[ContentBlock],
    ) -> MCQSet:
        """Build final MCQSet from question list, trimming to exactly n."""
        all_questions = all_questions[:n]
        summary = self._build_summary(blocks)
        exam_time = max(1, len(all_questions) * 2)
        return MCQSet(
            source_url=source_url,
            page_title=page_title,
            questions=all_questions,
            total_questions=len(all_questions),
            content_summary=summary,
            total_exam_time=exam_time,
            metadata={
                "provider": self.provider,
                "mcq_model": getattr(self.backend, "mcq_model", "unknown"),
                "method": self.method,
                "requested_n": n,
                "content_blocks": len(blocks),
                "content_types": list({b.type for b in blocks}),
            },
        )

    # ── Internal generation pipeline ─────────────────────────────────────────

    @staticmethod
    def _resolve_mcq_model_list(mcq_model_list: Optional[List] = None) -> List[dict]:
        """Resolve MCQ model list: env var > parameter > sensible default.

        Returns list of dicts: {"model": str, "max_tokens": int}.
        Plain-string entries are wrapped with a default max_tokens.
        """
        env = os.environ.get("HTML2MCQ_MCQ_MODELS", "").strip()
        if env:
            raw = [m.strip() for m in env.split(",") if m.strip()]
        elif mcq_model_list:
            raw = list(mcq_model_list)
        else:
            raw = [
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "openai/gpt-oss-120b:free",
                "google/gemma-4-31b-it:free",
            ]
        # Known max_output tokens per model (from OpenRouter API)
        # Models ordered by speed (fastest first) on free tier
        _MAX_TOKENS = {
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": 65536,
            "openai/gpt-oss-120b:free": 131072,
            "openai/gpt-oss-20b:free": 131072,
            "google/gemma-4-31b-it:free": 32768,
            "google/gemma-4-26b-a4b-it:free": 32768,
            "nvidia/nemotron-3-super-120b-a12b:free": 65536,
            "nvidia/nemotron-3-ultra-550b-a55b:free": 65536,
        }
        result = []
        for entry in raw:
            if isinstance(entry, dict):
                result.append(entry)
            else:
                result.append({
                    "model": entry,
                    "max_tokens": _MAX_TOKENS.get(entry, 16384),
                })
        return result

    def _generate(
        self,
        blocks: List[ContentBlock],
        n: int,
        page_title: str,
        source_url: Optional[str],
        difficulty_mix: Optional[str],
        focus_topics: Optional[List[str]],
        custom_instructions: Optional[str] = None,
    ) -> Tuple[List[MCQQuestion], str]:
        if not blocks:
            return [], ""

        all_questions: List[MCQQuestion] = []
        system_prompt = build_system_prompt()
        remaining = n

        # ── Resolve MCQ model (supports auto mode) ──
        if self.mcq_model == "auto":
            model_list = self._resolve_mcq_model_list(self.mcq_model_list)
            for entry in model_list:
                model_name = entry["model"]
                model_tokens = entry["max_tokens"]
                self.backend.mcq_model = model_name
                # Use model's max_tokens to send all questions in one call
                est_tokens_per_q = 500  # output tokens per MCQ (generous)
                requested_output = n * est_tokens_per_q + 200
                batch_max_tokens = min(model_tokens, requested_output)
                max_per_call = max(1, batch_max_tokens // est_tokens_per_q)
                batch_n = min(remaining, max_per_call)
                user_prompt = build_user_prompt(
                    blocks=blocks,
                    n=batch_n,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    page_title=page_title,
                    custom_instructions=self._resolve_instructions(custom_instructions),
                )
                self._log_prompt("SYSTEM", system_prompt)
                self._log_prompt("USER", user_prompt)
                try:
                    raw = self.backend.complete(system_prompt, user_prompt, batch_max_tokens)
                    batch = self._parse_response(raw)
                except Exception as e:
                    print(f"  [html2mcq] ⚠ MCQ model '{model_name}' failed: {e}")
                    continue
                if batch:
                    all_questions.extend(batch)
                    remaining -= len(batch)
                    print(f"  [html2mcq] OK MCQ model '{model_name}' selected "
                          f"({len(batch)} questions, {batch_max_tokens} max_tokens)")
                    break
            else:
                raise RuntimeError(
                    f"All MCQ models in list failed: {[e['model'] for e in model_list]}"
                )
            # Auto mode already sent all questions in one batch
            all_questions = all_questions[:n]
            summary = self._build_summary(blocks)
            return all_questions, summary

        while remaining > 0:
            batch_n = min(remaining, self.batch_size)
            user_prompt = build_user_prompt(
                blocks=blocks,
                n=batch_n,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                page_title=page_title,
                custom_instructions=self._resolve_instructions(custom_instructions),
            )
            self._log_prompt("SYSTEM", system_prompt)
            self._log_prompt("USER", user_prompt)
            raw = self.backend.complete(system_prompt, user_prompt, self.max_tokens)
            batch_questions = self._parse_response(raw)
            all_questions.extend(batch_questions)
            remaining -= len(batch_questions)

            if len(batch_questions) == 0:
                break
            if remaining > 0 and len(batch_questions) < batch_n:
                break

        all_questions = all_questions[:n]
        summary = self._build_summary(blocks)
        return all_questions, summary

    def _parse_response(self, raw: str) -> List[MCQQuestion]:
        """Parse AI JSON response into MCQQuestion objects."""
        # Strip any accidental markdown fences
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"AI returned non-JSON response:\n{raw[:500]}")

        questions = []
        for item in data:
            if item is None:
                continue
            try:
                # Support both old single int and new list format for answers
                raw_answers = item.get("answers", item.get("correct_answer", 0))
                if isinstance(raw_answers, int):
                    answers = [raw_answers]
                else:
                    answers = [int(a) for a in raw_answers]

                options = item.get("options", [])
                if not isinstance(options, list):
                    continue
                if not options:
                    continue

                multi = item.get("multi", len(answers) > 1)
                marks = float(item.get("marks", 1))
                negative_marks = float(item.get("negative_marks", 0.0 if multi else 0.25))

                q = MCQQuestion(
                    question_html=item.get("question_html", item.get("question", "")),
                    options=options[:4],
                    answers=answers,
                    multi=bool(multi),
                    marks=marks,
                    negative_marks=negative_marks,
                    difficulty=item.get("difficulty", "medium").lower(),
                    explaination=item.get("explaination", item.get("explanation", "")),
                )
                questions.append(q)
            except (KeyError, TypeError, ValueError):
                continue  # Skip malformed items
        return questions

    @staticmethod
    def _build_summary(blocks: List[ContentBlock]) -> str:
        counts = {}
        for b in blocks:
            counts[b.type] = counts.get(b.type, 0) + 1
        parts = [f"{v} {k}{'s' if v>1 else ''}" for k, v in sorted(counts.items())]
        return "Content: " + ", ".join(parts)


