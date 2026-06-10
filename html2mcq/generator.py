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
import random

def _retry_with_backoff(func, max_retries=3, initial_delay=1, factor=2, jitter=0.1):
    """Retries a function with exponential backoff.
    Handles typical transient errors like 429 (Rate Limit) or 503 (Overloaded).
    """
    delay = initial_delay
    last_err = None
    for i in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            # 402 is credits, 429 is rate limit, 503 is overloaded
            is_transient = any(kw in msg for kw in ("402", "429", "rate limit", "quota", "503", "overloaded", "timeout", "credits"))
            if not is_transient or i == max_retries:
                raise e
            
            # Wait with jitter
            sleep_time = delay * (1 + jitter * random.random())
            print(f"  [html2mcq] ⚠ Rate limited or overloaded. Retrying in {sleep_time:.1f}s... (Attempt {i+1}/{max_retries})")
            time.sleep(sleep_time)
            delay *= factor
    raise last_err

from .extractor import ContentExtractor
from .models import ContentBlock, MCQQuestion, MCQSet
from .prompts import build_system_prompt, build_user_prompt
from .pdf import PDFExtractor, _render_pdf_pages_to_pngs, _render_specific_pages, _parse_page_range, _fetch_bytes
from .image_ocr import ImageOCRExtractor, _download_image


