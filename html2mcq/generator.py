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

from .extractor import ContentExtractor
from .models import ContentBlock, MCQQuestion, MCQSet
from .prompts import build_system_prompt, build_user_prompt
from .video import VideoTranscriptExtractor, extract_video_id, is_youtube_url
from .pdf import PDFExtractor


# ── AI backend registry ───────────────────────────────────────────────────────

class _AnthropicBackend:
    """Uses the official anthropic SDK."""

    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class _OpenAIBackend:
    """Uses the official openai SDK."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, model: str):
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content


class _OpenRouterBackend:
    """
    Uses OpenRouter (https://openrouter.ai) — drop-in for any model
    including Llama, Mistral, Gemini via the OpenAI-compatible API.
    """

    DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"

    def __init__(self, api_key: str, model: str, site_url: str = "", site_name: str = "html2mcq"):
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
        self.model = model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content


def _make_backend(provider: str, api_key: str, model: str, **kwargs):
    provider = provider.lower()
    if provider == "anthropic":
        return _AnthropicBackend(api_key, model)
    if provider == "openai":
        return _OpenAIBackend(api_key, model)
    if provider == "openrouter":
        return _OpenRouterBackend(api_key, model, **kwargs)
    raise ValueError(f"Unknown provider '{provider}'. Choose: anthropic | openai | openrouter")


# ── MCQGenerator ──────────────────────────────────────────────────────────────

class MCQGenerator:
    """
    Generate N MCQ questions from any HTML tutorial page.

    Quick start
    -----------
    >>> from html2mcq import MCQGenerator
    >>> gen = MCQGenerator(api_key="sk-ant-...", provider="anthropic")
    >>> mcq_set = gen.from_url("https://docs.python.org/3/tutorial/", n=10)
    >>> print(mcq_set.to_pretty_str())

    Parameters
    ----------
    api_key : str
        Your AI provider API key. Falls back to environment variables:
        ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY.
    provider : str
        "anthropic" (default) | "openai" | "openrouter"
    model : str
        Override the default model for the provider.
    batch_size : int
        Number of questions to request per API call (default 10).
        Large `n` values are split into batches to stay within token limits.
    max_tokens : int
        Max tokens for each API response (default 4096).
    extractor_kwargs : dict
        Keyword args forwarded to ContentExtractor.
    **backend_kwargs
        Extra args forwarded to the backend (e.g. site_url for OpenRouter).
    """

    ENV_KEYS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "anthropic",
        model: str = "",
        batch_size: int = 10,
        max_tokens: int = 4096,
        extractor_kwargs: Optional[dict] = None,
        transcript_languages: Optional[List[str]] = None,
        transcript_chunk_size: int = 800,
        pdf_backend: str = "pymupdf",
        docling_api_url: str = "",
        docling_ocr: bool = True,
        pdf_chunk_size: int = 1500,
        custom_instructions: Optional[str] = None,
        **backend_kwargs,
    ):
        self.provider = provider.lower()
        _key = api_key or os.environ.get(self.ENV_KEYS.get(self.provider, ""), "")
        if not _key:
            raise ValueError(
                f"No API key supplied. Pass api_key= or set "
                f"{self.ENV_KEYS.get(self.provider, 'YOUR_API_KEY')} env var."
            )
        self.backend = _make_backend(self.provider, _key, model, **backend_kwargs)
        self.batch_size = max(1, batch_size)
        self.max_tokens = max_tokens
        self.extractor = ContentExtractor(**(extractor_kwargs or {}))
        self.transcript_extractor = VideoTranscriptExtractor(
            languages=transcript_languages or ["en"],
            chunk_size=transcript_chunk_size,
        )
        self.pdf_extractor = PDFExtractor(
            backend=pdf_backend,
            docling_api_url=docling_api_url,
            docling_ocr=docling_ocr,
            chunk_size=pdf_chunk_size,
        )
        self.custom_instructions = custom_instructions or ""

    # ── Public API ────────────────────────────────────────────────────────────



    def from_html(
        self,
        html: str,
        n: int = 10,
        base_url: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_videos: bool = True,
        enrich_pdfs: bool = True,
        custom_instructions: Optional[str] = None,
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
        enrich_videos : bool
            Auto-fetch YouTube transcripts found in page (default True).
        enrich_pdfs : bool
            Auto-download and extract PDF links found in page (default True).
        """
        title, blocks = self.extractor.from_html(html, base_url=base_url)
        if enrich_videos:
            blocks = self.transcript_extractor.enrich_blocks(blocks)
        if enrich_pdfs:
            blocks = self.pdf_extractor.enrich_blocks(blocks)
        return self._generate(
            blocks=blocks,
            n=n,
            page_title=title,
            source_url=base_url or None,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

    def from_blocks(
        self,
        blocks: List[ContentBlock],
        n: int = 10,
        page_title: str = "Custom Content",
        source_url: Optional[str] = None,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs from pre-extracted ContentBlocks.
        Useful when you've already parsed the page yourself.
        """
        return self._generate(
            blocks=blocks,
            n=n,
            page_title=page_title,
            source_url=source_url,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

    def from_video_url(
        self,
        url: str,
        n: int = 10,
        video_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs directly from a YouTube video URL.
        Fetches the transcript automatically — no API key needed.

        Parameters
        ----------
        url : str
            YouTube video URL (any format: watch, youtu.be, embed, shorts).
        n : int
            Number of questions to generate.
        video_title : str, optional
            Title of the video. If empty, uses the URL as title.
        difficulty_mix : str, optional
            E.g. "30% easy, 40% medium, 30% hard".
        focus_topics : list[str], optional
            Topics to focus on.

        Example
        -------
        >>> gen = MCQGenerator(provider="anthropic")
        >>> mcq = gen.from_video_url(
        ...     "https://www.youtube.com/watch?v=VXU4LSAQDSc",
        ...     n=10,
        ...     video_title="Grammarly AI Tutorial"
        ... )
        """
        print(f"  [html2mcq] Fetching transcript for: {url}")
        blocks = self.transcript_extractor.from_url(url)
        if not blocks:
            raise ValueError(f"No transcript found for: {url}")
        print(f"  [html2mcq] Got {len(blocks)} transcript chunks → generating {n} MCQs...")
        title = video_title or f"Video: {url}"
        return self._generate(
            blocks=blocks,
            n=n,
            page_title=title,
            source_url=url,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

    def from_url(
        self,
        url: str,
        n: int = 10,
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        enrich_videos: bool = True,
        enrich_pdfs: bool = True,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """
        Fetch the page at *url*, extract content, and generate *n* MCQs.
        If the URL is a YouTube link, fetches the transcript automatically.

        Parameters
        ----------
        url : str
            Tutorial page URL, or a direct YouTube video URL.
        n : int
            Number of MCQ questions to generate.
        enrich_videos : bool
            If True (default), automatically fetch transcripts for any YouTube
            video links found in the page.
        enrich_pdfs : bool
            If True (default), automatically download and extract any PDF links
            found in the page.
        """
        # Direct YouTube URL — go straight to transcript
        if is_youtube_url(url):
            return self.from_video_url(url, n=n,
                                       difficulty_mix=difficulty_mix,
                                       focus_topics=focus_topics,
                                       custom_instructions=custom_instructions)

        title, blocks = self.extractor.from_url(url)

        if enrich_videos:
            blocks = self.transcript_extractor.enrich_blocks(blocks)
        if enrich_pdfs:
            blocks = self.pdf_extractor.enrich_blocks(blocks)

        return self._generate(
            blocks=blocks,
            n=n,
            page_title=title,
            source_url=url,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

    def from_pdf_url(
        self,
        url: str,
        n: int = 10,
        pdf_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs directly from a PDF URL.

        Backend priority: PyMuPDF → auto-fallback to Docling if text is sparse.

        Parameters
        ----------
        url : str
            Direct URL to a PDF file.
        n : int
            Number of questions to generate.
        pdf_title : str, optional
            Title for the MCQSet. Defaults to the filename from the URL.
        difficulty_mix : str, optional
            E.g. "30% easy, 40% medium, 30% hard".
        focus_topics : list[str], optional
            Topics to focus on.

        Example
        -------
        >>> gen = MCQGenerator(provider="anthropic")
        >>> mcq = gen.from_pdf_url(
        ...     "https://example.com/python-tutorial.pdf",
        ...     n=10,
        ...     pdf_title="Python Tutorial"
        ... )
        """
        blocks = self.pdf_extractor.from_url(url)
        if not blocks:
            raise ValueError(f"No text could be extracted from PDF: {url}")
        title = pdf_title or url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ").title()
        return self._generate(
            blocks=blocks,
            n=n,
            page_title=title,
            source_url=url,
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

    def from_pdf_path(
        self,
        path: str,
        n: int = 10,
        pdf_title: str = "",
        difficulty_mix: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        """
        Generate MCQs from a local PDF file.

        Parameters
        ----------
        path : str
            Local file path to a PDF.
        n : int
            Number of questions to generate.
        """
        blocks = self.pdf_extractor.from_path(path)
        if not blocks:
            raise ValueError(f"No text could be extracted from PDF: {path}")
        title = pdf_title or Path(path).stem.replace("-", " ").replace("_", " ").title()
        return self._generate(
            blocks=blocks,
            n=n,
            page_title=title,
            source_url=f"file://{path}",
            difficulty_mix=difficulty_mix,
            focus_topics=focus_topics,
            custom_instructions=custom_instructions,
        )

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

    # ── Internal generation pipeline ─────────────────────────────────────────

    def _generate(
        self,
        blocks: List[ContentBlock],
        n: int,
        page_title: str,
        source_url: Optional[str],
        difficulty_mix: Optional[str],
        focus_topics: Optional[List[str]],
        custom_instructions: Optional[str] = None,
    ) -> MCQSet:
        if not blocks:
            raise ValueError("No content extracted from the page. Check the URL or HTML.")

        all_questions: List[MCQQuestion] = []
        system_prompt = build_system_prompt()
        remaining = n

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
            raw = self.backend.complete(system_prompt, user_prompt, self.max_tokens)
            batch_questions = self._parse_response(raw)
            all_questions.extend(batch_questions)
            remaining -= len(batch_questions)

            # Safety: if AI returned fewer than asked, don't loop forever
            if len(batch_questions) == 0:
                break
            if remaining > 0 and len(batch_questions) < batch_n:
                break

        # Trim to exactly n
        all_questions = all_questions[:n]

        summary = self._build_summary(blocks)
        exam_time = max(1, len(all_questions) * 2)  # 2 minutes per question

        return MCQSet(
            source_url=source_url,
            page_title=page_title,
            questions=all_questions,
            total_questions=len(all_questions),
            content_summary=summary,
            total_exam_time=exam_time,
            metadata={
                "provider": self.provider,
                "model": getattr(self.backend, "model", "unknown"),
                "requested_n": n,
                "content_blocks": len(blocks),
                "content_types": list({b.type for b in blocks}),
            },
        )

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
            try:
                # Support both old single int and new list format for answers
                raw_answers = item.get("answers", item.get("correct_answer", 0))
                if isinstance(raw_answers, int):
                    answers = [raw_answers]
                else:
                    answers = [int(a) for a in raw_answers]

                multi = item.get("multi", len(answers) > 1)
                marks = float(item.get("marks", 1))
                negative_marks = float(item.get("negative_marks", 0.0 if multi else 0.25))

                q = MCQQuestion(
                    question_html=item.get("question_html", item.get("question", "")),
                    options=item["options"][:4],
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



