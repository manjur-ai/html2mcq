# html2mcq

**Convert any HTML tutorial page, YouTube video, or PDF into MCQ questions using AI.**

[![PyPI version](https://badge.fury.io/py/html2mcq.svg)](https://pypi.org/project/html2mcq/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-68%20passing-brightgreen.svg)]()

---

## Install

```bash
pip install html2mcq
```

That's it. Everything is included — HTML extraction, YouTube transcripts, PDF support, all AI providers.

> For scanned PDFs (OCR + complex layouts), optionally install Docling:
> ```bash
> pip install html2mcq docling
> ```

---

## Quick Start

```python
from html2mcq import MCQGenerator

gen = MCQGenerator(
    api_key="sk-or-v1-...",
    provider="openrouter",
    model="meta-llama/llama-3.3-70b-instruct:free",
)

# From an HTML tutorial page
mcq = gen.from_url("https://docs.python.org/3/tutorial/", n=15)

# From a YouTube video (transcript fetched automatically)
mcq = gen.from_video_url("https://www.youtube.com/watch?v=VXU4LSAQDSc", n=10)

# From a PDF URL
mcq = gen.from_pdf_url("https://example.com/tutorial.pdf", n=10)

# From a local PDF file
mcq = gen.from_pdf_path("/path/to/notes.pdf", n=10)

# From raw HTML
mcq = gen.from_html(html_string, n=10)

print(mcq.to_json())
print(mcq.to_pretty_str())
```

---

## What it supports

| Input | How |
|---|---|
| HTML tutorial page URL | `from_url(url)` — extracts text, code, tables, images, video links, PDF links |
| YouTube video URL | `from_video_url(url)` or `from_url(url)` — transcript fetched automatically |
| PDF via URL | `from_pdf_url(url)` — downloaded and extracted |
| Local PDF file | `from_pdf_path(path)` |
| Raw HTML string | `from_html(html)` |
| Pre-built blocks | `from_blocks(blocks)` |

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

- `answers` is always an array — supports multiple correct answers
- `multi: true` → `negative_marks: 0.0`, `multi: false` → `negative_marks: 0.25`
- `marks` always `1`, difficulty roughly 1/3 each easy/medium/hard

---

## AI Providers

```python
# Anthropic Claude
gen = MCQGenerator(api_key="sk-ant-...", provider="anthropic")

# OpenAI
gen = MCQGenerator(api_key="sk-...", provider="openai", model="gpt-4o")

# OpenRouter — 100+ models, free Llama available
gen = MCQGenerator(api_key="sk-or-...", provider="openrouter",
                   model="meta-llama/llama-3.3-70b-instruct:free")

# API key from environment variable
# Set ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY
gen = MCQGenerator(provider="anthropic")
```

---

## Custom Instructions

Override the AI's default behaviour without breaking the fixed rules (JSON schema, marks, options count).

```python
# Apply to every call this generator makes
gen = MCQGenerator(
    provider="openrouter",
    custom_instructions=(
        "Make answers very close and confusing. "
        "Only people with sharp attention should get 100% marks."
    )
)

# Or per individual call
mcq = gen.from_url(
    "https://example.com/tutorial",
    n=10,
    custom_instructions="All questions must be code-based. No theory questions."
)
```

**How the prompt is structured:**
```
SYSTEM PROMPT  (fixed — always sent, never modified)
  Rules: 4 options, JSON schema, marks/negative_marks, no hallucination...

USER PROMPT
  [extracted content: text / code / tables / transcripts / PDFs]

  Generate exactly N questions. Mix difficulties...

  --- CUSTOM INSTRUCTIONS (highest priority) ---
  Your custom text here
  --- END CUSTOM INSTRUCTIONS ---

  Return ONLY the JSON array.
```

---

## PDF Backends

By default, PyMuPDF handles PDFs instantly. For scanned or complex PDFs, Docling is used as an automatic fallback.

```python
# Default — PyMuPDF, fast, works for most digital PDFs
gen = MCQGenerator(provider="anthropic")

# With Docling Serve on your own server (GPU recommended)
# Run once: docker run --gpus all -p 5001:5001 quay.io/docling/docling-serve
gen = MCQGenerator(
    provider="anthropic",
    docling_api_url="http://your-server:5001"
)
```

**Auto-fallback:**
```
PyMuPDF extracts text
  ↓ fewer than 100 chars? (scanned PDF)
  → retry with Docling Serve  (if docling_api_url set)
  → or retry with Docling Local  (if pip install html2mcq docling)
```

---

## Desktop GUI

```bash
python html2mcq_gui.py
```

5 input tabs: **Web URL · YouTube · PDF URL · Local PDF · Raw HTML**

Options: N questions, difficulty mix, focus topics, custom instructions, PDF backend selector.

Output: syntax-highlighted pretty view or JSON, copy to clipboard, save as JSON.

---

## CLI

```bash
# Basic
html2mcq https://example.com/tutorial --n 20

# All options
html2mcq https://example.com/tutorial \
    --n 20 \
    --provider openrouter \
    --model meta-llama/llama-3.3-70b-instruct:free \
    --difficulty "40% easy, 40% medium, 20% hard" \
    --topics "variables" "functions" \
    --instructions "Make answers very close and confusing" \
    --output quiz.json \
    --format json

# From a local HTML file
html2mcq --html page.html --n 5
```

---

## Live Tests

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
python test_live.py                  # all input types
python test_live.py --test html      # HTML only
python test_live.py --test video     # YouTube only
python test_live.py --test pdf_file  # local PDF only
python test_live.py --n 5
```

---

## API Reference

### `MCQGenerator`

```python
MCQGenerator(
    api_key=None,               # or set env var ANTHROPIC/OPENAI/OPENROUTER_API_KEY
    provider="anthropic",       # "anthropic" | "openai" | "openrouter"
    model="",                   # default per provider if not set
    batch_size=10,              # questions per API call; large N is auto-batched
    max_tokens=4096,
    pdf_backend="pymupdf",      # "pymupdf" | "docling_local" | "docling_serve"
    docling_api_url="",         # Docling Serve URL e.g. "http://your-server:5001"
    docling_ocr=True,
    transcript_languages=["en"],
    custom_instructions="",     # global custom instructions for every call
)
```

| Method | Description |
|---|---|
| `from_url(url, n, ...)` | HTML page; auto-detects YouTube links |
| `from_html(html, n, base_url, ...)` | Raw HTML string |
| `from_video_url(url, n, video_title, ...)` | YouTube video via transcript |
| `from_pdf_url(url, n, pdf_title, ...)` | PDF via URL |
| `from_pdf_path(path, n, pdf_title, ...)` | Local PDF file |
| `from_blocks(blocks, n, ...)` | Pre-extracted `ContentBlock` list |

All methods accept `custom_instructions`, `difficulty_mix`, and `focus_topics`.

### `MCQSet`

| Property / Method | Description |
|---|---|
| `.questions` | `List[MCQQuestion]` |
| `.total_exam_time` | Minutes — auto-calculated as n × 2 |
| `.to_json()` | Exam-ready JSON (`total_exam_time` + `questions` only) |
| `.to_pretty_str()` | Human-readable output |
| `.filter_by_difficulty(d)` | Returns filtered `MCQSet` for `"easy"/"medium"/"hard"` |

---

## Project Structure

```
html2mcq/
├── html2mcq/
│   ├── __init__.py        # Public exports
│   ├── extractor.py       # HTML parser
│   ├── video.py           # YouTube transcript extractor
│   ├── pdf.py             # PDF extractor (PyMuPDF + Docling)
│   ├── generator.py       # MCQGenerator — main API
│   ├── models.py          # ContentBlock, MCQQuestion, MCQSet
│   ├── prompts.py         # Fixed system prompt + dynamic user prompt
│   └── cli.py             # CLI entry point
├── tests/
│   └── test_html2mcq.py   # 68 unit tests (fully mocked, no API key needed)
├── html2mcq_gui.py        # Tkinter desktop GUI
├── test_live.py           # Live integration tests
├── examples/
│   └── basic_usage.py
├── pyproject.toml
├── README.md
└── CHANGELOG.md
```

---

## License

MIT © 2025 html2mcq contributors
