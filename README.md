# html2mcq

**Convert any HTML tutorial, PDF, or image into MCQ quiz questions using AI.**

[![PyPI version](https://badge.fury.io/py/html2mcq.svg)](https://pypi.org/project/html2mcq/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AI Providers](https://img.shields.io/badge/providers-8+-orange)]()

---

## What is html2mcq?

html2mcq is a **Python library and CLI tool** that turns educational content — web tutorials, PDF textbooks, lecture slides, or handwritten notes — into multiple-choice quiz questions automatically using AI.

**Your content goes in; ready-to-export quiz JSON comes out.**

It supports **8 AI providers** (OpenAI, Gemini, Anthropic, DeepSeek, Groq, OpenRouter, Ollama, ManualAI), **4 processing methods** (auto, onestep vision, twostep OCR, local Tesseract), and exports to **Moodle XML** and **Aiken** formats for LMS import.

Perfect for educators, ed-tech platforms, self-learners, and content creators who want to generate assessments from existing material without manual effort.

---

## Key Features

- **Multi-Provider Support**: Gemini, DeepSeek, Groq, OpenAI, Anthropic, OpenRouter, Ollama, and ManualAI.
- **Async Support**: Native `AsyncMCQGenerator` for high-performance integration.
- **LMS Export**: Direct export to **Aiken** and **Moodle XML** formats for easy course importing.
- **Native PDF Vision**: Sends raw PDF data directly to Gemini for highest extraction quality.
- **Resilient Retries**: Automatic exponential backoff for rate limits and transient errors.
- **Request Timeout**: All AI provider calls have a 70-second timeout to prevent hanging.
- **Hybrid Vision**: Simultaneous text + image analysis in `onestep` mode.
- **Smart Choice**: `method="auto"` intelligently chooses the best processing path.
- **Priority List Fallback**: Cycle through a list of models until one succeeds.
- **Operator Auto-Detection**: Automatically detects which API keys you have set.

---

## Quick Start

```bash
pip install html2mcq
```

```python
from html2mcq import MCQGenerator

gen = MCQGenerator(api_key="sk-...", method="auto")

# From a website
mcq = gen.from_url("https://example.com/tutorial", n=5)

# From a PDF
mcq = gen.from_pdf_paths(["chapter1.pdf"], n=10)

# From an image
mcq = gen.from_image_paths("screenshot.png", n=5)

print(mcq.to_pretty_str())
```

---

## Install

```bash
pip install html2mcq
```

Everything is included — HTML extraction, PDF support, OCR, all AI providers, and **native async support**.

---

## Processing Methods (`--method`)

The tool intelligently routes your content based on the `--method` parameter. **`auto`** is the default and usually the best choice.

| Method | Strategy | OCR Engine | MCQ Writer | Required Params |
|:---|:---|:---|:---|:---|
| **`auto`** | Smart Choice | AI Priority List | `mcq_model` | `--mcq-model` or `--ocr-model` |
| **`onestep`** | Vision-Direct | `ocr_model` | `ocr_model` | `--ocr-model` (AI model) |
| **`twostep`** | AI-based OCR | `ocr_model` | `mcq_model`¹ | `--ocr-model` (AI model) |
| **`tesseract`** | Local OCR | Tesseract | `mcq_model`¹ | `--mcq-model` (AI model) |

¹ *If `mcq_model` is omitted, it falls back to the value provided in `ocr_model`.*

> **Note:** `pytesseract` is an internal engine and cannot be passed as a model name. It is automatically used when you select `--method tesseract`.

### When to use what:
- **`auto`**: Use for 99% of cases. It resolves to `onestep` for images and `twostep` for PDFs/HTML.
- **`onestep`**: Best for diagrams or complex layouts where the AI needs to "see" the visual relationship.
- **`twostep`**: Best for documents with very dense text where you want the highest AI-based OCR accuracy.
- **`tesseract`**: Best if you want to use your local machine for OCR (no extra API cost for reading) and only use the AI for writing the quiz.

---

## CLI

```bash
# Smart Mode (Recommended: Vision for images, Text for PDFs)
html2mcq https://example.com/tutorial --method auto

# AI-based OCR (Two-Step)
html2mcq img.png --method twostep --ocr-model gemini-2.0-flash

# Local OCR (Tesseract)
html2mcq img.png --method tesseract --mcq-model claude-3-5

# Vision Direct (Fastest for diagrams)
html2mcq diagram.png --method onestep --ocr-model gemini-2.0-flash

# Save OCR results
html2mcq textbook.pdf --method tesseract --mcq-model gpt-4o --save-ocr-path text.txt

# Export to Moodle XML
html2mcq tutorial.html --method auto --format moodle --output quiz.xml
```

All output is printed to stdout by default. Use `--output` / `-o` to save to a file.

---

## Constructor

```python
gen = MCQGenerator(
    provider="openrouter",                         # "anthropic" | "openai" | "openrouter" | "gemini" | "deepseek" | "groq" | "manualai" | "ollama"
    api_key="sk-...",                              # your API key
    method="auto",                                 # MANDATORY: "auto" | "onestep" | "twostep" | "tesseract"
    mcq_model="google/gemini-2.5-flash-lite",      # the writer (used if method is not onestep)
    ocr_model="google/gemini-2.5-flash-lite",      # the reader (mandatory for onestep/twostep)
    manualai_base_url="https://...",               # only for provider="manualai"
    ocr_fallback=True,                             # fall back to Tesseract if AI OCR fails
    save_ocr_path="ocr_output.txt",                # save extracted text to file
    prompt_log_path="stdout",                      # dump prompts for debugging
    batch_size=10,
    max_tokens=4096,
)
```

### Parameter Roles

| Parameter | Role | Logic |
|:---|:---|:---|
| `mcq_model` | **The Writer** | Used to generate the final JSON quiz from text. Falls back to `ocr_model` if empty. |
| `ocr_model` | **The Reader** | Used as the vision engine for `onestep` and `twostep`. |
| `method` | **The Strategy** | Determines how reading and writing are orchestrated. |

---

## Examples

### 1. Basic — HTML tutorial page

```python
from html2mcq import MCQGenerator

gen = MCQGenerator(api_key="sk-or-v1-...", method="auto")
mcq = gen.from_url("https://docs.python.org/3/tutorial/introduction.html", n=5)
print(mcq.to_pretty_str())
```

### 2. Raw HTML string

```python
gen = MCQGenerator(api_key="sk-...", method="auto")
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

### 3. Local HTML file

```python
mcq = gen.from_html_path("/path/to/tutorial.html", n=5)
```

### 4. Scan HTML folder

```python
mcq = gen.from_html_folder("./tutorials/", n=20)
```

### 5. Multiple PDF URLs in batch

```python
mcq = gen.from_pdf_urls([
    "https://example.com/chapter1.pdf",
    "https://example.com/chapter2.pdf",
    "https://example.com/chapter3.pdf",
], n=20)
```

### 6. Local PDF files

```python
mcq = gen.from_pdf_paths([
    "C:/Users/Me/Documents/lecture_notes.pdf",
    "C:/Users/Me/Documents/textbook_ch5.pdf",
], n=15)
```

### 7. Image files with AI OCR (two-step)

```python
gen = MCQGenerator(
    api_key="sk-...",
    method="twostep",
    ocr_model="google/gemini-2.5-flash-lite"
)
mcq = gen.from_image_paths("screenshot.png", n=5)
```

### 8. Image URLs via local OCR (Tesseract)

```python
gen = MCQGenerator(
    api_key="sk-...",
    method="tesseract",
    mcq_model="claude-3-5-sonnet-20241022"
)
mcq = gen.from_image_urls("https://example.com/diagram.png", n=5)
```

### 9. Vision-Direct (AI looks at image)

```python
gen = MCQGenerator(
    api_key="sk-...",
    method="onestep",
    ocr_model="google/gemini-2.5-flash-lite"
)
mcq = gen.from_image_paths("complex_diagram.png", n=3)
```

---

## LMS Exporting

You can export your generated quizzes directly into formats supported by Moodle, Canvas, and Blackboard.

**CLI:**
```bash
html2mcq tutorial.html --method auto --format moodle --output quiz.xml
html2mcq tutorial.html --method auto --format aiken --output quiz.txt
```

**Python:**
```python
mcq = gen.from_url("https://example.com/lesson")
with open("moodle_quiz.xml", "w") as f:
    f.write(mcq.to_moodle_xml())
```

---

## Async Support

For high-performance applications (like FastAPI), use `AsyncMCQGenerator`:

```python
import asyncio
from html2mcq import AsyncMCQGenerator

async def main():
    gen = AsyncMCQGenerator(api_key="...", provider="openai", method="auto")
    mcq = await gen.from_url("https://example.com/lesson")
    print(mcq.to_pretty_str())

asyncio.run(main())
```

---

## AI Providers

```python
# Gemini (Google)
gen = MCQGenerator(api_key="...", provider="gemini", method="auto")

# DeepSeek
gen = MCQGenerator(api_key="...", provider="deepseek", method="auto")

# Groq (Extreme Speed)
gen = MCQGenerator(api_key="...", provider="groq", method="auto")

# OpenRouter (default) — 100+ models
gen = MCQGenerator(api_key="...", provider="openrouter", method="auto")

# OpenAI
gen = MCQGenerator(api_key="...", provider="openai", method="auto")

# Anthropic Claude
gen = MCQGenerator(api_key="...", provider="anthropic", method="auto")

# ManualAI (Any OpenAI-compatible API)
gen = MCQGenerator(api_key="...", provider="manualai", method="auto",
                   manualai_base_url="https://api.my-custom-llm.com/v1")

# Ollama (local, no API key needed)
gen = MCQGenerator(provider="ollama", method="auto", mcq_model="qwen2.5:7b")
```

---

## Priority Lists

If you set `mcq_model="priority_list"` or `ocr_model="priority_list"`, the tool will cycle through a list of models until one succeeds.

**Customizing the lists via environment variables:**
- `HTML2MCQ_MCQ_MODELS`: Comma-separated list for the writer.
- `HTML2MCQ_OCR_MODELS`: Comma-separated list for the reader.

*Example:* `export HTML2MCQ_MCQ_MODELS="(openai)/gpt-4o,(gemini)/gemini-2.0-flash,llama-3.3-70b"`

---

## Operator Auto-Detection (`--operator auto`)

The tool can automatically detect which AI providers you have set up by scanning your environment variables.

When you use `provider="auto"` alongside `priority_list`, the tool becomes **Resilient Across Providers**. It will intelligently skip providers where keys are missing.

```bash
html2mcq tutorial.html --method auto --operator auto --mcq-model priority_list
```

### Independent Provider Routing
Use completely different AI providers for reading (OCR) and writing (MCQ) in the same run.

```bash
# Gemini reads the image, OpenAI writes the quiz.
html2mcq img.png --method auto --operator auto \
  --ocr-model "(gemini)/gemini-2.5-flash" \
  --mcq-model "(openai)/gpt-4o"
```

---

## Environment Variables

| Variable | Description |
|:---|:---|
| `OPENROUTER_API_KEY` | Key for OpenRouter provider |
| `ANTHROPIC_API_KEY` | Key for Anthropic provider |
| `OPENAI_API_KEY` | Key for OpenAI provider |
| `GEMINI_API_KEY` | Key for Gemini provider |
| `DEEPSEEK_API_KEY` | Key for DeepSeek provider |
| `GROQ_API_KEY` | Key for Groq provider |
| `MANUALAI_API_KEY` | Key for ManualAI provider |
| `MANUALAI_BASE_URL` | Base URL for ManualAI provider |
| `HTML2MCQ_MCQ_MODELS` | Default priority list for `mcq_model="priority_list"` |
| `HTML2MCQ_OCR_MODELS` | Default priority list for `ocr_model="priority_list"` |

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