def _parse_operator_model(model_str: str, current_provider: str, available_keys: Optional[dict] = None) -> Optional[Tuple[str, str]]:
    if not model_str:
        return None
    if model_str.startswith("("):
        match = re.match(r"^\(([^)]+)\)/(.*)$", model_str)
        if match:
            provider_prefix, actual_model = match.groups()
            p_low = provider_prefix.lower()
            if current_provider == "auto":
                if available_keys and p_low in available_keys:
                    return (p_low, actual_model)
                return None
            if p_low == current_provider.lower():
                return (p_low, actual_model)
            else:
                return None
    
    if current_provider == "auto":
        if available_keys:
            for preferred in ["openrouter", "openai", "gemini"]:
                if preferred in available_keys:
                    return (preferred, model_str)
            return (next(iter(available_keys)), model_str)
        return ("openrouter", model_str)

    return (current_provider, model_str)


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

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
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

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
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

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
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

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _GeminiBackend:
    """Uses Google's Gemini API via its OpenAI-compatible endpoint."""

    DEFAULT_MODEL = "gemini-2.5-flash-lite"

    def __init__(self, api_key: str, mcq_model: str):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _DeepSeekBackend:
    """Uses DeepSeek's API via its OpenAI-compatible endpoint."""

    DEFAULT_MODEL = "deepseek-chat"

    def __init__(self, api_key: str, mcq_model: str):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _GroqBackend:
    """Uses Groq's API via its OpenAI-compatible endpoint."""

    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str, mcq_model: str):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class _ManualAIBackend:
    """Uses a manual custom API via its OpenAI-compatible endpoint."""

    DEFAULT_MODEL = "custom-model"

    def __init__(self, api_key: str, mcq_model: str, manualai_base_url: str = ""):
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "Missing 'openai' package. Install it with: pip install openai\n"
                f"  Original error: {e}"
            ) from e
        base_url = manualai_base_url or os.environ.get("MANUALAI_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(
                "For 'manualai' provider, you must set the MANUALAI_BASE_URL environment variable "
                "or pass manualai_base_url pointing to your OpenAI-compatible endpoint."
            )
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.mcq_model = mcq_model or self.DEFAULT_MODEL

    def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        return _retry_with_backoff(lambda: self._complete_raw(system, user, max_tokens))

    def _complete_raw(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
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
    if provider == "gemini":
        return _GeminiBackend(api_key, mcq_model)
    if provider == "deepseek":
        return _DeepSeekBackend(api_key, mcq_model)
    if provider == "groq":
        return _GroqBackend(api_key, mcq_model)
    if provider == "manualai":
        return _ManualAIBackend(api_key, mcq_model, **kwargs)
    if provider == "ollama":
        return _OllamaBackend(api_key, mcq_model, **kwargs)
    if provider == "auto":
        return None
    raise ValueError(f"Unknown provider '{provider}'. Choose: anthropic | openai | openrouter | gemini | deepseek | groq | manualai | ollama | auto")


class _OverrideContext:
    """Temporarily overrides backend, prompt_log_path, ocr_model, and/or mcq_model on MCQGenerator."""
    def __init__(self, gen, api_key_override, prompt_log_path,
                 ocr_model=None, mcq_model=None):
        self.gen = gen
        self.api_key = api_key_override
        self.log_path = prompt_log_path
        self.ocr_model = ocr_model
        self.mcq_model = mcq_model
        self._saved = {}

    def __enter__(self):
        if self.api_key is not None:
            self._saved['backend'] = self.gen.backend
            self.gen.backend = _make_backend(
                self.gen.provider, self.api_key, self.gen.mcq_model,
            )
        if self.log_path is not None:
            self._saved['prompt_log_path'] = getattr(self.gen, "prompt_log_path", None)
            self.gen.prompt_log_path = self.log_path
        if self.ocr_model is not None:
            ocr_val = self.ocr_model.lower()
            if hasattr(self.gen, 'image_ocr_extractor'):
                self._saved['image_ocr_extractor.backend'] = self.gen.image_ocr_extractor.backend
                self.gen.image_ocr_extractor.backend = ocr_val
            if hasattr(self.gen, 'pdf_extractor'):
                self._saved['pdf_extractor.scanned_backend'] = self.gen.pdf_extractor.scanned_backend
                self.gen.pdf_extractor.scanned_backend = ocr_val
        # ── Vision Model Override ──
        # Determine which model to use for vision tasks (OCR / Direct Vision MCQ)
        # Priority: ocr_model (if AI) > mcq_model (if not auto)
        
        # Resolve prefixes for overrides
        ovr_ocr = _parse_operator_model(self.ocr_model, self.gen.provider)
        ovr_mcq = _parse_operator_model(self.mcq_model, self.gen.provider)

        target_vis_model = None
        if ovr_ocr is not None and ovr_ocr != "pytesseract" and ovr_ocr != "":
            target_vis_model = ovr_ocr
        elif ovr_mcq is not None and ovr_mcq not in ("", "priority_list"):
            target_vis_model = ovr_mcq

        if target_vis_model is not None:
            _DEFAULT_VISION = "google/gemini-2.5-flash-lite"
            _vis_model = target_vis_model if target_vis_model not in ("", "priority_list") else _DEFAULT_VISION
            
            if hasattr(self.gen, 'image_ocr_extractor'):
                self._saved['image_ocr_extractor.vision_model'] = self.gen.image_ocr_extractor.vision_model
                self.gen.image_ocr_extractor.vision_model = _vis_model
            if hasattr(self.gen, 'pdf_extractor') and hasattr(self.gen.pdf_extractor, 'vision_model'):
                self._saved['pdf_extractor.vision_model'] = self.gen.pdf_extractor.vision_model
                self.gen.pdf_extractor.vision_model = _vis_model
            if hasattr(self.gen, '_vision_model'):
                self._saved['_vision_model'] = self.gen._vision_model
                self.gen._vision_model = _vis_model

        # ── Backend Override ──
        if ovr_mcq is not None:
            effective_mcq_model = ovr_mcq
            # Implement method-specific fallbacks for overrides
            if not effective_mcq_model:
                if self.gen.method in ("twostep", "tesseract"):
                    if ovr_ocr:
                        effective_mcq_model = ovr_ocr
                    else:
                        effective_mcq_model = getattr(self.gen, "mcq_model", "")
            
            _key = getattr(self.gen, '_resolved_api_key', None) or "ollama"
            self._saved['backend'] = self.gen.backend
            self.gen.backend = _make_backend(self.gen.provider, _key, effective_mcq_model)

        return self

    def __exit__(self, *args):
        if 'backend' in self._saved:
            self.gen.backend = self._saved['backend']
        if 'prompt_log_path' in self._saved:
            self.gen.prompt_log_path = self._saved['prompt_log_path']
        if 'image_ocr_extractor.backend' in self._saved:
            self.gen.image_ocr_extractor.backend = self._saved['image_ocr_extractor.backend']
        if 'pdf_extractor.scanned_backend' in self._saved:
            self.gen.pdf_extractor.scanned_backend = self._saved['pdf_extractor.scanned_backend']
        if 'image_ocr_extractor.vision_model' in self._saved:
            self.gen.image_ocr_extractor.vision_model = self._saved['image_ocr_extractor.vision_model']
        if 'pdf_extractor.vision_model' in self._saved:
            self.gen.pdf_extractor.vision_model = self._saved['pdf_extractor.vision_model']
        if '_vision_model' in self._saved:
            self.gen._vision_model = self._saved['_vision_model']


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
        or "priority_list" to try mcq_model_list until one succeeds.
        Also controls the vision model used by ``from_image_paths`` /
        ``from_image_urls``. Defaults to the provider's default model when empty.
    mcq_model_list : list of str, optional
        Priority-ordered model list for mcq_model="priority_list".
        Runtime-reloadable via HTML2MCQ_MCQ_MODELS env var (comma-separated).

    --- OCR / Vision ---
    ocr_model : str
        OCR backend for extracting text from images in HTML pages.
        "pytesseract" (default, needs tesseract binary) | "priority_list" (tries priority list)
        | any OpenRouter model ID (e.g. "google/gemini-2.5-flash-lite").
        Does *not* affect ``from_image_paths`` / ``from_image_urls`` — those
        use ``mcq_model`` for the vision model.
    ocr_model_list : list of str, optional
        Priority-ordered model list for ocr_model="priority_list".
        Allows defining a custom fallback order for OCR tasks.
    ocr_models : list of str, optional
        Priority-ordered model list for ocr_model="priority_list".
        Backward compatibility alias for ocr_model_list.
    ocr_fallback : bool
        If True (default), fall back to Tesseract OCR when vision API fails.
    ocr_lang : str
        Tesseract language code (default "eng").

    --- Generation Options ---
    method : str
        Processing method (MANDATORY):
        - ``"auto"`` — intelligently choose the best method
        - ``"onestep"`` — send images directly to vision model for MCQ generation
        - ``"twostep"`` — use vision model as OCR engine, then generate MCQs from text
        - ``"tesseract"`` — use local Tesseract for OCR, then generate MCQs from text
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
        "gemini": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
        "manualai": "MANUALAI_API_KEY",
        "ollama": "",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "openrouter",
        operator: Optional[str] = None,
        mcq_model: str = "",
        mcq_model_list: Optional[List[str]] = None,
        ocr_model: str = "",
        ocr_model_list: Optional[List[str]] = None,
        ocr_models: Optional[List[str]] = None,
        ocr_fallback: bool = True,
        ocr_lang: str = "eng",
        method: str = "",
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
        # ── Resolve Provider / Operator ──────────────────────────────────
        self.provider = (operator or provider).lower()
        
        # ── Scan for valid operators (API keys) ──────────────────────────
        self.available_keys = {}
        for p, env_var in self.ENV_KEYS.items():
            if env_var:
                val = os.environ.get(env_var, "").strip()
                if val:
                    self.available_keys[p] = val
            elif p == "ollama":
                self.available_keys[p] = "ollama"
        
        if self.provider == "auto":
            if ocr_model != "priority_list" and mcq_model != "priority_list":
                raise ValueError(
                    "Logical Error: 'operator=\"auto\"' is only allowed when "
                    "'ocr_model=\"priority_list\"' or 'mcq_model=\"priority_list\"' is used."
                )
            if not self.available_keys:
                raise ValueError(
                    "Logical Error: 'operator=\"auto\"' specified, but no valid API keys "
                    "found in environment variables."
                )

        # ── Resolve operator-aware single models ─────────────────────────
        # If in auto mode, we don't resolve prefixes yet, they are handled in loops
        if self.provider != "auto":
            res_ocr = _parse_operator_model(ocr_model, self.provider)
            ocr_model = res_ocr[1] if res_ocr else ""
            
            res_mcq = _parse_operator_model(mcq_model, self.provider)
            mcq_model = res_mcq[1] if res_mcq else ""
        
        if ocr_model and ocr_model.lower() in ("pytesseract", "tesseract"):
            raise ValueError(
                "Logical Error: 'pytesseract' is an internal engine, not an AI model name. "
                "Do not pass it to 'ocr_model'. For local OCR, use 'method=\"tesseract\"'."
            )
        if mcq_model and mcq_model.lower() in ("pytesseract", "tesseract"):
            raise ValueError(
                "Logical Error: 'pytesseract' is not an AI model and cannot generate MCQs. "
                "Please provide a valid AI model name for 'mcq_model'."
            )

        self.mcq_model = mcq_model
        self.mcq_model_list = mcq_model_list
        self.ocr_models = ocr_model_list or ocr_models
        if not method:
            raise ValueError(
                "Logical Error: The 'method' parameter is mandatory. "
                "Choose: auto | twostep | tesseract | onestep"
            )
        self.method = method.lower()
        if self.method not in ("auto", "twostep", "tesseract", "onestep"):
            raise ValueError(f"Unknown method '{method}'. Choose: auto | twostep | tesseract | onestep")
        
        # ── Resolve 'auto' method ────────────────────────────────────────
        if self.method == "auto":
            if not mcq_model and not ocr_model:
                raise ValueError(
                    "Logical Error: As both 'mcq_model' and 'ocr_model' are missing, "
                    "not able to resolve 'auto' method. Please provide at least one AI model "
                    "via '--mcq-model' or '--ocr-model'."
                )
            # If ocr_model (the reader) is missing, we must use local OCR
            if not ocr_model and mcq_model:
                self.method = "tesseract"
        
        # ── Enforce ocr_model rules and handle method splitting ──────────
        if self.method == "tesseract":
            orig_ocr_model = ocr_model
            # Extraction backend is ALWAYS pytesseract
            ocr_model = "pytesseract"
            
            # Validation: at least one AI model must be provided for MCQ generation
            if not self.mcq_model and not orig_ocr_model:
                 raise ValueError(
                     "Logical Error: For 'tesseract' method, you must provide an AI model for MCQ generation "
                     "via either 'mcq_model' or 'ocr_model' (e.g. --ocr-model gemini-2.0-flash)."
                 )
            # Fallback: if mcq_model missing, use the user's ocr_model value
            if not self.mcq_model:
                self.mcq_model = orig_ocr_model

        elif self.method == "twostep":
            if not ocr_model:
                raise ValueError(
                    "Logical Error: For 'twostep' method, 'ocr_model' is mandatory and must be "
                    "set to a vision-capable AI model."
                )
            # Fallback: if mcq_model missing, use ocr_model
            if not self.mcq_model:
                self.mcq_model = ocr_model

        elif self.method == "onestep":
            if not ocr_model:
                raise ValueError(
                    "Logical Error: For 'onestep' method, the 'ocr_model' parameter is mandatory "
                    "and must be set to a vision-capable AI model (e.g. 'google/gemini-2.5-flash')."
                )
            # Fallback: if mcq_model missing, use ocr_model
            if not self.mcq_model:
                self.mcq_model = ocr_model

        if self.provider == "ollama":
            _key = "ollama"
            if self.mcq_model in ("", "priority_list"):
                self.mcq_model = _OllamaBackend.DEFAULT_MODEL
        elif self.provider == "auto":
            # Keys will be resolved from available_keys during loops
            _key = "auto"
        else:
            _key = api_key or os.environ.get(self.ENV_KEYS.get(self.provider, ""), "")
            if not _key:
                raise ValueError(
                    f"No API key supplied. Pass api_key= or set "
                    f"{self.ENV_KEYS.get(self.provider, 'YOUR_API_KEY')} env var."
                )
        
        # ── Final mcq_model Fallbacks ────────────────────────────────────
        if not self.mcq_model or self.mcq_model == "priority_list":
            if self.method in ("twostep", "tesseract") and ocr_model:
                # We only fall back if ocr_model is an AI model (not Tesseract)
                if ocr_model != "pytesseract":
                    self.mcq_model = ocr_model

        self._resolved_api_key = _key
        self.backend = _make_backend(self.provider, _key, self.mcq_model, **backend_kwargs)
        if api_key_override:
            self._resolved_api_key = api_key_override
            self.backend = _make_backend(self.provider, api_key_override, self.mcq_model, **backend_kwargs)
        self.batch_size = max(1, batch_size)
        self.max_tokens = max_tokens
        self.timeout = backend_kwargs.get("timeout", 30)
        self.extractor = ContentExtractor(**(extractor_kwargs or {}))

        # ── Derive downstream params ─────────────────────────────────────
        image_ocr_backend = ocr_model
        pdf_scanned_backend = ocr_model
        
        # For vision-based tasks (onestep, twostep OCR, scanned PDFs),
        # determine the primary vision model.
        # PRIORITY: ocr_model (if AI) > mcq_model (if not auto) > default
        _DEFAULT_VISION = "google/gemini-2.5-flash-lite"
        
        if ocr_model and ocr_model not in ("pytesseract", "priority_list"):
            _vision_model = ocr_model
        elif self.mcq_model and self.mcq_model not in ("priority_list", ""):
            _vision_model = self.mcq_model
        else:
            _vision_model = _DEFAULT_VISION
        _vision_free_model = "google/gemma-3-12b-it"

        # Image OCR / vision (for method="twostep")
        self.image_ocr_extractor = ImageOCRExtractor(
            backend=image_ocr_backend,
            lang=ocr_lang,
            vision_provider=self.provider,
            vision_model=_vision_model,
            vision_free_model=_vision_free_model,
            vision_api_key=_key,
            ocr_fallback=ocr_fallback,
            ocr_models=ocr_models,
            available_keys=self.available_keys,
            max_tokens=self.max_tokens,
        )

        # PDF (text + scanned)
        self.pdf_extractor = PDFExtractor(
            backend=pdf_backend,
            chunk_size=pdf_chunk_size,
            scanned_backend=pdf_scanned_backend,
            scanned_max_pages=pdf_scanned_max_pages,
            vision_provider=self.provider,
            vision_model=_vision_model,
            vision_free_model=_vision_free_model,
            vision_api_key=_key,
            ocr_fallback=ocr_fallback,
            ocr_lang=ocr_lang,
            ocr_models=ocr_models,
            available_keys=self.available_keys,
            max_tokens=self.max_tokens,
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
                        prompt_log_path: Optional[str] = None,
                        ocr_model: Optional[str] = None,
                        mcq_model: Optional[str] = None):
        return _OverrideContext(self, api_key_override, prompt_log_path,
                                ocr_model=ocr_model, mcq_model=mcq_model)




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
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        """Generate MCQs from a raw HTML string."""
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            use_vision = self.method == "onestep"
            m_display = "onestep (Hybrid)" if use_vision else "twostep"
            print(f"  [html2mcq] Method: {m_display} (Text/HTML detected)")
            
            title, blocks = self.extractor.from_html(html, base_url=base_url)
            if enrich_pdfs:
                if use_vision:
                    # Hybrid path: render PDF pages to images for direct vision prompt
                    blocks = self.pdf_extractor.render_blocks_to_images(blocks)
                else:
                    blocks = self.pdf_extractor.enrich_blocks(blocks)

            if enrich_images:
                if use_vision:
                    # Hybrid path: download images for direct vision prompt
                    blocks = self.image_ocr_extractor.download_images(blocks)
                else:
                    # Standard path: OCR images into text
                    blocks = self.image_ocr_extractor.enrich_blocks(blocks, replace=True)

            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=title,
                source_url=base_url or None,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
                show_progress=show_progress,
            )

            return self._build_mcq_set(all_qs, n, title, base_url or None, blocks)

    from_html_string = from_html

    def from_html_path(
        self,
        path: str,
        n: int = 999,
        base_url: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_pdfs: bool = True,
        enrich_images: bool = True,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        """Read a local HTML file and generate MCQs from it."""
        html = Path(path).read_text(encoding="utf-8")
        return self.from_html(
            html, n=n, base_url=base_url or path,
            difficulty_mix=difficulty_mix, focus_topics=focus_topics,
            enrich_pdfs=enrich_pdfs, enrich_images=enrich_images,
            custom_instructions=custom_instructions,
            api_key_override=api_key_override, prompt_log_path=prompt_log_path,
            ocr_model=ocr_model, mcq_model=mcq_model,
            show_progress=show_progress,
        )

    def from_html_folder(
        self,
        folder: str,
        n: int = 999,
        base_url: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_pdfs: bool = True,
        enrich_images: bool = True,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        """Scan a folder for .html files and generate MCQs from all of them."""
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise ValueError(f"Folder not found: {folder}")
        html_files = sorted(f for f in folder_path.iterdir() if f.suffix.lower() in (".html", ".htm"))
        if not html_files:
            raise ValueError(f"No HTML files found in: {folder}")
        combined = []
        for f in html_files:
            combined.append(f"<!-- Source: {f.name} -->\n{f.read_text(encoding='utf-8')}")
        return self.from_html(
            "\n\n".join(combined), n=n, base_url=base_url or folder,
            difficulty_mix=difficulty_mix, focus_topics=focus_topics,
            enrich_pdfs=enrich_pdfs, enrich_images=enrich_images,
            custom_instructions=custom_instructions,
            api_key_override=api_key_override, prompt_log_path=prompt_log_path,
            ocr_model=ocr_model, mcq_model=mcq_model,
            show_progress=show_progress,
        )

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
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=page_title,
                source_url=source_url,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
                show_progress=show_progress,
            )
            return self._build_mcq_set(all_qs, n, page_title, source_url, blocks)

    def from_url(
        self,
        url: str,
        n: int = 999,
        page_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_pdfs: bool = True,
        enrich_images: bool = True,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            use_vision = self.method == "onestep"
            m_display = "onestep (Hybrid)" if use_vision else "twostep"
            print(f"  [html2mcq] Method: {m_display} (Text/HTML detected)")
            
            title, blocks = self.extractor.from_url(url)
            if page_title:
                title = page_title

            if enrich_pdfs:
                if use_vision:
                    # Hybrid path: render PDF pages to images for direct vision prompt
                    blocks = self.pdf_extractor.render_blocks_to_images(blocks)
                else:
                    blocks = self.pdf_extractor.enrich_blocks(blocks)

            if enrich_images:
                if use_vision:
                    # Hybrid path: download images for direct vision prompt
                    blocks = self.image_ocr_extractor.download_images(blocks)
                else:
                    # Standard path: OCR images into text
                    blocks = self.image_ocr_extractor.enrich_blocks(blocks, replace=True)

            all_qs, _ = self._generate(
                blocks=blocks,
                n=n,
                page_title=title,
                source_url=url,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
                show_progress=show_progress,
            )

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
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            if isinstance(urls, str):
                urls = [urls]
            blocks = [ContentBlock(type="image", content=u) for u in urls]
            
            use_vision = self.method in ("priority_list", "onestep")
            if use_vision:
                print(f"  [html2mcq] Method: onestep (Pure image detected)")
                all_qs = self._vision_mcq(
                    blocks, n=n, page_title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                )
                return self._build_mcq_set(all_qs, n, title, urls[0] if urls else None, blocks)
            else:
                m_name = "tesseract" if self.method == "tesseract" else "twostep"
                print(f"  [html2mcq] Method: {m_name} (Forced)")
                return self._image_twostep(
                    paths=None, urls=urls, blocks=blocks,
                    n=n, title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                    show_progress=show_progress,
                )

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
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            if isinstance(paths, str):
                paths = [paths]
            blocks = []
            for p in paths:
                data = Path(p).read_bytes()
                b64 = _base64.b64encode(data).decode("utf-8")
                data_uri = f"data:image/png;base64,{b64}"
                blocks.append(ContentBlock(type="image", content=data_uri))
            
            use_vision = self.method in ("priority_list", "onestep")
            if use_vision:
                print(f"  [html2mcq] Method: onestep (Pure image detected)")
                all_qs = self._vision_mcq(
                    blocks, n=n, page_title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                )
                return self._build_mcq_set(all_qs, n, title, paths[0] if paths else None, blocks)
            else:
                m_name = "tesseract" if self.method == "tesseract" else "twostep"
                print(f"  [html2mcq] Method: {m_name} (Forced)")
                return self._image_twostep(
                    paths=paths, urls=None, blocks=blocks,
                    n=n, title=title,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    custom_instructions=custom_instructions,
                    show_progress=show_progress,
                )

    def from_pdf_urls(
        self,
        urls: Union[str, List[str]],
        n: int = 999,
        pdf_title: str = "",
        pages: Optional[str] = None,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            if isinstance(urls, str):
                urls = [urls]
            page_nums = _parse_page_range(pages)
            title = pdf_title or (urls[0].split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ").title()
                                  if len(urls) == 1 else "PDFs")
            all_bytes = []
            for url in urls:
                all_bytes.append(_fetch_bytes(url, timeout=self.timeout, user_agent=self.extractor.user_agent))
            
            # Detect if all are scanned
            is_all_scanned = all(self.pdf_extractor.detect_scan_type(b) == "scanned" for b in all_bytes)
            
            use_vision = (is_all_scanned and self.method == "auto") or (self.method == "onestep")
            if use_vision:
                desc = "Scanned PDF" if is_all_scanned else "Forced vision"
                print(f"  [html2mcq] Method: onestep ({desc} detected)")
                
                # Check for native PDF support
                if self.provider in ("gemini", "openrouter") and len(all_bytes) == 1:
                    all_qs = self._vision_mcq_pdf(n=n, page_title=title,
                                                  difficulty_mix=difficulty_mix,
                                                  focus_topics=focus_topics,
                                                  custom_instructions=custom_instructions,
                                                  pdf_bytes=all_bytes[0])
                    return self._build_mcq_set(all_qs, n, title, urls[0], [])

                all_pngs: List[bytes] = []
                for pdf_bytes in all_bytes:
                    if page_nums is not None:
                        rendered = _render_specific_pages(pdf_bytes, page_nums, max_pages=self.pdf_extractor.scanned_max_pages)
                    else:
                        rendered = _render_pdf_pages_to_pngs(pdf_bytes, max_pages=self.pdf_extractor.scanned_max_pages)
                    all_pngs.extend(rendered)
                if not all_pngs:
                    raise ValueError("No pages could be rendered from PDF(s)")
                all_qs = self._vision_mcq_pdf(all_pngs, n=n, page_title=title,
                                              difficulty_mix=difficulty_mix,
                                              focus_topics=focus_topics,
                                              custom_instructions=custom_instructions)
                return self._build_mcq_set(all_qs, n, title, urls[0], [])

            m_name = "tesseract" if self.method == "tesseract" else "twostep"
            desc = "Text PDF" if not is_all_scanned else f"Forced {m_name.upper()}"
            print(f"  [html2mcq] Method: {m_name} ({desc} detected)")
            all_blocks: List[ContentBlock] = []
            for i, pdf_bytes in enumerate(all_bytes):
                blocks = self.pdf_extractor.from_bytes(pdf_bytes, source_url=urls[i], page_numbers=page_nums)
                if not blocks:
                    raise ValueError(f"No text could be extracted from PDF: {urls[i]}")
                all_blocks.extend(blocks)
            if not all_blocks:
                raise ValueError("No text could be extracted from any PDF")
            save_ocr_path = getattr(self, 'save_ocr_path', None)
            if save_ocr_path:
                ocr_text = "\n".join(b.content for b in all_blocks if b.content)
                Path(save_ocr_path).write_text(ocr_text, encoding="utf-8")
                print(f"  [html2mcq] OCR text saved to: {save_ocr_path}")
            all_qs, _ = self._generate(
                blocks=all_blocks,
                n=n,
                page_title=title,
                source_url=urls[0],
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
                show_progress=show_progress,
            )
            return self._build_mcq_set(all_qs, n, title, urls[0], all_blocks)

    def from_pdf_paths(
        self,
        paths: Union[str, List[str]],
        n: int = 999,
        pdf_title: str = "",
        pages: Optional[str] = None,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        api_key_override: Optional[str] = None,
        prompt_log_path: Optional[str] = None,
        ocr_model: Optional[str] = None,
        mcq_model: Optional[str] = None,
        show_progress: bool = False,
    ) -> MCQSet:
        with self._with_overrides(api_key_override, prompt_log_path,
                                  ocr_model=ocr_model, mcq_model=mcq_model):
            if isinstance(paths, str):
                paths = [paths]
            page_nums = _parse_page_range(pages)
            title = pdf_title or (Path(paths[0]).stem.replace("-", " ").replace("_", " ").title()
                                  if len(paths) == 1 else "PDFs")
            # Detect if all are scanned
            is_all_scanned = all(self.pdf_extractor.detect_scan_type_from_path(p) == "scanned" for p in paths)

            use_vision = (is_all_scanned and self.method == "auto") or (self.method == "onestep")
            if use_vision:
                desc = "Scanned PDF" if is_all_scanned else "Forced vision"
                print(f"  [html2mcq] Method: onestep ({desc} detected)")
                
                # Check for native PDF support
                if self.provider in ("gemini", "openrouter") and len(paths) == 1:
                    pdf_bytes = Path(paths[0]).read_bytes()
                    all_qs = self._vision_mcq_pdf(n=n, page_title=title,
                                                  difficulty_mix=difficulty_mix,
                                                  focus_topics=focus_topics,
                                                  custom_instructions=custom_instructions,
                                                  pdf_bytes=pdf_bytes)
                    return self._build_mcq_set(all_qs, n, title, f"file://{paths[0]}", [])

                all_pngs: List[bytes] = []
                for p in paths:
                    pdf_bytes = Path(p).read_bytes()
                    if page_nums is not None:
                        rendered = _render_specific_pages(pdf_bytes, page_nums, max_pages=self.pdf_extractor.scanned_max_pages)
                    else:
                        rendered = _render_pdf_pages_to_pngs(pdf_bytes, max_pages=self.pdf_extractor.scanned_max_pages)
                    all_pngs.extend(rendered)
                if not all_pngs:
                    raise ValueError("No pages could be rendered from PDF(s)")
                all_qs = self._vision_mcq_pdf(all_pngs, n=n, page_title=title,
                                              difficulty_mix=difficulty_mix,
                                              focus_topics=focus_topics,
                                              custom_instructions=custom_instructions)
                return self._build_mcq_set(all_qs, n, title, f"file://{paths[0]}", [])

            m_name = "tesseract" if self.method == "tesseract" else "twostep"
            desc = "Text PDF" if not is_all_scanned else f"Forced {m_name.upper()}"
            print(f"  [html2mcq] Method: {m_name} ({desc} detected)")
            all_blocks: List[ContentBlock] = []
            for p in paths:
                blocks = self.pdf_extractor.from_path(p, page_numbers=page_nums)
                if not blocks:
                    raise ValueError(f"No text could be extracted from PDF: {p}")
                all_blocks.extend(blocks)
            if not all_blocks:
                raise ValueError("No text could be extracted from any PDF")
            save_ocr_path = getattr(self, 'save_ocr_path', None)
            if save_ocr_path:
                ocr_text = "\n".join(b.content for b in all_blocks if b.content)
                Path(save_ocr_path).write_text(ocr_text, encoding="utf-8")
                print(f"  [html2mcq] OCR text saved to: {save_ocr_path}")
            all_qs, _ = self._generate(
                blocks=all_blocks,
                n=n,
                page_title=title,
                source_url=f"file://{paths[0]}",
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                custom_instructions=custom_instructions,
                show_progress=show_progress,
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

    # ── Vision → MCQ (onestep method) ────────────────────────────────────

    def _vision_mcq(
        self, img_blocks: List[ContentBlock], n: int, page_title: str,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> List[MCQQuestion]:
        """Send images directly to vision model and parse MCQ JSON response."""
        import urllib.request
        import urllib.error

        # ── Resolve Provider and Model ──────────────────────────────────
        vis_model_raw = self.image_ocr_extractor.vision_model
        res = _parse_operator_model(vis_model_raw, self.provider, self.available_keys)
        if not res:
            return []
        p_target, model_name = res
        
        # Determine API key and base URL
        if self.provider == "auto":
            p_key = self.available_keys.get(p_target, "")
        else:
            p_key = self.image_ocr_extractor.vision_api_key

        if not p_key and p_target != "ollama":
            return []

        try:
            import openai
        except ImportError:
            return []

        # Provider base URLs
        base_urls = {
            "openrouter": "https://openrouter.ai/api/v1",
            "openai": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "ollama": getattr(self.backend, "ollama_base_url", "http://localhost:11434/v1"),
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "deepseek": "https://api.deepseek.com",
            "groq": "https://api.groq.com/openai/v1",
            "manualai": os.environ.get("MANUALAI_BASE_URL", ""),
        }
        
        client = openai.OpenAI(
            api_key=p_key,
            base_url=base_urls.get(p_target),
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
            '"explanation": "..."}'
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
            resp = _retry_with_backoff(lambda: client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": content}],
                max_tokens=self.max_tokens,
            ))
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' returned empty response")
                return []
            return self._parse_response(raw)
        except Exception as e:
            err_msg = str(e).split('\n')[0][:100]
            print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' failed: {err_msg}")
            return []

    def _vision_mcq_pdf(
        self, pngs: Optional[List[bytes]] = None, n: int = 1, page_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
        pdf_bytes: Optional[bytes] = None,
    ) -> List[MCQQuestion]:
        """Send PDF data (either as PNGs or native PDF bytes) to a vision model."""
        # ── Resolve Provider and Model ──────────────────────────────────
        vis_model_raw = self.image_ocr_extractor.vision_model
        res = _parse_operator_model(vis_model_raw, self.provider, self.available_keys)
        if not res:
            return []
        p_target, model_name = res
        
        # Determine API key and base URL
        if self.provider == "auto":
            p_key = self.available_keys.get(p_target, "")
        else:
            p_key = self.image_ocr_extractor.vision_api_key

        if not p_key and p_target != "ollama":
            return []

        try:
            import openai
        except ImportError:
            return []

        # Provider base URLs
        base_urls = {
            "openrouter": "https://openrouter.ai/api/v1",
            "openai": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "ollama": getattr(self.backend, "ollama_base_url", "http://localhost:11434/v1") if self.backend else "http://localhost:11434/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "deepseek": "https://api.deepseek.com",
            "groq": "https://api.groq.com/openai/v1",
            "manualai": os.environ.get("MANUALAI_BASE_URL", ""),
        }

        client = openai.OpenAI(
            api_key=p_key,
            base_url=base_urls.get(p_target),
        )

        instr_parts = [f"Generate {n} MCQ questions based on the content in these PDF pages."]
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
            '"explanation": "..."}'
        )
        
        # ── Build Multi-modal Content ──
        content: list = [{"type": "text", "text": "\n".join(instr_parts)}]
        
        # Try native PDF first for Gemini/OpenRouter if bytes are available
        use_native = pdf_bytes and self.provider in ("gemini", "openrouter")
        
        if use_native:
            b64_pdf = _base64.b64encode(pdf_bytes).decode("utf-8")
            # Google/OpenRouter convention for PDF in OpenAI-compatible SDK
            content.append({
                "type": "image_url", # Some SDKs use generic type but this often works for blobs
                "image_url": {"url": f"data:application/pdf;base64,{b64_pdf}"},
            })
            log_desc = f"Native PDF ({len(pdf_bytes)} bytes)"
        elif pngs:
            for png in pngs:
                b64 = _base64.b64encode(png).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            log_desc = f"{len(pngs)} rendered pages"
        else:
            return []

        self._log_prompt("VISION INSTRUCTION",
                          f"Model: {self.image_ocr_extractor.vision_model}\n"
                          f"Data: {log_desc}\n"
                          f"Instruction: {content[0]['text']}")

        try:
            resp = _retry_with_backoff(lambda: client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": content}],
                max_tokens=self.max_tokens,
            ))
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' returned empty response")
                return []
            return self._parse_response(raw)
        except Exception as e:
            err_msg = str(e).split('\n')[0][:100]
            print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' failed: {err_msg}")
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
        show_progress: bool = False,
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
            show_progress=show_progress,
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
                "(gemini)/gemini-2.5-flash-lite",
                "(openai)/gpt-4o-mini",
                "(deepseek)/deepseek-chat",
                "(groq)/llama-3.3-70b-versatile",
                "(openrouter)/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "(openrouter)/openai/gpt-oss-120b:free",
                "(openrouter)/google/gemma-4-31b-it:free",
                "(anthropic)/claude-3-5-sonnet-20241022",
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

    @staticmethod
    def get_mcq_models() -> list:
        """Return MCQ model list from HTML2MCQ_MCQ_MODELS env var, or built-in default."""
        return [entry["model"] for entry in MCQGenerator._resolve_mcq_model_list()]

    @staticmethod
    def set_mcq_models(value: str) -> None:
        """Set HTML2MCQ_MCQ_MODELS env var (comma-separated)."""
        os.environ["HTML2MCQ_MCQ_MODELS"] = value

    @staticmethod
    def get_ocr_models() -> list:
        """Return OCR model list from HTML2MCQ_OCR_MODELS env var, or built-in default."""
        from html2mcq.image_ocr import _OCR_MODELS_ENV_VAR, _DEFAULT_OCR_PRIORITY
        env = os.environ.get(_OCR_MODELS_ENV_VAR, "").strip()
        if env:
            return [m.strip() for m in env.split(",") if m.strip()]
        return list(_DEFAULT_OCR_PRIORITY)

    @staticmethod
    def set_ocr_models(value: str) -> None:
        """Set HTML2MCQ_OCR_MODELS env var (comma-separated)."""
        os.environ["HTML2MCQ_OCR_MODELS"] = value

    @staticmethod
    def set_api_key(provider: str, key: str) -> None:
        """Set the API key env var for a provider only if not already set.

        Providers: openrouter, anthropic, openai, gemini, deepseek, groq, manualai, ollama
        """
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "groq": "GROQ_API_KEY",
            "manualai": "MANUALAI_API_KEY",
            "ollama": "",
        }
        env_var = env_map.get(provider.lower())
        if not env_var:
            return
        if not os.environ.get(env_var, "").strip():
            os.environ[env_var] = key

    def _generate(
        self,
        blocks: List[ContentBlock],
        n: int,
        page_title: str,
        source_url: Optional[str],
        difficulty_mix: Optional[str],
        focus_topics: Optional[List[str]],
        custom_instructions: Optional[str] = None,
        show_progress: bool = False,
    ) -> Tuple[List[MCQQuestion], str]:
        if not blocks:
            return [], ""

        all_questions: List[MCQQuestion] = []
        system_prompt = build_system_prompt()
        remaining = n

        try:
            from tqdm import tqdm as _tqdm
            _pbar = _tqdm(total=n, desc="MCQ", unit="q", disable=not show_progress)
        except ImportError:
            _pbar = None
        _total_batches = (n + self.batch_size - 1) // self.batch_size if n < 9999 else None
        _batch_count = 0

        def _report(questions):
            nonlocal _batch_count
            _batch_count += 1
            if _pbar is not None:
                _pbar.update(len(questions))
            elif show_progress and _total_batches is not None:
                print(f"  [html2mcq] Batch {_batch_count}/{_total_batches}: "
                      f"{len(questions)} questions", file=__import__('sys').stderr)

        # ── Resolve MCQ model (supports priority_list mode) ──
        backend_cache = {}
        if self.mcq_model == "priority_list":
            model_list = self._resolve_mcq_model_list(self.mcq_model_list)
            for entry in model_list:
                res = _parse_operator_model(entry["model"], self.provider, self.available_keys)
                if not res:
                    continue
                p_target, model_name = res
                
                # Resolve backend for this specific model
                if self.provider == "auto":
                    if p_target not in backend_cache:
                        p_key = self.available_keys.get(p_target)
                        backend_cache[p_target] = _make_backend(p_target, p_key, model_name)
                    current_backend = backend_cache[p_target]
                else:
                    current_backend = self.backend
                
                current_backend.mcq_model = model_name
                model_tokens = entry["max_tokens"]
                est_tokens_per_q = 500
                requested_output = n * est_tokens_per_q + 200
                batch_max_tokens = min(model_tokens, requested_output)
                max_per_call = max(1, batch_max_tokens // est_tokens_per_q)
                batch_n = min(remaining, max_per_call)
                
                text_prompt = build_user_prompt(
                    blocks=blocks,
                    n=batch_n,
                    difficulty_mix=difficulty_mix,
                    focus_topics=focus_topics,
                    page_title=page_title,
                    custom_instructions=self._resolve_instructions(custom_instructions),
                )
                
                # Hybrid Vision: detect images with data
                user_content: Union[str, List[dict]] = text_prompt
                image_data_blocks = [b for b in blocks if b.type == "image" and b.metadata.get("image_data")]
                if self.method == "onestep" and image_data_blocks:
                    user_content = [{"type": "text", "text": text_prompt}]
                    for b in image_data_blocks:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b.metadata['image_data']}"}
                        })

                self._log_prompt("SYSTEM", system_prompt)
                self._log_prompt("USER", str(user_content) if isinstance(user_content, list) else user_content)
                try:
                    raw = current_backend.complete(system_prompt, user_content, batch_max_tokens)
                    batch = self._parse_response(raw)
                except Exception as e:
                    err_msg = str(e).split('\n')[0][:100]
                    print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' failed: {err_msg}")
                    continue
                if batch:
                    all_questions.extend(batch)
                    _report(batch)
                    remaining -= len(batch)
                    print(f"  [html2mcq] OK MCQ model ({p_target}) '{model_name}' selected "
                          f"({len(batch)} questions, {batch_max_tokens} max_tokens)")
                    break
            else:
                raise RuntimeError(
                    f"All MCQ models in list failed: {[e['model'] for e in model_list]}"
                )
            if _pbar is not None:
                _pbar.close()
            all_questions = all_questions[:n]
            summary = self._build_summary(blocks)
            return all_questions, summary

        # Simple loop
        # We need a backend for this loop
        current_backend = self.backend
        if self.provider == "auto":
            res = _parse_operator_model(self.mcq_model, self.provider, self.available_keys)
            if res:
                p_target, model_name = res
                if p_target not in backend_cache:
                    p_key = self.available_keys.get(p_target)
                    backend_cache[p_target] = _make_backend(p_target, p_key, model_name)
                current_backend = backend_cache[p_target]
                current_backend.mcq_model = model_name
            else:
                 # If model is invalid, we can't really continue in this loop
                 raise ValueError(f"In 'auto' operator mode, the model '{self.mcq_model}' could not be resolved.")

        while remaining > 0:
            batch_n = min(remaining, self.batch_size)
            text_prompt = build_user_prompt(
                blocks=blocks,
                n=batch_n,
                difficulty_mix=difficulty_mix,
                focus_topics=focus_topics,
                page_title=page_title,
                custom_instructions=self._resolve_instructions(custom_instructions),
            )
            
            # Hybrid Vision: detect images with data
            user_content: Union[str, List[dict]] = text_prompt
            image_data_blocks = [b for b in blocks if b.type == "image" and b.metadata.get("image_data")]
            if self.method == "onestep" and image_data_blocks:
                user_content = [{"type": "text", "text": text_prompt}]
                for b in image_data_blocks:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b.metadata['image_data']}"}
                    })

            self._log_prompt("SYSTEM", system_prompt)
            self._log_prompt("USER", str(user_content) if isinstance(user_content, list) else user_content)
            try:
                raw = current_backend.complete(system_prompt, user_content, self.max_tokens)
                batch_questions = self._parse_response(raw)
            except Exception as e:
                # Resolve display names for the error message
                res = _parse_operator_model(self.mcq_model, self.provider, self.available_keys)
                p_display, m_display = res if res else (self.provider, self.mcq_model)
                err_msg = str(e).split('\n')[0][:100]
                print(f"  [html2mcq] \u26a0 ({p_display}) '{m_display}' failed: {err_msg}")
                break

            all_questions.extend(batch_questions)
            _report(batch_questions)
            remaining -= len(batch_questions)

            if len(batch_questions) == 0:
                break
            if remaining > 0 and len(batch_questions) < batch_n:
                break

        if _pbar is not None:
            _pbar.close()
        all_questions = all_questions[:n]
        summary = self._build_summary(blocks)
        return all_questions, summary

    @staticmethod
    def _build_summary(blocks: List[ContentBlock]) -> str:
        counts = {}
        for b in blocks:
            counts[b.type] = counts.get(b.type, 0) + 1
        parts = [f"{v} {k}{'s' if v>1 else ''}" for k, v in sorted(counts.items())]
        return "Content: " + ", ".join(parts)

    def _parse_response(self, raw: str) -> List[MCQQuestion]:
        """Parse AI JSON response into MCQQuestion objects."""
        # Strip any accidental markdown fences
        text = raw.strip()
        if not text:
            return []
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
                    explanation=item.get("explanation", item.get("explaination", "")),
                )
                questions.append(q)
            except (KeyError, TypeError, ValueError):
                continue  # Skip malformed items
        return questions

    # ── Async Backends ───────────────────────────────────────────────────────────

