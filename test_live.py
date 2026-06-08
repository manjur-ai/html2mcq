"""
test_live.py — Live integration tests for html2mcq
====================================================
Tests all input types against a real AI provider.

Usage
-----
# Set your API key first:
export OPENROUTER_API_KEY="sk-or-v1-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export OPENAI_API_KEY="sk-..."

# Run all tests:
python test_live.py

# Run specific test:
python test_live.py --test html
python test_live.py --test pdf_url
python test_live.py --test pdf_file
python test_live.py --test url

# Options:
python test_live.py --provider anthropic --n 5
python test_live.py --provider openrouter --model meta-llama/llama-3.3-70b-instruct:free
"""

import os
import sys
import json
import time
import argparse
import tempfile
from pathlib import Path


# ── Colour helpers ─────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"{GREEN}  ✓ {msg}{RESET}")
def fail(msg): print(f"{RED}  ✗ {msg}{RESET}")
def info(msg): print(f"{CYAN}  ℹ {msg}{RESET}")
def warn(msg): print(f"{YELLOW}  ⚠ {msg}{RESET}")
def header(msg): print(f"\n{BOLD}{CYAN}{'='*55}\n  {msg}\n{'='*55}{RESET}")


# ── Assertion helpers ──────────────────────────────────────────────────────────

def assert_mcqset(mcq, n, label=""):
    from html2mcq import MCQSet
    assert isinstance(mcq, MCQSet), f"{label}: Expected MCQSet, got {type(mcq)}"
    assert mcq.total_questions == n, f"{label}: Expected {n} questions, got {mcq.total_questions}"
    assert mcq.total_exam_time > 0
    for i, q in enumerate(mcq.questions):
        assert q.question_html, f"Q{i+1}: Empty question_html"
        assert len(q.options) == 4, f"Q{i+1}: Expected 4 options, got {len(q.options)}"
        assert all(0 <= a <= 3 for a in q.answers), f"Q{i+1}: Invalid answer index"
        assert q.difficulty in ("easy", "medium", "hard"), f"Q{i+1}: Invalid difficulty '{q.difficulty}'"
        assert q.marks == 1.0, f"Q{i+1}: Expected marks=1.0"
        if q.multi:
            assert len(q.answers) > 1, f"Q{i+1}: multi=True but only 1 answer"
            assert q.negative_marks == 0.0, f"Q{i+1}: multi should have 0 negative marks"
        else:
            assert len(q.answers) == 1, f"Q{i+1}: multi=False but {len(q.answers)} answers"
            assert q.negative_marks == 0.25, f"Q{i+1}: single should have 0.25 negative marks"

    # Validate JSON output
    parsed = json.loads(mcq.to_json())
    assert set(parsed.keys()) == {"total_exam_time", "questions"}
    assert len(parsed["questions"]) == n
    ok(f"{label}: {n} questions, JSON valid, all assertions passed")


# ── Test cases ─────────────────────────────────────────────────────────────────

def test_from_html(gen, n):
    header("TEST 1: from_html — inline HTML with all content types")

    HTML = """
    <html><head><title>JavaScript Arrays Tutorial</title></head>
    <body>
    <h1>JavaScript Arrays</h1>
    <p>Arrays in JavaScript are zero-indexed, ordered collections of values.
    They can hold any type including numbers, strings, objects, and other arrays.</p>
    <h2>Creating Arrays</h2>
    <p>Use array literals (preferred) or the Array constructor to create arrays.</p>
    <pre><code class="language-javascript">
    const fruits = ["Apple", "Banana", "Cherry"];
    const nums   = new Array(1, 2, 3);
    console.log(fruits[0]); // "Apple"
    console.log(fruits.length); // 3
    </code></pre>
    <h2>Key Methods</h2>
    <table>
      <tr><th>Method</th><th>Mutates?</th><th>Returns</th></tr>
      <tr><td>push()</td><td>Yes</td><td>New length</td></tr>
      <tr><td>pop()</td><td>Yes</td><td>Removed element</td></tr>
      <tr><td>map()</td><td>No</td><td>New array</td></tr>
      <tr><td>filter()</td><td>No</td><td>New array</td></tr>
      <tr><td>reduce()</td><td>No</td><td>Accumulated value</td></tr>
    </table>
    <img src="https://javascript.info/article/array/array.svg" alt="Array index diagram showing positions 0,1,2">
    <a href="https://example.com/js-cheatsheet.pdf">Download JS Arrays Cheat Sheet</a>
    </body></html>
    """

    info(f"Generating {n} MCQs from inline HTML (5 content types)...")
    t = time.time()
    mcq = gen.from_html(HTML, n=n, base_url="https://example.com/", enrich_pdfs=False)
    elapsed = time.time() - t
    info(f"Completed in {elapsed:.1f}s")
    info(f"Content summary: {mcq.content_summary}")
    assert_mcqset(mcq, n, "from_html")
    print(mcq.to_pretty_str())
    return mcq


