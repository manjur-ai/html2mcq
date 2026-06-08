"""Smoke test for html2mcq_web.py Flask server."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import html2mcq_web
from werkzeug.serving import make_server

srv = make_server("0.0.0.0", 5000, html2mcq_web.app)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
time.sleep(1)

try:
    # Test 1: GET / returns HTML
    resp = urllib.request.urlopen("http://localhost:5000/")
    html = resp.read().decode()
    assert "html2mcq" in html
    assert "v2.0.0" in html
    print("\u2713 GET / returns HTML page with v2.0.0")

    # Test 2: POST /api/generate with missing fields returns error
    data = json.dumps({"api_key": "", "provider": "openrouter", "tab": "url", "url": "", "n": 1}).encode()
    req = urllib.request.Request("http://localhost:5000/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        assert "error" in body
        print(f"\u2713 POST /api/generate (bad request) returns error: {body.get('error', '')[:60]}")

    # Test 3: HTML page has required UI elements
    for eid in ("generateBtn", "webUrl", "pdfUrl", "pdfFile", "rawHtml", "apiKey", "model"):
        assert eid in html, f"Missing element: {eid}"
    print("\u2713 HTML page has all required UI elements")

    print("\nAll smoke tests passed!")

finally:
    srv.shutdown()
    time.sleep(0.5)