class _AsyncAnthropicBackend:
    def __init__(self, api_key: str, mcq_model: str):
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.mcq_model = mcq_model or "claude-opus-4-6"

    async def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        msg = await self.client.messages.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class _AsyncOpenAIBackend:
    def __init__(self, api_key: str, mcq_model: str, base_url: Optional[str] = None, **kwargs):
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, **kwargs)
        self.mcq_model = mcq_model or "gpt-4o"

    async def complete(self, system: str, user: Union[str, List[dict]], max_tokens: int) -> str:
        resp = await self.client.chat.completions.create(
            model=self.mcq_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


def _make_async_backend(provider: str, api_key: str, mcq_model: str, **kwargs):
    provider = provider.lower()
    if provider == "anthropic":
        return _AsyncAnthropicBackend(api_key, mcq_model)
    
    # All others are OpenAI-compatible
    base_urls = {
        "openai": None,
        "openrouter": "https://openrouter.ai/api/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "deepseek": "https://api.deepseek.com",
        "groq": "https://api.groq.com/openai/v1",
        "manualai": kwargs.get("manualai_base_url") or os.environ.get("MANUALAI_BASE_URL", ""),
        "ollama": kwargs.get("ollama_base_url") or "http://localhost:11434/v1",
    }
    
    if provider not in base_urls:
        raise ValueError(f"Unknown async provider '{provider}'")
        
    return _AsyncOpenAIBackend(api_key, mcq_model, base_url=base_urls[provider], **kwargs)


class AsyncMCQGenerator(MCQGenerator):
    """Asynchronous version of MCQGenerator."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For auto operator mode, we don't have a single backend
        if self.provider != "auto":
            self.backend = _make_async_backend(
                self.provider, self._resolved_api_key, self.mcq_model, **kwargs
            )
        else:
            self.backend = None

    async def from_url(self, url: str, **kwargs) -> MCQSet:
        import asyncio
        loop = asyncio.get_running_loop()
        use_vision = self.method == "onestep"
        
        # 1. Extraction (Sync -> Thread)
        title, blocks = await loop.run_in_executor(None, lambda: self.extractor.from_url(url))
        
        # 2. PDF enrichment (Sync -> Thread)
        if kwargs.get("enrich_pdfs", True):
            blocks = await loop.run_in_executor(None, lambda: self.pdf_extractor.enrich_blocks(blocks))
            
        # 3. Image enrichment (Sync -> Thread)
        if kwargs.get("enrich_images", True):
            if use_vision:
                blocks = await loop.run_in_executor(None, lambda: self.image_ocr_extractor.download_images(blocks))
            else:
                blocks = await loop.run_in_executor(None, lambda: self.image_ocr_extractor.enrich_blocks(blocks))
        
        return await self._generate_async(blocks, kwargs.get("n", 999), title, url, **kwargs)

    async def from_html(self, html: str, **kwargs) -> MCQSet:
        import asyncio
        loop = asyncio.get_running_loop()
        use_vision = self.method == "onestep"
        title, blocks = await loop.run_in_executor(None, lambda: self.extractor.from_html(html, base_url=kwargs.get("base_url", "")))
        
        if kwargs.get("enrich_pdfs", True):
            blocks = await loop.run_in_executor(None, lambda: self.pdf_extractor.enrich_blocks(blocks))
        if kwargs.get("enrich_images", True):
            if use_vision:
                blocks = await loop.run_in_executor(None, lambda: self.image_ocr_extractor.download_images(blocks))
            else:
                blocks = await loop.run_in_executor(None, lambda: self.image_ocr_extractor.enrich_blocks(blocks))
                
        return await self._generate_async(blocks, kwargs.get("n", 999), title, kwargs.get("base_url"), **kwargs)

    async def from_pdf_urls(self, urls: Union[str, List[str]], **kwargs) -> MCQSet:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: super(AsyncMCQGenerator, self).from_pdf_urls(urls, **kwargs))

    async def from_pdf_paths(self, paths: Union[str, List[str]], **kwargs) -> MCQSet:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: super(AsyncMCQGenerator, self).from_pdf_paths(paths, **kwargs))

    async def from_image_urls(self, urls: Union[str, List[str]], **kwargs) -> MCQSet:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: super(AsyncMCQGenerator, self).from_image_urls(urls, **kwargs))

    async def from_image_paths(self, paths: Union[str, List[str]], **kwargs) -> MCQSet:
        import asyncio
        if self.method == "onestep":
            if isinstance(paths, str): paths = [paths]
            blocks = []
            for p in paths:
                data = Path(p).read_bytes()
                b64 = _base64.b64encode(data).decode("utf-8")
                blocks.append(ContentBlock(type="image", content=f"data:image/png;base64,{b64}", 
                                           metadata={"image_data": b64}))
            return await self._generate_async(blocks, kwargs.get("n", 999), "Images", f"file://{paths[0]}", **kwargs)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: super(AsyncMCQGenerator, self).from_image_paths(paths, **kwargs))

    async def from_blocks(self, blocks: List[ContentBlock], **kwargs) -> MCQSet:
        return await self._generate_async(blocks, kwargs.get("n", 999), kwargs.get("page_title", "Custom"), kwargs.get("source_url"), **kwargs)

    async def _generate_async(self, blocks: List[ContentBlock], n: int, page_title: str, source_url: Optional[str], **kwargs) -> MCQSet:
        system_prompt = build_system_prompt()
        remaining = n
        all_questions = []
        backend_cache = {}

        if self.mcq_model == "priority_list":
            model_list = self._resolve_mcq_model_list(self.mcq_model_list)
            for entry in model_list:
                res = _parse_operator_model(entry["model"], self.provider, self.available_keys)
                if not res: continue
                p_target, model_name = res

                if self.provider == "auto":
                    if p_target not in backend_cache:
                        p_key = self.available_keys.get(p_target)
                        backend_cache[p_target] = _make_async_backend(p_target, p_key, model_name)
                    current_backend = backend_cache[p_target]
                else:
                    current_backend = self.backend
                
                current_backend.mcq_model = model_name
                batch_n = min(remaining, self.batch_size)
                text_prompt = build_user_prompt(blocks, batch_n, page_title=page_title, 
                                               custom_instructions=self._resolve_instructions(kwargs.get("custom_instructions")))
                
                user_content = text_prompt
                image_data_blocks = [b for b in blocks if b.type == "image" and b.metadata.get("image_data")]
                if self.method == "onestep" and image_data_blocks:
                    user_content = [{"type": "text", "text": text_prompt}]
                    for b in image_data_blocks:
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b.metadata['image_data']}"}})

                try:
                    raw = await current_backend.complete(system_prompt, user_content, self.max_tokens)
                    batch = self._parse_response(raw)
                    if batch:
                        all_questions.extend(batch)
                        remaining -= len(batch)
                        break
                except Exception as e:
                    err_msg = str(e).split('\n')[0][:100]
                    print(f"  [html2mcq] \u26a0 ({p_target}) '{model_name}' failed: {err_msg}")
                    continue
        else:
            while remaining > 0:
                batch_n = min(remaining, self.batch_size)
                text_prompt = build_user_prompt(blocks, batch_n, page_title=page_title, 
                                               custom_instructions=self._resolve_instructions(kwargs.get("custom_instructions")))
                
                user_content = text_prompt
                image_data_blocks = [b for b in blocks if b.type == "image" and b.metadata.get("image_data")]
                if self.method == "onestep" and image_data_blocks:
                    user_content = [{"type": "text", "text": text_prompt}]
                    for b in image_data_blocks:
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b.metadata['image_data']}"}})

                try:
                    raw = await self.backend.complete(system_prompt, user_content, self.max_tokens)
                    batch = self._parse_response(raw)
                    if not batch: break
                    all_questions.extend(batch)
                    remaining -= len(batch)
                except Exception as e:
                    res = _parse_operator_model(self.mcq_model, self.provider, self.available_keys)
                    p_display, m_display = res if res else (self.provider, self.mcq_model)
                    err_msg = str(e).split('\n')[0][:100]
                    print(f"  [html2mcq] \u26a0 ({p_display}) '{m_display}' failed: {err_msg}")
                    break

        return self._build_mcq_set(all_questions, n, page_title, source_url, blocks)


