# html2mcq

**Convert any HTML tutorial page, PDF, or image into MCQ questions using AI.**

[![PyPI version](https://badge.fury.io/py/html2mcq.svg)](https://pypi.org/project/html2mcq/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-68%20passing-brightgreen.svg)]()

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

## What it supports

| Input | Method |
|---|---|
| HTML tutorial page URL | `from_url(url)` |
| Raw HTML string | `from_html(html)` |
| PDF via URL | `from_pdf_urls(url)` |
| Local PDF file | `from_pdf_paths(path)` |
| Image files (local) | `from_image_paths(path)` |
| Image URLs | `from_image_urls(url)` |
| Pre-built blocks | `from_blocks(blocks)` |

Also accepts `list[str]` for batch — `from_pdf_urls([url1, url2])`, `from_image_paths([img1, img2])`.

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

## PDF Backends

```python
# Default — PyMuPDF, fast, works for most digital PDFs
gen = MCQGenerator(provider="openrouter")
```

---

## CLI

```bash
# Basic
html2mcq https://example.com/tutorial --n 20

# All options
html2mcq https://example.com/tutorial \
    --n 20 \
    --provider openrouter \
    --mcq-model google/gemini-2.5-flash-lite \
    --ocr-model auto \
    --difficulty "40% easy, 40% medium, 20% hard" \
    --topics variables functions \
    --output quiz.json \
    --format json
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
│   ├── test_html2mcq.py       # 119 unit tests (fully mocked)
│   └── scripts/               # Debug / scratch scripts
├── pyproject.toml
├── README.md
└── CHANGELOG.md
```

---

## License

MIT © 2025 html2mcq contributors
