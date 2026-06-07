"""
Data models for html2mcq.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json


@dataclass
class ContentBlock:
    """Represents a block of extracted content from an HTML page."""
    type: str                   # "text" | "image" | "video" | "pdf" | "code" | "table"
    content: str                # text content or URL
    alt_text: Optional[str] = None   # for images
    caption: Optional[str] = None    # for media
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCQQuestion:
    """A single multiple-choice question."""
    question_html: str          # Question text (may contain inline HTML)
    options: List[str]          # Always exactly 4 options
    answers: List[int]          # 0-based indices of ALL correct options
    multi: bool                 # True if more than one correct answer
    marks: float                # Marks awarded for correct answer
    negative_marks: float       # Marks deducted for wrong answer
    difficulty: str             # "easy" | "medium" | "hard"
    explaination: str           # Explanation (typo preserved per spec)

    def to_dict(self) -> dict:
        return {
            "question_html": self.question_html,
            "options": self.options,
            "answers": self.answers,
            "multi": self.multi,
            "marks": self.marks,
            "negative_marks": self.negative_marks,
            "difficulty": self.difficulty,
            "explaination": self.explaination,
        }

    def to_pretty_str(self, number: int = 1) -> str:
        multi_tag = " [MULTI]" if self.multi else ""
        lines = [
            f"Q{number}. [{self.difficulty.upper()}]{multi_tag} {self.question_html}",
            f"  Marks: +{self.marks} / -{self.negative_marks}",
            "",
        ]
        for i, opt in enumerate(self.options):
            marker = "✓" if i in self.answers else " "
            lines.append(f"  {marker} {chr(65+i)}) {opt}")
        if self.explaination:
            lines += ["", f"  Explanation: {self.explaination}"]
        return "\n".join(lines)


@dataclass
class MCQSet:
    """A complete set of MCQ questions generated from a page."""
    source_url: Optional[str]
    page_title: str
    questions: List[MCQQuestion]
    total_questions: int
    content_summary: str
    total_exam_time: int = 30       # Minutes; 2 min per question by default
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Returns the clean exam-ready JSON structure."""
        return {
            "total_exam_time": self.total_exam_time,
            "questions": [q.to_dict() for q in self.questions],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_pretty_str(self) -> str:
        lines = [
            f"{'='*60}",
            f"MCQ Set  : {self.page_title}",
            f"Source   : {self.source_url or 'N/A'}",
            f"Questions: {self.total_questions}  |  Exam time: {self.total_exam_time} min",
            f"Summary  : {self.content_summary}",
            f"{'='*60}",
            "",
        ]
        for i, q in enumerate(self.questions, 1):
            lines.append(q.to_pretty_str(i))
            lines.append("")
        return "\n".join(lines)

    def filter_by_difficulty(self, difficulty: str) -> "MCQSet":
        filtered = [q for q in self.questions if q.difficulty.lower() == difficulty.lower()]
        return MCQSet(
            source_url=self.source_url,
            page_title=self.page_title,
            questions=filtered,
            total_questions=len(filtered),
            content_summary=self.content_summary,
            total_exam_time=len(filtered) * 2,
            metadata=self.metadata,
        )