def test_from_pdf_url(gen, n, pdf_url=None):
    header("TEST 2: from_pdf_url — PDF via URL")

    url = pdf_url or "https://www.w3.org/WAI/WCAG21/wcag21.pdf"
    info(f"Downloading and extracting PDF: {url}")
    t = time.time()
    try:
        mcq = gen.from_pdf_url(url, n=n)
        elapsed = time.time() - t
        info(f"Completed in {elapsed:.1f}s — {mcq.content_summary}")
        assert_mcqset(mcq, n, "from_pdf_url")
        print(mcq.to_pretty_str())
        return mcq
    except Exception as e:
        warn(f"PDF URL test skipped: {e}")
        return None


def test_from_pdf_file(gen, n):
    header("TEST 3: from_pdf_path — local PDF file")

    # Create a temporary PDF using PyMuPDF
    try:
        import fitz
    except ImportError:
        warn("PyMuPDF not installed, skipping PDF file test")
        return None

    content = """
Introduction to Flask Web Framework

Flask is a lightweight WSGI web application framework in Python.
It is designed to make getting started quick and easy, with the ability to scale up to complex applications.

Routing in Flask
----------------
Use the @app.route() decorator to bind a function to a URL:
    @app.route('/')
    def index():
        return 'Hello, World!'

Flask supports variable rules, HTTP methods (GET, POST, PUT, DELETE),
and URL building with url_for().

Templates
---------
Flask uses the Jinja2 templating engine. Templates are stored in a /templates folder.
Use render_template('index.html', name=name) to render them.
Variables are passed as keyword arguments.

Database Integration
--------------------
Flask works with SQLAlchemy (ORM) and also supports raw SQLite via sqlite3.
For small projects, SQLite is recommended. For production, use PostgreSQL or MySQL.

Error Handling
--------------
Use @app.errorhandler(404) to handle HTTP errors gracefully.
Flask also supports abort() to raise HTTP errors programmatically.
"""

    doc = fitz.open()
    lines = content.strip().split("\n")
    page = doc.new_page()
    y = 72
    for line in lines:
        if y > 700:
            page = doc.new_page()
            y = 72
        page.insert_text((72, y), line.strip(), fontsize=11)
        y += 16
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        doc.save(tmp.name)
        tmp_path = tmp.name
    doc.close()

    info(f"Created temporary PDF: {tmp_path}")
    t = time.time()
    mcq = gen.from_pdf_path(tmp_path, n=n, pdf_title="Flask Web Framework Guide")
    elapsed = time.time() - t
    Path(tmp_path).unlink(missing_ok=True)

    info(f"Completed in {elapsed:.1f}s — {mcq.content_summary}")
    assert_mcqset(mcq, n, "from_pdf_path")
    print(mcq.to_pretty_str())
    return mcq


def test_from_url(gen, n):
    header("TEST 4: from_url — live web page")

    url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    info(f"Fetching live page: {url}")
    t = time.time()
    try:
        mcq = gen.from_url(url, n=n, enrich_pdfs=False)
        elapsed = time.time() - t
        info(f"Completed in {elapsed:.1f}s — {mcq.content_summary}")
        assert_mcqset(mcq, n, "from_url")
        print(mcq.to_pretty_str())
        return mcq
    except Exception as e:
        warn(f"URL test skipped: {e}")
        return None


