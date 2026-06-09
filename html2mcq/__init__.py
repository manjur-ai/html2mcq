"""
html2mcq - Convert any HTML tutorial page, PDF, or image into MCQ questions using AI.
"""

from .generator import MCQGenerator
from .extractor import ContentExtractor
from .pdf import PDFExtractor
from .image_ocr import ImageOCRExtractor
from .models import MCQQuestion, MCQSet, ContentBlock

__version__ = "2.0.1"
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
