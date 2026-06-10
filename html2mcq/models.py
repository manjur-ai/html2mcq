"""
Data models for html2mcq.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json


@dataclass
class ContentBlock:
    """Represents a block of extracted content from an HTML page."""
    type: str                   # "text" | "image" | "pdf" | "code" | "table" | "image_ocr" | "pdf_text"
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
    explanation: str           # Explanation (typo preserved per spec)

    def to_dict(self) -> dict:
        return {
            "question_html": self.question_html,
            "options": self.options,
            "answers": self.answers,
            "multi": self.multi,
            "marks": self.marks,
            "negative_marks": self.negative_marks,
            "difficulty": self.difficulty,
            "explanation": self.explanation,
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
        if self.explanation:
            lines += ["", f"  Explanation: {self.explanation}"]
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

    def to_aiken(self) -> str:
        """Returns the set in Aiken format (simple text format for LMS)."""
        blocks = []
        for q in self.questions:
            lines = [q.question_html]
            for i, opt in enumerate(q.options):
                lines.append(f"{chr(65+i)}) {opt}")
            # Aiken only supports single answer officially, but we take the first
            ans_idx = q.answers[0] if q.answers else 0
            lines.append(f"ANSWER: {chr(65+ans_idx)}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def to_moodle_xml(self) -> str:
        """Returns the set in Moodle XML format."""
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        root = ET.Element("quiz")
        for i, q in enumerate(self.questions):
            question = ET.SubElement(root, "question", {"type": "multichoice"})
            
            name = ET.SubElement(question, "name")
            ET.SubElement(name, "text").text = f"Q{i+1}: {self.page_title[:40]}"
            
            qtext = ET.SubElement(question, "questiontext", {"format": "html"})
            ET.SubElement(qtext, "text").text = f"<![CDATA[{q.question_html}]]>"
            
            ET.SubElement(question, "single").text = "false" if q.multi else "true"
            ET.SubElement(question, "shuffleanswers").text = "true"
            ET.SubElement(question, "answernumbering").text = "abc"
            
            if q.explanation:
                feedback = ET.SubElement(question, "generalfeedback", {"format": "html"})
                ET.SubElement(feedback, "text").text = f"<![CDATA[{q.explanation}]]>"

            # Calculate fraction for multiple answers
            num_correct = len(q.answers)
            fraction = 100.0 / num_correct if num_correct > 0 else 100.0

            for idx, opt in enumerate(q.options):
                is_correct = idx in q.answers
                ans = ET.SubElement(question, "answer", {
                    "fraction": str(fraction if is_correct else 0),
                    "format": "plain_text"
                })
                ET.SubElement(ans, "text").text = opt
                
        # Pretty print
        xml_str = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_str)
        # Un-escape CDATA manually because minidom/ET might escape '&lt;' etc.
        return parsed.toprettyxml(indent="  ").replace("&lt;", "<").replace("&gt;", ">")

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
