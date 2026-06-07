"""
VideoTranscriptExtractor: Fetches transcripts from YouTube videos
and converts them into ContentBlocks for MCQ generation.

Supports:
- youtube-transcript-api (no API key needed, auto/manual captions)
- Manual transcript text as fallback
"""
from __future__ import annotations

import re
from typing import List, Optional, Dict, Tuple
from .models import ContentBlock


# ── YouTube URL helpers ───────────────────────────────────────────────────────

_YT_PATTERNS = [
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/)([A-Za-z0-9_-]{11})",
    r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
]


def extract_video_id(url: str) -> Optional[str]:
    """Extract the 11-char YouTube video ID from any YouTube URL format."""
    for pattern in _YT_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_youtube_url(url: str) -> bool:
    return extract_video_id(url) is not None


# ── Transcript fetcher ────────────────────────────────────────────────────────

class VideoTranscriptExtractor:
    """
    Fetches YouTube video transcripts and converts them to ContentBlocks.

    Usage
    -----
    vte = VideoTranscriptExtractor()

    # From a video URL
    blocks = vte.from_url("https://www.youtube.com/watch?v=VXU4LSAQDSc")

    # From a video ID directly
    blocks = vte.from_video_id("VXU4LSAQDSc")

    # Enrich existing ContentBlocks (auto-replaces video blocks with transcripts)
    enriched = vte.enrich_blocks(existing_blocks)
    """

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        chunk_size: int = 800,          # characters per ContentBlock chunk
        chunk_overlap: int = 100,        # overlap between chunks for context
        max_duration: Optional[int] = None,  # max seconds of transcript to use (None = all)
        preserve_timestamps: bool = False,
    ):
        """
        Parameters
        ----------
        languages : list[str], optional
            Preferred transcript languages in order. Defaults to ["en"].
        chunk_size : int
            Characters per text chunk (ContentBlock). Larger = more context per
            question but fewer distinct blocks.
        chunk_overlap : int
            Characters of overlap between consecutive chunks.
        max_duration : int, optional
            Only use the first N seconds of transcript. Useful for long videos.
        preserve_timestamps : bool
            Include [MM:SS] timestamps in the chunk text.
        """
        self.languages = languages or ["en"]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_duration = max_duration
        self.preserve_timestamps = preserve_timestamps

    # ── Public API ────────────────────────────────────────────────────────────

    def from_url(self, url: str) -> List[ContentBlock]:
        """
        Fetch transcript for a YouTube URL and return ContentBlocks.
        Raises ValueError if the URL is not a YouTube URL.
        Raises RuntimeError if transcript cannot be fetched.
        """
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError(f"Not a recognised YouTube URL: {url}")
        return self.from_video_id(video_id, source_url=url)

    def from_video_id(
        self, video_id: str, source_url: str = ""
    ) -> List[ContentBlock]:
        """
        Fetch transcript for a YouTube video ID and return ContentBlocks.
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            raise ImportError(
                "youtube-transcript-api is required for video transcripts.\n"
                "Install it with:  pip install html2mcq[video]"
            )

        raw_segments = self._fetch_transcript(video_id)
        full_text, timed_chunks = self._process_segments(raw_segments)
        blocks = self._build_blocks(
            timed_chunks,
            video_id=video_id,
            source_url=source_url or f"https://www.youtube.com/watch?v={video_id}",
            full_text=full_text,
        )
        return blocks

    def from_text(
        self,
        transcript_text: str,
        source_url: str = "",
        video_title: str = "",
    ) -> List[ContentBlock]:
        """
        Convert a plain-text transcript string into ContentBlocks.
        Useful as a manual fallback or for testing.
        """
        chunks = self._chunk_text(transcript_text)
        blocks = []
        for i, chunk in enumerate(chunks):
            blocks.append(ContentBlock(
                type="transcript",
                content=chunk,
                caption=video_title,
                metadata={
                    "source": "manual",
                    "source_url": source_url,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            ))
        return blocks

    def enrich_blocks(
        self, blocks: List[ContentBlock], replace: bool = True
    ) -> List[ContentBlock]:
        """
        Walk a list of ContentBlocks, find all video blocks that are YouTube URLs,
        fetch their transcripts, and return an enriched block list.

        Parameters
        ----------
        blocks : list[ContentBlock]
            Existing blocks (e.g. from ContentExtractor).
        replace : bool
            If True, replace the original video block with transcript blocks.
            If False, append transcript blocks after the video block.
        """
        enriched: List[ContentBlock] = []
        for block in blocks:
            if block.type == "video" and is_youtube_url(block.content):
                try:
                    transcript_blocks = self.from_url(block.content)
                    if replace:
                        enriched.extend(transcript_blocks)
                    else:
                        enriched.append(block)
                        enriched.extend(transcript_blocks)
                    print(
                        f"  [html2mcq] ✓ Fetched transcript for {block.content} "
                        f"→ {len(transcript_blocks)} chunks"
                    )
                except Exception as e:
                    # Keep original video block if transcript fails
                    enriched.append(block)
                    print(f"  [html2mcq] ⚠ Could not fetch transcript for {block.content}: {e}")
            else:
                enriched.append(block)
        return enriched

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_transcript(self, video_id: str) -> List[Dict]:
        """Fetch raw transcript segments from YouTube."""
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        )

        api = YouTubeTranscriptApi()

        try:
            # Try preferred languages first
            transcript_list = api.list(video_id)
            transcript = transcript_list.find_transcript(self.languages)
        except NoTranscriptFound:
            try:
                # Fall back to auto-generated in any language
                transcript_list = api.list(video_id)
                transcript = transcript_list.find_generated_transcript(
                    transcript_list._generated_transcripts.keys()
                    or self.languages
                )
            except Exception:
                # Last resort: fetch directly
                transcript = api.fetch(video_id)
                return list(transcript)

        fetched = transcript.fetch()
        return list(fetched)

    def _process_segments(
        self, segments: List[Dict]
    ) -> Tuple[str, List[Tuple[str, float]]]:
        """
        Process raw transcript segments into:
        - full_text: the complete joined transcript
        - timed_chunks: list of (text_chunk, start_seconds) tuples
        """
        if not segments:
            return "", []

        # Filter by max_duration
        if self.max_duration:
            segments = [s for s in segments if s.get("start", 0) <= self.max_duration]

        # Build full text with optional timestamps
        parts = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            if self.preserve_timestamps:
                start = seg.get("start", 0)
                mm = int(start // 60)
                ss = int(start % 60)
                parts.append(f"[{mm:02d}:{ss:02d}] {text}")
            else:
                parts.append(text)

        full_text = " ".join(parts)

        # Chunk the full text
        raw_chunks = self._chunk_text(full_text)

        # Pair each chunk with an approximate start time
        timed_chunks = []
        for i, chunk in enumerate(raw_chunks):
            # Estimate start time proportionally
            approx_start = 0.0
            if segments:
                ratio = i / max(len(raw_chunks) - 1, 1)
                last_start = segments[-1].get("start", 0)
                approx_start = ratio * last_start
            timed_chunks.append((chunk, approx_start))

        return full_text, timed_chunks

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks of ~chunk_size characters."""
        if not text.strip():
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.chunk_size

            if end >= text_len:
                chunks.append(text[start:].strip())
                break

            # Try to break at sentence boundary (. ! ?)
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind("! ", start, end),
                text.rfind("? ", start, end),
            )
            if boundary > start + self.chunk_size // 2:
                end = boundary + 1
            else:
                # Fall back to word boundary
                word_boundary = text.rfind(" ", start, end)
                if word_boundary > start:
                    end = word_boundary

            chunks.append(text[start:end].strip())
            start = end - self.chunk_overlap

        return [c for c in chunks if c]

    def _build_blocks(
        self,
        timed_chunks: List[Tuple[str, float]],
        video_id: str,
        source_url: str,
        full_text: str,
    ) -> List[ContentBlock]:
        """Convert timed text chunks into ContentBlocks."""
        blocks = []

        for i, (chunk, start_sec) in enumerate(timed_chunks):
            mm = int(start_sec // 60)
            ss = int(start_sec % 60)
            yt_url = f"{source_url}&t={int(start_sec)}s" if "youtube" in source_url else source_url

            blocks.append(ContentBlock(
                type="transcript",
                content=chunk,
                metadata={
                    "source": "youtube_transcript",
                    "video_id": video_id,
                    "source_url": yt_url,
                    "chunk_index": i,
                    "total_chunks": len(timed_chunks),
                    "approx_timestamp": f"{mm:02d}:{ss:02d}",
                    "char_count": len(chunk),
                },
            ))

        return blocks