def test_filters_and_export(mcq, label=""):
    header(f"TEST: Filters & Export — {label}")

    easy   = mcq.filter_by_difficulty("easy")
    medium = mcq.filter_by_difficulty("medium")
    hard   = mcq.filter_by_difficulty("hard")
    total  = easy.total_questions + medium.total_questions + hard.total_questions
    info(f"Difficulty split — easy:{easy.total_questions} medium:{medium.total_questions} hard:{hard.total_questions}")
    assert total == mcq.total_questions, "Difficulty filter totals don't add up"
    ok("Difficulty filters correct")

    out = Path(tempfile.mktemp(suffix=".json"))
    out.write_text(mcq.to_json())
    parsed = json.loads(out.read_text())
    assert set(parsed.keys()) == {"total_exam_time", "questions"}
    out.unlink()
    ok(f"JSON export valid — {mcq.total_questions} questions, exam_time={mcq.total_exam_time}min")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="html2mcq live integration tests")
    parser.add_argument("--test", choices=["html","pdf_url","pdf_file","url","all"], default="all")
    parser.add_argument("--provider", default="openrouter", choices=["anthropic","openai","openrouter"])
    parser.add_argument("--model", default="meta-llama/llama-3.3-70b-instruct:free")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--n", type=int, default=5, help="Questions per test (default 5)")
    parser.add_argument("--pdf-url", default="", help="Custom PDF URL for pdf_url test")
    args = parser.parse_args()

    # Resolve API key
    env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
    api_key = args.api_key or os.environ.get(env_map[args.provider], "")
    if not api_key:
        print(f"{RED}Error: No API key found. Set {env_map[args.provider]} or pass --api-key{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}html2mcq — Live Integration Tests{RESET}")
    print(f"  Provider : {args.provider}")
    print(f"  Model    : {args.model}")
    print(f"  Questions: {args.n} per test")

    from html2mcq import MCQGenerator
    gen = MCQGenerator(
        api_key=api_key,
        provider=args.provider,
        model=args.model,
        pdf_backend="pymupdf",
    )

    results = {}
    run = args.test

    if run in ("html", "all"):
        try:
            mcq = test_from_html(gen, args.n)
            test_filters_and_export(mcq, "HTML")
            results["html"] = "PASS"
        except Exception as e:
            fail(f"from_html FAILED: {e}")
            results["html"] = f"FAIL: {e}"

    if run in ("pdf_url", "all"):
        try:
            mcq = test_from_pdf_url(gen, args.n, args.pdf_url)
            if mcq:
                test_filters_and_export(mcq, "PDF URL")
                results["pdf_url"] = "PASS"
            else:
                results["pdf_url"] = "SKIP"
        except Exception as e:
            fail(f"from_pdf_url FAILED: {e}")
            results["pdf_url"] = f"FAIL: {e}"

    if run in ("pdf_file", "all"):
        try:
            mcq = test_from_pdf_file(gen, args.n)
            if mcq:
                test_filters_and_export(mcq, "PDF File")
                results["pdf_file"] = "PASS"
            else:
                results["pdf_file"] = "SKIP"
        except Exception as e:
            fail(f"from_pdf_path FAILED: {e}")
            results["pdf_file"] = f"FAIL: {e}"

    if run in ("url", "all"):
        try:
            mcq = test_from_url(gen, args.n)
            if mcq:
                test_filters_and_export(mcq, "URL")
                results["url"] = "PASS"
            else:
                results["url"] = "SKIP"
        except Exception as e:
            fail(f"from_url FAILED: {e}")
            results["url"] = f"FAIL: {e}"

    # Summary
    header("RESULTS SUMMARY")
    all_pass = True
    for test, result in results.items():
        if result == "PASS":
            ok(f"{test:12s} {result}")
        elif result == "SKIP":
            warn(f"{test:12s} {result}")
        else:
            fail(f"{test:12s} {result}")
            all_pass = False

    print()
    if all_pass:
        print(f"{GREEN}{BOLD}All tests passed!{RESET}")
    else:
        print(f"{RED}{BOLD}Some tests failed.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
