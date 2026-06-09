# html2mcq

**Convert any HTML tutorial page, PDF, or image into MCQ questions using AI.**

[![PyPI version](https://badge.fury.io/py/html2mcq.svg)](https://pypi.org/project/html2mcq/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Install

```bash
pip install html2mcq
```

Everything is included — HTML extraction, PDF support, OCR, all AI providers.

---

## Quick Start

```python
from html2mcq import MCQGenerator

gen = MCQGenerator(
    api_key="sk-or-v1-...",
    provider="openrouter",
    mcq_model="google/gemini-2.5-flash-lite",
)

# From an HTML tutorial page
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=15)

# From a PDF URL
mcq = gen.from_pdf_urls("https://example.com/tutorial.pdf", n=10)

# From a local PDF file
mcq = gen.from_pdf_paths("/path/to/notes.pdf", n=10)

# From image files (OCR → MCQ in one step)
mcq = gen.from_image_paths("screenshot.png", n=5)

# From image URLs (vision model direct)
mcq = gen.from_image_urls("https://example.com/diagram.png", n=5)

print(mcq.to_json())
print(mcq.to_pretty_str())
```

---

## Input Methods

| Input | Method | Batch support |
|---|---|---|
| HTML tutorial page URL | `from_url(url)` | ❌ single URL |
| Raw HTML string | `from_html(html)` | ❌ single string |
| PDF via URL | `from_pdf_urls(url)` | ✅ `list[str]` |
| Local PDF file | `from_pdf_paths(path)` | ✅ `list[str]` |
| Image files (local) | `from_image_paths(path)` | ✅ `list[str]` |
| Image URLs | `from_image_urls(url)` | ✅ `list[str]` |
| Pre-built content blocks | `from_blocks(blocks)` | ❌ single list |

---

## Examples (10+)

### 1. Basic — HTML tutorial page

```python
from html2mcq import MCQGenerator

gen = MCQGenerator(api_key="sk-or-v1-...")
mcq = gen.from_url("https://docs.python.org/3/tutorial/introduction.html", n=5)
print(mcq.to_pretty_str())
```

### 2. Raw HTML string

```python
html_string = """
<html><body>
<h1>Python Lists</h1>
<p>Lists are ordered, mutable collections. Items are indexed from 0.</p>
<pre><code>fruits = ["apple", "banana", "cherry"]
fruits.append("date")
</code></pre>
</body></html>
"""
mcq = gen.from_html(html_string, n=3)
print(mcq.to_json())
```

### 3. Multiple PDF URLs in batch

```python
mcq = gen.from_pdf_urls([
    "https://example.com/chapter1.pdf",
    "https://example.com/chapter2.pdf",
    "https://example.com/chapter3.pdf",
], n=20)
```

### 4. Local PDF files

```python
mcq = gen.from_pdf_paths([
    "C:/Users/Me/Documents/lecture_notes.pdf",
    "C:/Users/Me/Documents/textbook_ch5.pdf",
], n=15)
```

### 5. Image files with OCR (two-step)

```python
gen = MCQGenerator(
    api_key="sk-or-v1-...",
    method="twostep",
    ocr_model="google/gemini-2.5-flash-lite",
    save_ocr_path="ocr_output.txt",
)
mcq = gen.from_image_paths("screenshot.png", n=5)
```

### 6. Image URLs via vision model (direct)

```python
gen = MCQGenerator(
    api_key="sk-or-v1-...",
    method="images2mcq",
)
mcq = gen.from_image_urls("https://example.com/diagram.png", n=5)
```

### 7. Batch image files

```python
mcq = gen.from_image_paths([
    "slide01.png",
    "slide02.png",
    "slide03.png",
], n=15)
```

### 8. Generate as many questions as possible

```python
# When n=999, the AI covers every distinct topic in the content
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=999)
print(f"Generated {len(mcq.questions)} questions")
```

### 9. Difficulty mix and topic focus

```python
mcq = gen.from_url(
    "https://docs.python.org/3/tutorial/",
    n=20,
    difficulty_mix="50% easy, 30% medium, 20% hard",
    focus_topics=["lists", "dictionaries", "loops"],
)
```

### 10. Custom instructions per call

```python
mcq = gen.from_url(
    "https://docs.python.org/3/tutorial/",
    n=10,
    custom_instructions="All questions must be code-based. Include the code snippet in the question.",
)
```

### 11. Pre-extracted content blocks

```python
from html2mcq import MCQGenerator, ContentExtractor

extractor = ContentExtractor()
title, blocks = extractor.from_url("https://docs.python.org/3/tutorial/")

# Filter to only code blocks
code_blocks = [b for b in blocks if b.type == "code"]
mcq = gen.from_blocks(code_blocks, n=5)
```

### 12. Save output to JSON file

```python
import json

mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=10)
with open("quiz.json", "w") as f:
    json.dump(mcq.to_json(), f, indent=2)
```

### 13. Filter questions by difficulty

```python
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=20)
easy = mcq.filter_by_difficulty("easy")
medium = mcq.filter_by_difficulty("medium")
hard = mcq.filter_by_difficulty("hard")
print(f"Easy: {len(easy)}, Medium: {len(medium)}, Hard: {len(hard)}")
```

### 14. Different AI provider — Anthropic

```python
gen = MCQGenerator(
    api_key="sk-ant-...",
    provider="anthropic",
    mcq_model="claude-3-5-sonnet-20241022",
)
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=10)
```

### 15. Local Ollama (no API key needed)

```python
gen = MCQGenerator(
    provider="ollama",
    mcq_model="qwen2.5:7b",
    ollama_base_url="http://localhost:11434/v1",
)
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=5)
```

---

## Constructor

```python
gen = MCQGenerator(
    provider="openrouter",                         # default, also: "anthropic" | "openai" | "ollama"
    api_key="sk-or-v1-...",                        # or set env var OPENROUTER_API_KEY
    api_key_override="sk-or-v1-...",               # override key for this instance
    mcq_model="google/gemini-2.5-flash-lite",      # model for ALL MCQ generation
    mcq_model_list=["model1", "model2"],           # fallback list for mcq_model="auto"
    ocr_model="pytesseract",                       # OCR for HTML images: "pytesseract" | "auto" | model ID
    ocr_models=["model1", "pytesseract"],          # priority list for ocr_model="auto"
    method="twostep",                              # "twostep" (OCR→MCQ) | "images2mcq" (vision direct)
    save_ocr_path="ocr_output.txt",                # save OCR text when method=twostep
    prompt_log_path="stdout",                      # dump prompts: file path | "stdout" | "-"
    batch_size=10,
    max_tokens=4096,
    custom_instructions="Make answers tricky",
)
```

### New in v2

| Parameter | What it does |
|---|---|
| `mcq_model` | Single source of truth for all MCQ generation (text + vision). Renamed from `model`. |
| `mcq_model="auto"` | Tries `mcq_model_list` in order until one succeeds. |
| `mcq_model_list` | Priority-ordered models for auto mode. Runtime-reloadable via `HTML2MCQ_MCQ_MODELS` env var. |
| `ocr_model` | OCR backend: `"pytesseract"` (default), `"auto"` (priority list), or any OpenRouter model ID. |
| `ocr_model="auto"` | Tries `ocr_models` priority list. |
| `ocr_models` | Priority list for auto OCR. Reloadable via `HTML2MCQ_OCR_MODELS` env var. |
| `method` | `"twostep"` (OCR images → text → MCQs) or `"images2mcq"` (vision model direct). |
| `prompt_log_path` | Dump full prompts to file or terminal. Use `"stdout"` or `"-"` for terminal. |
| `api_key_override` | Override key for this instance |
| `save_ocr_path` | Save OCR text to file when method=twostep |

---

## Two-Step Image Pipeline (`method="twostep"`)

When `method="twostep"` (default), `from_image_paths()` and `from_image_urls()` automatically:

1. **OCR** — extract text from images using `ocr_model`
2. **Generate** — feed text into text-based MCQ generation

Optionally save the OCR text with `save_ocr_path`:

```python
gen = MCQGenerator(method="twostep", ocr_model="google/gemini-2.5-flash-lite",
                   save_ocr_path="ocr_output.txt")

# OCR → save to file → generate MCQs
gen.from_image_paths("chart.png", n=5)
```

---

## Per-Call Overrides

All 7 public methods accept `api_key_override` and `prompt_log_path`:

```python
mcq = gen.from_url(
    "https://example.com/",
    n=10,
    api_key_override="sk-or-v1-...",       # different key for this call
    prompt_log_path="debug_prompt.txt",    # log prompts for this call only
)
```

---

## Output Schema

```json
{
  "total_exam_time": 20,
  "questions": [
    {
      "question_html": "Which of these are non-mutating array methods?",
      "options": ["push()", "map()", "filter()", "pop()"],
      "answers": [1, 2],
      "multi": true,
      "marks": 1,
      "negative_marks": 0,
      "difficulty": "medium",
      "explaination": "map() and filter() return new arrays without modifying the original."
    }
  ]
}
```

---

## AI Providers

```python
# OpenRouter (default) — 100+ models
gen = MCQGenerator(api_key="sk-or-...", provider="openrouter",
                   mcq_model="google/gemini-2.5-flash-lite")

# Anthropic Claude
gen = MCQGenerator(api_key="sk-ant-...", provider="anthropic")

# OpenAI
gen = MCQGenerator(api_key="sk-...", provider="openai", mcq_model="gpt-4o")

# Ollama (local, no API key needed)
gen = MCQGenerator(provider="ollama", mcq_model="qwen2.5:7b",
                   ollama_base_url="http://localhost:11434/v1")
```

---

## OCR Priority (when `ocr_model="auto"`)

The default priority list is:
1. `google/gemini-2.5-flash-lite` (fast, cheap)
2. `google/gemma-3-27b-it` (free)
3. `google/gemma-3-12b-it` (free)
4. `openai/gpt-4o` (paid)
5. `pytesseract` (local fallback)

Override via `ocr_models` parameter or `HTML2MCQ_OCR_MODELS` env var.

---

## MCQ Model Priority (when `mcq_model="auto"`)

Tries `mcq_model_list` in order. Override via `HTML2MCQ_MCQ_MODELS` env var (comma-separated):

```bash
export HTML2MCQ_MCQ_MODELS="model1,model2,model3"
```

---

## Custom Instructions

```python
# Apply to every call
gen = MCQGenerator(
    provider="openrouter",
    custom_instructions="Make answers very close and confusing."
)

# Or per individual call
mcq = gen.from_url("https://example.com/", n=10,
    custom_instructions="All questions must be code-based.")
```

---

## API Reference

### `MCQGenerator`

| Parameter | Default | Description |
|---|---|---|
| `provider` | `"openrouter"` | `"openrouter"` | `"anthropic"` | `"openai"` | `"ollama"` |
| `api_key` | `None` | API key or env var |
| `api_key_override` | `None` | Override key for this instance |
| `mcq_model` | `""` | Model for all MCQ generation. `"auto"` tries `mcq_model_list` |
| `mcq_model_list` | `None` | Fallback models for auto mode |
| `ocr_model` | `"pytesseract"` | OCR backend: `"pytesseract"` | `"auto"` | model ID |
| `ocr_models` | `None` | Priority list for auto OCR |
| `method` | `"twostep"` | `"twostep"` (OCR→MCQ) | `"images2mcq"` |
| `prompt_log_path` | `None` | Dump prompts to file/terminal |
| `batch_size` | `10` | Questions per API call |
| `custom_instructions` | `None` | Global custom instructions |

| Method | Description |
|---|---|
| `from_url(url, n, ...)` | HTML page |
| `from_html(html, n, ...)` | Raw HTML string |
| `from_pdf_urls(urls, n, ...)` | PDF via URL (str or list) |
| `from_pdf_paths(paths, n, ...)` | Local PDF file (str or list) |
| `from_image_urls(urls, n, ...)` | Image URLs → MCQ via vision |
| `from_image_paths(paths, n, ...)` | Local image files → MCQ |
| `from_blocks(blocks, n, ...)` | Pre-extracted `ContentBlock` list |

All methods accept `api_key_override`, `prompt_log_path`, `difficulty_mix`, `focus_topics`, `custom_instructions`.

### `MCQSet`

| Property / Method | Description |
|---|---|
| `.questions` | `List[MCQQuestion]` |
| `.total_exam_time` | Minutes — auto-calculated as n × 2 |
| `.to_json()` | Exam-ready JSON |
| `.to_pretty_str()` | Human-readable output |
| `.filter_by_difficulty(d)` | Filter by `"easy"` / `"medium"` / `"hard"` |

---

## CLI

```bash
# Basic — URL (n defaults to 999 = cover all topics)
html2mcq https://docs.python.org/3/tutorial/

# Local HTML file
html2mcq --html ./tutorial.html

# PDF URL
html2mcq --pdf-url https://example.com/chapter1.pdf --pdf-url https://example.com/chapter2.pdf

# Local PDF file
html2mcq --pdf-path ./textbook.pdf

# Image URL (via vision model)
html2mcq --image-url https://example.com/diagram.png --method images2mcq

# Local image files
html2mcq --image-path ./slide1.png --image-path ./slide2.png

# Specify question count
html2mcq https://example.com/tutorial --n 20

# Output to JSON file
html2mcq https://example.com/tutorial --output quiz.json --format json

# Difficulty mix and topic focus
html2mcq https://example.com/tutorial --difficulty "40% easy, 40% medium, 20% hard" --topics variables functions

# Custom instructions
html2mcq https://example.com/tutorial -i "Make answers very close and confusing"

# AI provider and model
html2mcq https://example.com/tutorial --provider openai --mcq-model gpt-4o --api-key sk-...

# Auto-detect API key from env var (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY)
html2mcq https://example.com/tutorial

# Local Ollama (no API key needed)
html2mcq https://example.com/tutorial --provider ollama --mcq-model qwen2.5:7b

# Show version
html2mcq --version
```

All output is printed to stdout by default. Use `--output` / `-o` to save to a file.

---

## Project Structure

```
html2mcq/
├── html2mcq/
│   ├── __init__.py
│   ├── extractor.py        # HTML parser
│   ├── generator.py        # MCQGenerator — main API
│   ├── image_ocr.py        # OCR (pytesseract + vision API)
│   ├── models.py           # ContentBlock, MCQQuestion, MCQSet
│   ├── pdf.py              # PDF extractor
│   ├── prompts.py          # System + user prompt builders
│   └── cli.py              # CLI entry point
├── tests/
│   ├── test_html2mcq.py    # Unit tests (fully mocked)
│   └── scripts/            # Debug / scratch scripts
├── pyproject.toml
├── README.md
└── CHANGELOG.md
```

---

## License

MIT © 2025 html2mcq contributors
