# html2mcq

**Convert any HTML tutorial page, PDF, or image into MCQ questions using AI.**

[![PyPI version](https://badge.fury.io/py/html2mcq.svg)](https://pypi.org/project/html2mcq/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

### **Processing Methods**

```text
┌───────────┬──────────────────────────────────────────────────────────┐
│ Method    │ Strategy (MANDATORY)                                     │
├───────────┼──────────────────────────────────────────────────────────┤
│ auto      │ Smart Choice (Recommended).                              │
│ onestep   │ Hybrid Vision (AI sees images + reads text).             │
│ twostep   │ AI-based OCR (AI reads text, then writes quiz).          │
│ tesseract │ Local OCR (Tesseract reads text, AI writes quiz).        │
└───────────┴──────────────────────────────────────────────────────────┘
```

---

## Key Features

- **Multi-Provider Support**: Gemini, DeepSeek, Groq, OpenAI, Anthropic, OpenRouter, and ManualAI.
- **Async Support**: Native `AsyncMCQGenerator` for high-performance integration.
- **LMS Export**: Direct export to **Aiken** and **Moodle XML** formats for easy course importing.
- **Native PDF Vision**: Sends raw PDF data directly to Gemini for highest extraction quality.
- **Resilient Retries**: Automatic exponential backoff for rate limits and transient errors.
- **Request Timeout**: All AI provider calls have a 70-second timeout to prevent hanging.
- **Hybrid Vision**: Simultaneous text + image analysis in `onestep` mode.
- **Smart Choice**: `method="auto"` intelligently chooses the best processing path.

---

## Request Timeout

All AI provider calls now pass `timeout=70` (seconds), ensuring every request returns within a reasonable window. This applies to all 10 synchronous backends (`_AnthropicBackend`, `_OpenAIBackend`, `_OpenRouterBackend`, `_OllamaBackend`, `_GeminiBackend`, `_DeepSeekBackend`, `_GroqBackend`, `_ManualAIBackend`), 2 async backends (`_AsyncAnthropicBackend`, `_AsyncOpenAIBackend`), and the vision helper methods (`_vision_mcq`, `_vision_mcq_pdf`, `_ocr_vision_call`).

Without this timeout, the OpenAI SDK's default is effectively infinite — a request to a slow or unresponsive model can hang your application indefinitely. The 70-second value balances the needs of complex PDF/image processing against responsiveness.

You can override the timeout by monkey-patching the backend after import, or pass a custom `timeout` for PDF downloads via `backend_kwargs`:

```python
gen = MCQGenerator(api_key="...", method="auto", timeout=120)
```

---

## Install

```bash
pip install html2mcq
```

Everything is included — HTML extraction, PDF support, OCR, all AI providers, and **native async support**.

---

## Quick Start

```python
from html2mcq import MCQGenerator

# Standard setup: Smart Mode (auto)
gen = MCQGenerator(
    api_key="sk-...",
    provider="openai",  # e.g. using Gemini via OpenAI endpoint
    method="auto",      # Now mandatory
    mcq_model="gemini-2.0-flash",
    explanation="normal",  # normal | shorter | off
)

# 1. From a Website (Auto-selects twostep)
mcq = gen.from_url("https://example.com/tutorial", n=5)

# 2. From a Scanned Image (Auto-selects onestep)
# Since we didn't specify ocr_model, 'auto' uses mcq_model for vision.
mcq = gen.from_image_paths("screenshot.png", n=5)

# 3. High-Accuracy AI OCR (Forced twostep)
# ocr_model reads the text, mcq_model writes the quiz.
mcq = gen.from_image_paths("blurry_notes.jpg", n=5, 
                           method="twostep", 
                           ocr_model="gemini-2.0-flash-pro")

print(mcq.to_pretty_str())
```

### Explanation control

Use `explanation="normal"`, `"shorter"`, or `"off"` to control the fixed MCQ explanation instruction. The same option is available in the CLI as `--explanation normal|shorter|off`.

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
-   **`auto`**: Use for 99% of cases. It resolves to `onestep` for images and `twostep` for PDFs/HTML.
-   **`onestep`**: Best for diagrams or complex layouts where the AI needs to "see" the visual relationship.
-   **`twostep`**: Best for documents with very dense text where you want the highest AI-based OCR accuracy.
-   **`tesseract`**: Best if you want to use your local machine for OCR (no extra API cost for reading) and only use the AI for writing the quiz.

---

## Examples (10+)

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
# gemini-flash will be used for both Reading and Writing
gen = MCQGenerator(
    api_key="sk-...",
    method="twostep",
    ocr_model="google/gemini-2.5-flash-lite"
)
mcq = gen.from_image_paths("screenshot.png", n=5)
```

### 8. Image URLs via local OCR (Tesseract)

```python
# Local Tesseract reads the image, Claude writes the quiz
gen = MCQGenerator(
    api_key="sk-...",
    method="tesseract",
    mcq_model="claude-3-5-sonnet-20241022"
)
mcq = gen.from_image_urls("https://example.com/diagram.png", n=5)
```

### 9. Vision-Direct (AI looks at image)

```python
# ocr_model is mandatory here and performs the entire task
gen = MCQGenerator(
    api_key="sk-...",
    method="onestep",
    ocr_model="google/gemini-2.5-flash-lite"
)
mcq = gen.from_image_paths("complex_diagram.png", n=3)
```

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

## Priority Lists

If you set `mcq_model="priority_list"` or `ocr_model="priority_list"`, the tool will cycle through a list of models until one succeeds. This is highly recommended for production reliability.

**Customizing the lists via environment variables:**
*   `HTML2MCQ_MCQ_MODELS`: Comma-separated list for the writer.
*   `HTML2MCQ_OCR_MODELS`: Comma-separated list for the reader.

*Example:* `export HTML2MCQ_MCQ_MODELS="(openai)/gpt-4o,(gemini)/gemini-2.0-flash,llama-3.3-70b"`

---

## API Reference

### `MCQGenerator` (Synchronous)

| Parameter | Default | Description |
|:---|:---|:---|
| `provider` | `"openrouter"` | AI provider (see list). Use `"auto"` for multi-provider routing. |
| `api_key` | `None` | API key (falls back to ENV vars) |
| `method` | `""` | **Mandatory**: `"auto"` \| `"onestep"` \| `"twostep"` \| `"tesseract"` |
| `mcq_model` | `""` | Model for MCQ generation. Falls back to `ocr_model`. Use `"priority_list"` for fallback. |
| `mcq_model_list` | `None` | Custom list of models for `mcq_model="priority_list"`. |
| `ocr_model` | `""` | Vision/OCR engine. **Mandatory** for `twostep`/`onestep`. Use `"priority_list"` for fallback. |
| `ocr_model_list` | `None` | Custom list of models for `ocr_model="priority_list"`. |
| `max_tokens` | `4096` | Max tokens for AI responses. |
| `manualai_base_url` | `""` | Base URL for the `manualai` provider |
| `ocr_fallback` | `True` | Fall back to Tesseract if AI OCR fails |
| `ocr_lang` | `"eng"` | Tesseract language code |
| `save_ocr_path` | `None` | Save extracted text to file |

### `AsyncMCQGenerator` (Asynchronous)

Inherits all parameters from `MCQGenerator`. All methods (`from_url`, `from_html`, etc.) are `async` and must be awaited.

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

## Native PDF Vision

When using `method="onestep"` with a PDF (and `provider="gemini"`), the tool bypasses PNG rendering and sends the **raw PDF bytes** directly to the AI. This ensures 100% accuracy of the original document layout and is significantly faster.

---

## Async Support

For high-performance applications (like FastAPI), use `AsyncMCQGenerator`:

```python
import asyncio
from html2mcq import AsyncMCQGenerator

async def main():
    gen = AsyncMCQGenerator(api_key="...", provider="openai", method="auto")
    
    # Non-blocking calls
    mcq = await gen.from_url("https://example.com/lesson")
    print(mcq.to_pretty_str())

asyncio.run(main())
```

---

## Hybrid Vision (One-Step HTML)

When you use `method="onestep"` for a website, the tool doesn't just read the text — it sends the actual images found on the page to the AI's "vision" eye. This is perfect for lessons that rely on diagrams.

```python
# Hybrid Mode: AI sees the text AND the diagrams at once
gen = MCQGenerator(method="onestep", ocr_model="google/gemini-2.0-flash")
mcq = gen.from_url("https://example.com/physics-lesson")
```

---

## Operator Auto-Detection (`--operator auto`)

The tool can automatically detect which AI providers you have set up by scanning your environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.).

When you use `provider="auto"` (or `--operator auto`) alongside `priority_list` for your models, the tool becomes **Resilient Across Providers**. It will intelligently skip providers where keys are missing and only attempt calls on valid ones.

```bash
# Example: Use all your available keys to ensure the quiz is generated!
html2mcq tutorial.html --method auto --operator auto --mcq-model priority_list
```

### Independent Provider Routing
You can even use completely different AI providers for reading (OCR) and writing (MCQ) in the same run!

```bash
# Gemini reads the image, OpenAI writes the quiz.
html2mcq img.png --method auto --operator auto \
  --ocr-model "(gemini)/gemini-2.5-flash" \
  --mcq-model "(openai)/gpt-4o"
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

## Operator-Aware Selection

You can target specific models for specific providers using the `(provider)/model_id` syntax. This is perfect for building a single configuration that works across different environments.

**Syntax:** `(provider)/model_id`

```bash
# Example: Only use Gemini if on Google, fallback to Llama otherwise.
export HTML2MCQ_MCQ_MODELS="(gemini)/gemini-2.0-flash,llama-3.3-70b"
```

| Match Type | Logic |
|:---|:---|
| **Specific** | `(openai)/gpt-4o` — Only used if active provider is **openai**. |
| **Universal** | `gpt-4o` — Used as a fallback for **any** provider. |


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
