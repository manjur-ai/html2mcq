"""
Prompt construction for MCQ generation.
"""
from __future__ import annotations
from typing import List, Optional
from .models import ContentBlock


_SYSTEM_BASE = """\
You are an expert educator and quiz designer.
Your task is to generate high-quality multiple-choice questions (MCQs) from educational content.

Rules:
1. Each question must have EXACTLY 4 options.
2. Most questions should have ONE correct answer. Occasionally (20-30%) generate questions
   with MULTIPLE correct answers — for those, set multi=true and list all correct indices in answers.
3. Distractors must be plausible, not obviously wrong.
4. Vary difficulty: roughly 1/3 easy, 1/3 medium, 1/3 hard.
5. question_html may use simple inline HTML tags (<code>, <b>, <em>) when useful.
6. Never fabricate facts not present in the content.
7. marks is always 1. negative_marks is 0.25 for single-answer, 0 for multi-answer questions.
8. explaination should be a brief explanation of why the answer(s) are correct (can be empty string).
9. Respond ONLY with valid JSON — no markdown fences, no preamble.

JSON schema (array of objects):
[
  {
    "question_html": "<question text, may include inline HTML>",
    "options": ["<A>", "<B>", "<C>", "<D>"],
    "answers": [<0-based int>, ...],
    "multi": <true|false>,
    "marks": 1,
    "negative_marks": <0.25 for single, 0 for multi>,
    "difficulty": "<easy|medium|hard>",
    "explaination": "<brief explanation or empty string>"
  }
]
"""


def build_system_prompt() -> str:
    return _SYSTEM_BASE


def build_user_prompt(
    blocks: List[ContentBlock],
    n: int,
    difficulty_mix: Optional[str] = None,
    focus_topics: Optional[List[str]] = None,
    page_title: str = "",
    custom_instructions: Optional[str] = None,
) -> str:
    sections: List[str] = []

    if page_title:
        sections.append(f"PAGE TITLE: {page_title}\n")

    text_blocks       = [b for b in blocks if b.type == "text"]
    code_blocks       = [b for b in blocks if b.type == "code"]
    table_blocks      = [b for b in blocks if b.type == "table"]
    image_blocks      = [b for b in blocks if b.type == "image"]
    video_blocks      = [b for b in blocks if b.type == "video"]
    pdf_blocks        = [b for b in blocks if b.type == "pdf"]
    transcript_blocks = [b for b in blocks if b.type == "transcript"]
    pdf_text_blocks   = [b for b in blocks if b.type == "pdf_text"]

    if text_blocks:
        sections.append("=== TEXT CONTENT ===")
        for i, b in enumerate(text_blocks, 1):
            tag = b.metadata.get("tag", "p")
            sections.append(f"[{tag.upper()} {i}] {b.content}")
        sections.append("")

    if code_blocks:
        sections.append("=== CODE EXAMPLES ===")
        for i, b in enumerate(code_blocks, 1):
            lang = b.metadata.get("language", "")
            sections.append(f"[CODE {i}{' ('+lang+')' if lang else ''}]\n{b.content.strip()}")
        sections.append("")

    if table_blocks:
        sections.append("=== TABLES ===")
        for i, b in enumerate(table_blocks, 1):
            sections.append(f"[TABLE {i}]\n{b.content}")
        sections.append("")

    if image_blocks:
        sections.append("=== IMAGES ===")
        for i, b in enumerate(image_blocks, 1):
            alt = b.alt_text or "(no alt text)"
            cap = b.caption or ""
            line = f"[IMAGE {i}] URL: {b.content} | Alt: {alt}"
            if cap:
                line += f" | Caption: {cap}"
            sections.append(line)
        sections.append("")

    if video_blocks:
        sections.append("=== VIDEOS ===")
        for i, b in enumerate(video_blocks, 1):
            alt = b.alt_text or ""
            cap = b.caption or ""
            line = f"[VIDEO {i}] URL: {b.content}"
            if alt: line += f" | Title: {alt}"
            if cap: line += f" | Caption: {cap}"
            sections.append(line)
        sections.append("")

    if pdf_blocks:
        sections.append("=== PDF RESOURCES ===")
        for i, b in enumerate(pdf_blocks, 1):
            alt = b.alt_text or ""
            line = f"[PDF {i}] URL: {b.content}"
            if alt: line += f" | Link text: {alt}"
            sections.append(line)
        sections.append("")

    if transcript_blocks:
        sections.append("=== VIDEO TRANSCRIPT ===")
        for i, b in enumerate(transcript_blocks, 1):
            ts = b.metadata.get("approx_timestamp", "")
            vid = b.metadata.get("video_id", "")
            header = f"[TRANSCRIPT {i}"
            if ts: header += f" @ {ts}"
            if vid: header += f" | video:{vid}"
            header += "]"
            sections.append(f"{header}\n{b.content}")
        sections.append("")

    if pdf_text_blocks:
        sections.append("=== PDF CONTENT ===")
        for i, b in enumerate(pdf_text_blocks, 1):
            url = b.metadata.get("source_url", "")
            page = b.metadata.get("total_pages", "?")
            backend = b.metadata.get("backend", "")
            header = f"[PDF {i}"
            if url: header += f" | {url}"
            if page: header += f" | {page} pages"
            if backend: header += f" | via {backend}"
            header += "]"
            sections.append(f"{header}\n{b.content}")
        sections.append("")

    instructions = [f"\nGenerate exactly {n} MCQ questions based on the content above."]

    if difficulty_mix:
        instructions.append(f"Difficulty distribution: {difficulty_mix}")
    else:
        instructions.append("Mix difficulties: approximately equal easy/medium/hard split.")

    if focus_topics:
        instructions.append(f"Focus especially on these topics: {', '.join(focus_topics)}")

    instructions.append(
        "Use ALL content types (text, code, images, videos, PDFs, tables) where possible. "
        "For images/videos/PDFs, base questions on their URLs, alt-texts, captions, and context."
    )
    if custom_instructions and custom_instructions.strip():
        instructions.append(
            f"\n--- CUSTOM INSTRUCTIONS (highest priority, override defaults if needed) ---\n"
            f"{custom_instructions.strip()}\n"
            f"--- END CUSTOM INSTRUCTIONS ---"
        )

    instructions.append("Return ONLY the JSON array, no markdown fences.")

    return "\n".join(sections) + "\n" + "\n".join(instructions)
