"""Smoke test for app.py"""
import json, os, sys, threading, time, urllib.error, urllib.request
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, root)
from http.server import HTTPServer
import importlib
spec = importlib.util.spec_from_file_location("app", os.path.join(root, "app.py"))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

srv = HTTPServer(("0.0.0.0", 5001), app.Handler)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
time.sleep(0.5)

ok = True

def check(name, cond, detail=""):
    global ok
    if cond:
        print("  PASS", name)
    else:
        print("  FAIL", name, detail)
        ok = False

# GET /
resp = urllib.request.urlopen("http://localhost:5001/")
html = resp.read().decode()
check("GET / contains html2mcq", "html2mcq" in html)
check("GET / contains v2.0.0", "v2.0.0" in html)

# POST /api/generate no key
data = json.dumps({"api_key":"","provider":"openrouter","tab":"url","url":"","n":1}).encode()
req = urllib.request.Request("http://localhost:5001/api/generate", data=data,
                             headers={"Content-Type":"application/json"})
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    check("POST /api/generate returns error", "error" in body)

# 404
try:
    urllib.request.urlopen("http://localhost:5001/xyz")
except urllib.error.HTTPError as e:
    check("GET /xyz returns 404", e.code == 404)

# UI elements
for eid in ("genBtn","apiKey","model","webUrl","pdfUrl","pdfFile","rawHtml","n","ocr","ci"):
    check(f"Element #{eid} present", eid in html)

srv.shutdown()
print()
sys.exit(0 if ok else 1)
