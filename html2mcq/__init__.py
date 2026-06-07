"""
html2mcq - Convert any HTML tutorial page, YouTube video, or PDF into MCQ questions using AI.
"""

from .generator import MCQGenerator
from .extractor import ContentExtractor
from .video import VideoTranscriptExtractor
from .pdf import PDFExtractor
from .models import MCQQuestion, MCQSet, ContentBlock

__version__ = "1.2.0"
__author__ = "html2mcq"
__all__ = [
    "MCQGenerator",
    "ContentExtractor",
    "VideoTranscriptExtractor",
    "PDFExtractor",
    "MCQQuestion",
    "MCQSet",
    "ContentBlock",
]
