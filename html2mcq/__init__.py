"""
html2mcq - Convert any HTML tutorial page, PDF, or image into MCQ questions using AI.
"""

from .generator import MCQGenerator
from .extractor import ContentExtractor
from .pdf import PDFExtractor
from .image_ocr import ImageOCRExtractor
from .models import MCQQuestion, MCQSet, ContentBlock

try:
    from importlib.metadata import version as _v
    __version__ = _v("html2mcq")
except Exception:
    __version__ = "3.3.7"
__author__ = "html2mcq"
__all__ = [
    "MCQGenerator",
    "ContentExtractor",
    "PDFExtractor",
    "ImageOCRExtractor",
    "MCQQuestion",
    "MCQSet",
    "ContentBlock",
]
