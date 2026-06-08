"""Minimal Playwright test for html2mcq_web.py."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from html2mcq_web import Handler

from playwright.sync_api import sync_playwright

# Start server
srv = HTTPServer(("0.0.0.0", 5000), Handler)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
time.sleep(0.5)

pass_count = 0
fail_count = 0

def check(name, ok, detail=""):
    global pass_count, fail_count
    if ok:
        print(f"  \u2713 {name}")
        pass_count += 1
    else:
        print(f"  \u2717 {name}: {detail}")
        fail_count += 1

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    # 1. Page loads
    page.goto("http://localhost:5000", wait_until="networkidle")
    title_ok = "html2mcq" in page.title()
    version_ok = "v2.0.0" in page.content()
    check("Page loads", title_ok and version_ok, f"title={page.title()}")

    # 2. All UI elements
    for eid in ("apiKey", "model", "webUrl", "generateBtn"):
        el = page.locator(f"#{eid}")
        check(f"Element #{eid} visible", el.is_visible())

    # 3. Tab switching
    page.click(".tab-btn[data-tab='pdfurl']")
    check("PDF URL tab shows pdfUrl input", page.locator("#pdfUrl").is_visible())
    page.click(".tab-btn[data-tab='html']")
    check("Raw HTML tab shows rawHtml input", page.locator("#rawHtml").is_visible())
    page.click(".tab-btn[data-tab='url']")
    check("Web URL tab shows webUrl input", page.locator("#webUrl").is_visible())

    # 4. Provider switches model
    page.locator("input[name='provider'][value='anthropic']").click()
    page.wait_for_timeout(200)
    val = page.locator("#model").input_value()
    check("Anthropic sets model to claude-opus-4-6", val == "claude-opus-4-6", val)

    page.locator("input[name='provider'][value='openrouter']").click()
    page.wait_for_timeout(200)
    val = page.locator("#model").input_value()
    check("OpenRouter sets model to default", "meta-llama" in val, val)

    # 5. Format toggle
    page.locator("input[name='format'][value='json']").click()
    check("JSON format radio checked", page.locator("input[name='format'][value='json']").is_checked())

    # 6. PDF file picker
    page.click(".tab-btn[data-tab='pdffile']")
    # Use a temp file named .pdf to test
    tmp_pdf = os.path.join(os.path.dirname(__file__), "_fake.pdf")
    try:
        with open(tmp_pdf, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        page.locator("#pdfFile").set_input_files(tmp_pdf)
        check("PDF file picker accepts file", True)
    finally:
        if os.path.exists(tmp_pdf):
            os.unlink(tmp_pdf)

    # 7. API returns error without key
    page.click(".tab-btn[data-tab='url']")
    page.fill("#webUrl", "https://example.com")
    page.fill("#apiKey", "")
    page.click("#generateBtn")
    # Wait for error flash or status update
    try:
        page.wait_for_function("() => document.getElementById('errorFlash').style.display !== 'none'", timeout=8000)
        check("API returns error without key", True)
    except Exception as e:
        check("API returns error without key", False, str(e))

    # 8. Direct API call
    try:
        data = json.dumps({"api_key":"","provider":"openrouter","tab":"url","url":"","n":1}).encode()
        req = urllib.request.Request("http://localhost:5000/api/generate", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            check("POST /api/generate returns JSON error", "error" in body, body.get("error","")[:60])
    except Exception as e:
        check("POST /api/generate direct call", False, str(e))

    browser.close()

print(f"\n{'='*40}")
print(f"  {pass_count} passed, {fail_count} failed")
srv.shutdown()
sys.exit(0 if fail_count == 0 else 1)
