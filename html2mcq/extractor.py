"""
ContentExtractor: Parses HTML tutorial pages and extracts text, images,
video links, PDF links, code blocks, and tables into structured ContentBlocks.
"""
from __future__ import annotations

import re
import urllib.request
import urllib.error
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .models import ContentBlock

try:
    from bs4 import BeautifulSoup, Tag
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


# ── URL helpers ───────────────────────────────────────────────────────────────

VIDEO_PATTERNS = [
    r"youtube\.com/watch",
    r"youtu\.be/",
    r"vimeo\.com/",
    r"dailymotion\.com/",
    r"twitch\.tv/",
    r"\.mp4$",
    r"\.webm$",
    r"\.ogg$",
]

PDF_PATTERNS = [
    r"\.pdf($|\?)",
    r"drive\.google\.com.*pdf",
    r"docs\.google\.com/.*presentation",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff"}


def _is_video_url(url: str) -> bool:
    return any(re.search(p, url, re.IGNORECASE) for p in VIDEO_PATTERNS)


def _is_pdf_url(url: str) -> bool:
    return any(re.search(p, url, re.IGNORECASE) for p in PDF_PATTERNS)


def _is_image_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _absolute_url(base: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base, href)


# ── Extractor ─────────────────────────────────────────────────────────────────

class ContentExtractor:
    """
    Extracts structured content from an HTML string or URL.

    Usage
    -----
    extractor = ContentExtractor()
    blocks = extractor.from_url("https://example.com/tutorial")
    # or
    blocks = extractor.from_html(html_string, base_url="https://example.com/tutorial")
    """

    # Tags whose text content we skip entirely (navigation, boilerplate, etc.)
    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}
    # Tags that typically contain the main article body
    MAIN_TAGS = {"article", "main", "section", "div"}

    def __init__(
        self,
        min_text_length: int = 40,
        include_images: bool = True,
        include_videos: bool = True,
        include_pdfs: bool = True,
        include_code: bool = True,
        include_tables: bool = True,
        user_agent: str = "html2mcq/1.0 (content extractor)",
        timeout: int = 15,
    ):
        if not BS4_AVAILABLE:
            raise ImportError(
                "BeautifulSoup4 is required: pip install html2mcq[bs4]  "
                "or  pip install beautifulsoup4 lxml"
            )
        self.min_text_length = min_text_length
        self.include_images = include_images
        self.include_videos = include_videos
        self.include_pdfs = include_pdfs
        self.include_code = include_code
        self.include_tables = include_tables
        self.user_agent = user_agent
        self.timeout = timeout

    # ── Public API ────────────────────────────────────────────────────────────

    def from_url(self, url: str) -> Tuple[str, List[ContentBlock]]:
        """
        Fetch *url*, parse the HTML, and return (page_title, blocks).
        """
        html = self._fetch(url)
        return self.from_html(html, base_url=url)

    def from_html(
        self, html: str, base_url: str = ""
    ) -> Tuple[str, List[ContentBlock]]:
        """
        Parse *html* and return (page_title, blocks).
        *base_url* is used to resolve relative links.
        """
        soup = BeautifulSoup(html, "lxml" if self._lxml_available() else "html.parser")

        # Remove boilerplate tags
        for tag in soup(self.SKIP_TAGS):
            tag.decompose()

        title = self._extract_title(soup)
        blocks: List[ContentBlock] = []
        seen_urls: set = set()

        # Walk the DOM in document order
        body = soup.find("body") or soup
        self._walk(body, base_url, blocks, seen_urls)

        return title, blocks

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    @staticmethod
    def _lxml_available() -> bool:
        try:
            import lxml  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return "Untitled Page"

    def _walk(
        self,
        node,
        base_url: str,
        blocks: List[ContentBlock],
        seen_urls: set,
    ):
        for child in node.children:
            if not hasattr(child, "name") or child.name is None:
                # NavigableString – skip, text is captured at element level
                continue

            tag: Tag = child
            name = tag.name.lower()

            if name in self.SKIP_TAGS:
                continue

            # ── Images ──
            if name == "img" and self.include_images:
                src = tag.get("src", "")
                if src:
                    abs_src = _absolute_url(base_url, src)
                    if abs_src not in seen_urls:
                        seen_urls.add(abs_src)
                        blocks.append(ContentBlock(
                            type="image",
                            content=abs_src,
                            alt_text=tag.get("alt", ""),
                            caption=tag.get("title", ""),
                        ))
                continue

            # ── <video> ──
            if name == "video" and self.include_videos:
                src = tag.get("src", "")
                source_tag = tag.find("source")
                if not src and source_tag:
                    src = source_tag.get("src", "")
                if src:
                    abs_src = _absolute_url(base_url, src)
                    if abs_src not in seen_urls:
                        seen_urls.add(abs_src)
                        blocks.append(ContentBlock(
                            type="video",
                            content=abs_src,
                            caption=tag.get("title", ""),
                        ))
                continue

            # ── <iframe> (YouTube / Vimeo embeds) ──
            if name == "iframe" and self.include_videos:
                src = tag.get("src", "")
                if src and _is_video_url(src):
                    abs_src = _absolute_url(base_url, src)
                    if abs_src not in seen_urls:
                        seen_urls.add(abs_src)
                        blocks.append(ContentBlock(
                            type="video",
                            content=abs_src,
                            caption=tag.get("title", ""),
                            metadata={"embed": True},
                        ))
                continue

            # ── Anchors ──
            if name == "a":
                href = tag.get("href", "")
                if href:
                    abs_href = _absolute_url(base_url, href)
                    if abs_href not in seen_urls:
                        if self.include_pdfs and _is_pdf_url(abs_href):
                            seen_urls.add(abs_href)
                            blocks.append(ContentBlock(
                                type="pdf",
                                content=abs_href,
                                alt_text=tag.get_text(strip=True),
                            ))
                        elif self.include_videos and _is_video_url(abs_href):
                            seen_urls.add(abs_href)
                            blocks.append(ContentBlock(
                                type="video",
                                content=abs_href,
                                alt_text=tag.get_text(strip=True),
                            ))
                        elif self.include_images and _is_image_url(abs_href):
                            seen_urls.add(abs_href)
                            blocks.append(ContentBlock(
                                type="image",
                                content=abs_href,
                                alt_text=tag.get_text(strip=True),
                            ))
                # Still recurse into <a> for nested text / images
                self._walk(tag, base_url, blocks, seen_urls)
                continue

            # ── Code blocks ──
            if name in ("pre", "code") and self.include_code:
                code_text = tag.get_text()
                if len(code_text.strip()) >= 10:
                    lang = ""
                    cls = tag.get("class", [])
                    for c in cls:
                        if "language-" in c:
                            lang = c.replace("language-", "")
                    blocks.append(ContentBlock(
                        type="code",
                        content=code_text,
                        metadata={"language": lang},
                    ))
                continue

            # ── Tables ──
            if name == "table" and self.include_tables:
                rows = []
                for tr in tag.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append(ContentBlock(
                        type="table",
                        content="\n".join(rows),
                        metadata={"rows": len(rows)},
                    ))
                continue

            # ── Headings & text-bearing elements ──
            if name in ("h1","h2","h3","h4","h5","h6","p","li","blockquote","figcaption","td","th","dt","dd","summary","details"):
                text = tag.get_text(" ", strip=True)
                if len(text) >= self.min_text_length:
                    blocks.append(ContentBlock(
                        type="text",
                        content=text,
                        metadata={"tag": name},
                    ))
                # Don't recurse into these – we already captured their text
                continue

            # ── Recurse into containers ──
            self._walk(tag, base_url, blocks, seen_urls)
