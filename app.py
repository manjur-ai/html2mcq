"""
app.py — Self-contained web UI for html2mcq (zero deps)
=======================================================
Usage:  python app.py   →  http://localhost:5000
"""

import base64, json, os, re, sys, tempfile, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Pull default models from the library so we stay in sync
from html2mcq.generator import (
    _OpenRouterBackend,
    _OpenAIBackend,
    _AnthropicBackend,
    _OllamaBackend,
)

PORT = int(os.environ.get("PORT", 5000))

DEFAULT_MODELS = {
    "openrouter": _OpenRouterBackend.DEFAULT_MODEL,
    "openai": _OpenAIBackend.DEFAULT_MODEL,
    "anthropic": _AnthropicBackend.DEFAULT_MODEL,
    "ollama": _OllamaBackend.DEFAULT_MODEL,
}

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>html2mcq — MCQ Generator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,'Segoe UI',sans-serif;background:#1e1e2e;color:#e2e8f0;min-height:100vh}
:root{--bg:#1e1e2e;--bg2:#2a2a3e;--card:#252538;--accent:#7c3aed;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--dim:#94a3b8;--input:#1a1a2e;--border:#3f3f5a}
header{background:var(--accent);padding:12px 24px;display:flex;align-items:center;gap:14px}
header h1{font-size:18px;font-weight:700;color:#fff}
header span{font-size:12px;color:#ddd6fe}
.layout{display:flex;gap:14px;padding:14px;height:calc(100vh - 50px)}
.left{width:420px;min-width:420px;overflow-y:auto}
.left::-webkit-scrollbar{width:5px}
.left::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.section{display:flex;align-items:center;gap:8px;margin:12px 0 6px;font-size:13px;font-weight:600}
.section hr{flex:1;border:none;border-top:1px solid var(--border)}
.card{background:var(--card);padding:12px;border-radius:6px;margin-bottom:6px}
.row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.row:last-child{margin-bottom:0}
.row label{color:var(--dim);font-size:12px;min-width:80px;white-space:nowrap}
input,textarea,select{background:var(--input);color:var(--text);border:none;border-radius:4px;padding:7px 8px;font-size:12px;font-family:inherit;width:100%;outline:none}
input:focus,textarea:focus{box-shadow:0 0 0 2px var(--accent)}
.radio-group{display:flex;gap:6px;flex-wrap:wrap}
.radio-group label{cursor:pointer;display:flex;align-items:center;gap:4px;min-width:auto;color:var(--text);font-size:12px}
.radio-group input[type=radio]{accent-color:var(--accent);width:14px}
.chk{display:flex;gap:12px;margin-top:6px}
.chk label{display:flex;align-items:center;gap:4px;cursor:pointer;min-width:auto;color:var(--text);font-size:12px}
.chk input{accent-color:var(--accent);width:14px}
.tabs{display:flex;gap:2px}
.tab-btn{padding:7px 10px;font-size:11px;background:var(--bg2);color:var(--dim);border:none;cursor:pointer;border-radius:4px 4px 0 0;flex:1}
.tab-btn.active{background:var(--card);color:#fff;font-weight:600}
.tab-btn:hover{background:var(--border)}
.tab-pane{display:none;padding:10px 0}
.tab-pane.active{display:block}
.btn{background:var(--accent);color:#fff;border:none;border-radius:4px;padding:9px 14px;font-size:12px;font-weight:600;cursor:pointer}
.btn:hover{opacity:.9}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-block{width:100%;margin-top:8px}
.right{flex:1;display:flex;flex-direction:column;min-width:0}
.toolbar{background:var(--bg2);padding:6px 12px;border-radius:6px;display:flex;align-items:center;gap:8px;margin-bottom:6px}
.toolbar h2{font-size:13px;font-weight:700;margin-right:8px}
.toolbar .spacer{flex:1}
.stats{background:var(--border);padding:5px 10px;border-radius:4px;font-size:11px;color:var(--dim);margin-bottom:6px;min-height:24px}
.output{flex:1;background:var(--input);border-radius:6px;padding:10px;font-family:Consolas,'Courier New',monospace;font-size:12px;overflow:auto;white-space:pre-wrap;word-break:break-word;line-height:1.5;resize:none;border:none;color:var(--text)}
.output .h{color:var(--accent);font-weight:700}
.output .c{color:var(--green)}
.output .o{color:var(--text)}
.output .m{color:var(--dim);font-size:11px}
.output .e{color:var(--green)}
.output .m2{color:var(--yellow)}
.output .h2{color:var(--red)}
.output .mu{color:var(--yellow)}
.status{font-size:11px;color:var(--dim);margin-top:4px}
.error{background:var(--red);color:#fff;padding:8px 12px;border-radius:4px;margin-bottom:6px;display:none;font-size:12px}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--dim);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
</style>
</head>
<body>

<header>
  <h1>&#9889; html2mcq</h1>
  <span>v2.0.0 &bull; AI-powered MCQ Generator</span>
</header>

<div class="layout">

<div class="left">

<div class="section">&#128273; API<hr></div>
<div class="card">
  <div class="row">
    <label>Provider</label>
    <div class="radio-group">
      <label><input type="radio" name="provider" value="anthropic"> anthropic</label>
      <label><input type="radio" name="provider" value="openai"> openai</label>
      <label><input type="radio" name="provider" value="openrouter" checked> openrouter</label>
    </div>
  </div>
  <div class="row">
    <label>API Key</label>
    <input type="password" id="apiKey" placeholder="sk-...">
  </div>
  <div class="row">
    <label>Model</label>
    <input type="text" id="model" value="__MODEL__" list="models">
    <datalist id="models">
      <option value="__MODEL__">
      <option value="google/gemini-2.5-flash-lite">
      <option value="google/gemma-3-27b-it">
      <option value="google/gemma-3-12b-it">
      <option value="openai/gpt-4o">
      <option value="openai/gpt-4o-mini">
      <option value="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free">
      <option value="claude-opus-4-6">
      <option value="claude-sonnet-4-6">
      <option value="qwen2.5:7b">
    </datalist>
  </div>
</div>

<div class="section">&#128229; Input<hr></div>
<div class="card" style="padding:0 12px 12px">
  <div class="tabs">
    <button class="tab-btn active" data-tab="url">Web URL</button>
    <button class="tab-btn" data-tab="pdfurl">PDF URL</button>
    <button class="tab-btn" data-tab="pdfile">Local PDF</button>
    <button class="tab-btn" data-tab="html">Raw HTML</button>
  </div>
  <div class="tab-pane active" id="tp-url">
    <input type="text" id="webUrl" placeholder="https://docs.python.org/3/tutorial/" style="margin-top:8px">
    <div class="chk">
      <label><input type="checkbox" id="enrichPdfs" checked> Extract PDF links</label>
      <label><input type="checkbox" id="enrichImages" checked> OCR images</label>
    </div>
  </div>
  <div class="tab-pane" id="tp-pdfurl">
    <input type="text" id="pdfUrl" placeholder="https://example.com/doc.pdf" style="margin-top:8px">
    <input type="text" id="pdfUrlTitle" placeholder="Title (optional)" style="margin-top:6px">
  </div>
  <div class="tab-pane" id="tp-pdfile">
    <input type="file" id="pdfFile" accept=".pdf" style="margin-top:8px">
    <input type="text" id="pdfFileTitle" placeholder="Title (optional)" style="margin-top:6px">
  </div>
  <div class="tab-pane" id="tp-html">
    <textarea id="rawHtml" rows="4" placeholder="Paste HTML here..." style="margin-top:8px;font-family:Consolas,monospace;font-size:11px;resize:vertical"></textarea>
    <input type="text" id="baseUrl" placeholder="Base URL for relative links (optional)" style="margin-top:6px">
  </div>
</div>

<div class="section">&#9881; Options<hr></div>
<div class="card">
  <div class="row">
    <label>Questions</label>
    <input type="number" id="n" value="10" min="1" max="100" style="width:70px">
    <label style="min-width:auto;margin-left:10px">Batch</label>
    <input type="number" id="batch" value="10" min="1" max="30" style="width:60px">
  </div>
  <div class="row">
    <label>Difficulty</label>
    <input type="text" id="diff" placeholder='e.g. 40% easy, 40% medium, 20% hard'>
  </div>
  <div class="row">
    <label>Topics</label>
    <input type="text" id="topics" placeholder="loops, functions, OOP">
  </div>
  <div class="row">
    <label>OCR model</label>
    <input type="text" id="ocr" value="pytesseract" list="ocrs">
    <datalist id="ocrs">
      <option value="pytesseract">
      <option value="auto">
      <option value="google/gemini-2.5-flash-lite">
      <option value="google/gemma-3-27b-it">
      <option value="google/gemma-3-12b-it">
      <option value="openai/gpt-4o">
    </datalist>
  </div>
  <label style="display:block;margin:6px 0 4px;color:var(--dim);font-size:12px">Custom instructions</label>
  <textarea id="ci" rows="3" style="resize:vertical">e.g. Make answers very close and confusing. Only people with sharp attention should get 100%. Avoid straightforward questions.</textarea>
</div>

<button class="btn btn-block" id="genBtn">&#9889; Generate MCQs</button>
<div class="status" id="status">Ready</div>
</div>

<div class="right">
  <div class="toolbar">
    <h2>&#128203; Output</h2>
    <div class="radio-group">
      <label><input type="radio" name="fmt" value="pretty" checked> PRETTY</label>
      <label><input type="radio" name="fmt" value="json"> JSON</label>
    </div>
    <div class="spacer"></div>
    <button class="btn" id="copyBtn" style="padding:5px 10px;font-size:11px">&#128203; Copy</button>
    <button class="btn" id="clearBtn" style="padding:5px 10px;font-size:11px">&#128465; Clear</button>
    <button class="btn" id="saveBtn" style="padding:5px 10px;font-size:11px">&#128190; Save</button>
  </div>
  <div class="stats" id="stats">No results yet</div>
  <div class="error" id="err"></div>
  <div class="output" id="out"></div>
</div>

</div>

<script>
const $ = id => document.getElementById(id);
const Q = s => document.querySelector(s);
const QA = s => document.querySelectorAll(s);

// tabs
QA('.tab-btn').forEach(b => b.onclick = () => {
  QA('.tab-btn').forEach(x => x.classList.remove('active'));
  QA('.tab-pane').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('tp-'+b.dataset.tab).classList.add('active');
});

// provider -> model
const DM = __DEFAULT_MODELS__;
QA('input[name="provider"]').forEach(r => r.onchange = () => {
  $('model').value = DM[r.value] || '';
});

// PDF file -> auto title
$('pdfFile').onchange = e => {
  const f = e.target.files[0];
  if (!f||$('pdfFileTitle').value) return;
  $('pdfFileTitle').value = f.name.replace(/\.pdf$/i,'').replace(/[-_]/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
};

// CI placeholder
const CI = $('ci'), CIP = CI.value;
CI.style.color = '#94a3b8';
CI.onfocus = () => { if(CI.value===CIP){CI.value='';CI.style.color='#e2e8f0'} };
CI.onblur = () => { if(!CI.value.trim()){CI.value=CIP;CI.style.color='#94a3b8'} };

// generate
$('genBtn').onclick = generate;

async function generate() {
  const out = $('out'), stats = $('stats'), err = $('err'), status = $('status'), btn = $('genBtn');
  err.style.display = 'none';
  out.innerHTML = '';
  stats.textContent = 'Generating...';
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating...';
  status.textContent = 'Initialising...';

  const provider = Q('input[name="provider"]:checked').value;
  const tab = Q('.tab-btn.active').dataset.tab;

  const body = {
    api_key: $('apiKey').value,
    provider,
    model: $('model').value,
    n: parseInt($('n').value)||10,
    batch_size: parseInt($('batch').value)||10,
    difficulty_mix: $('diff').value||null,
    focus_topics: $('topics').value||null,
    ocr_model: $('ocr').value,
    custom_instructions: (CI.value===CIP||!CI.value.trim())?'':CI.value,
    tab,
  };

  if (tab==='url') {
    body.url = $('webUrl').value;
    body.enrich_pdfs = $('enrichPdfs').checked;
    body.enrich_images = $('enrichImages').checked;
  } else if (tab==='pdfurl') {
    body.url = $('pdfUrl').value;
    body.pdf_title = $('pdfUrlTitle').value;
  } else if (tab==='pdfile') {
    const fi = $('pdfFile');
    if (!fi.files[0]) return showErr('Select a PDF file.');
    body.pdf_title = $('pdfFileTitle').value;
    body.pdf_data = await readB64(fi.files[0]);
  } else if (tab==='html') {
    body.html = $('rawHtml').value;
    body.base_url = $('baseUrl').value;
  }

  try {
    const resp = await fetch('/api/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) return showErr(data.error||'Request failed');
    render(data);
  } catch(e) { showErr(e.message) }
  finally { btn.disabled=false; btn.innerHTML='&#9889; Generate MCQs' }
}

function readB64(f) {
  return new Promise((ok,no) => { const r=new FileReader(); r.onload=()=>ok(r.result.split(',')[1]); r.onerror=no; r.readAsDataURL(f) });
}

function showErr(m) {
  const e=$('err'); e.textContent=m; e.style.display='block';
  $('status').textContent='Error: '+m;
  $('stats').textContent='Error';
  $('out').innerHTML='<span class="m">ERROR:\n'+esc(m)+'</span>';
  $('genBtn').disabled=false; $('genBtn').innerHTML='&#9889; Generate MCQs';
}

function render(data) {
  if (data.error) return showErr(data.error);
  const fmt = Q('input[name="fmt"]:checked').value;
  $('out').innerHTML = fmt==='json' ? esc(JSON.stringify(data.mcq,null,2)) : pretty(data.mcq);
  const s = data.summary;
  $('stats').innerHTML = '&#10003; '+s.total_questions+' q &bull; E:'+s.easy+' M:'+s.medium+' H:'+s.hard+' &bull; Multi:'+s.multi+' &bull; '+s.exam_time+'min &bull; '+esc(s.content_summary);
  $('status').textContent = 'Done — '+s.total_questions+' questions.';
  window._md = data.mcq; window._ms = data.summary;
}

function pretty(mcq) {
  let h = '<span class="h">'+'='.repeat(56)+'\n  '+esc(mcq.page_title)+'\n  Source: '+esc(mcq.source_url||'N/A')+'\n  Q: '+mcq.total_questions+' | Time: '+mcq.total_exam_time+'min\n  '+esc(mcq.content_summary)+'\n'+'='.repeat(56)+'\n\n</span>';
  mcq.questions.forEach((q,i)=>{
    h += '<span class="h">Q'+(i+1)+'.</span> <span class="'+q.difficulty+'">['+q.difficulty.toUpperCase()+']</span>';
    if (q.multi) h+=' <span class="mu">[MULTI]</span>';
    h += ' '+esc(q.question_html)+'\n<span class="m">  +'+q.marks+'/-'+q.negative_marks+'</span>\n';
    q.options.forEach((o,j)=>{
      const k = q.answers.indexOf(j)!==-1;
      h += '<span class="'+(k?'c':'o')+'">'+(k?'\u2713 ':'   ')+String.fromCharCode(65+j)+') '+esc(o)+'\n</span>';
    });
    if (q.explanation) h+='<span class="m">  \uD83D\uDCA1 '+esc(q.explanation)+'\n</span>';
    h+='\n';
  });
  return h;
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }

// format toggle
QA('input[name="fmt"]').forEach(r => r.onchange = () => { if(window._md) render({mcq:window._md,summary:window._ms}) });

// copy
$('copyBtn').onclick = async () => {
  const t = $('out').textContent;
  if (!t) return;
  try { await navigator.clipboard.writeText(t); $('status').textContent='Copied!' }
  catch { const ta=document.createElement('textarea'); ta.value=t; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); $('status').textContent='Copied!' }
};

// clear
$('clearBtn').onclick = () => { $('out').innerHTML=''; $('stats').textContent='No results yet'; $('status').textContent='Ready'; window._md=null };

// save
$('saveBtn').onclick = () => {
  if (!window._md) return showErr('Generate first.');
  const t = (window._md.page_title||'mcq').replace(/[\/\\?*:<>|]/g,'_').slice(0,30);
  const b = new Blob([JSON.stringify(window._md,null,2)],{type:'application/json'});
  const a = document.createElement('a'); a.href=URL.createObjectURL(b); a.download=t+'_mcq.json'; a.click(); URL.revokeObjectURL(a.href);
  $('status').textContent='Saved as '+a.download;
};
</script>
</body>
</html>"""

HTML = HTML.replace("__MODEL__", DEFAULT_MODELS["openrouter"])
HTML = HTML.replace("__DEFAULT_MODELS__", json.dumps(DEFAULT_MODELS))


# ── HTTP server ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._html(200, HTML)
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/generate":
            self._generate()
        else:
            self._json(404, {"error": "Not found"})

    def _generate(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError, TypeError):
            return self._json(400, {"error": "Invalid JSON"})

        try:
            from html2mcq import MCQGenerator

            api_key = (data.get("api_key") or "").strip()
            provider = data.get("provider", "openrouter")
            model = data.get("model", "")
            n = int(data.get("n", 10))
            batch_size = int(data.get("batch_size", 10))
            diff = data.get("difficulty_mix") or None
            topics_raw = data.get("focus_topics") or ""
            topics = [t.strip() for t in topics_raw.split(",") if t.strip()] or None
            ci = data.get("custom_instructions") or None
            ocr_model = data.get("ocr_model", "pytesseract")
            tab = data.get("tab", "url")

            env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
            if not api_key:
                api_key = os.environ.get(env_map.get(provider, ""), "")
            if not api_key:
                raise ValueError(f"No API key. Set {env_map[provider]} env var or enter above.")

            gen = MCQGenerator(
                api_key=api_key, provider=provider, mcq_model=model,
                batch_size=batch_size, ocr_model=ocr_model,
                method="twostep", custom_instructions=ci,
            )

            if tab == "url":
                url = data.get("url", "").strip()
                if not url:
                    return self._json(400, {"error": "Enter a URL."})
                mcq = gen.from_url(url, n=n, difficulty_mix=diff, focus_topics=topics,
                                   enrich_pdfs=bool(data.get("enrich_pdfs", True)),
                                   enrich_images=bool(data.get("enrich_images", True)),
                                   custom_instructions=ci)
            elif tab == "pdfurl":
                url = data.get("url", "").strip()
                if not url:
                    return self._json(400, {"error": "Enter a PDF URL."})
                mcq = gen.from_pdf_url(url, n=n, pdf_title=data.get("pdf_title", "").strip(),
                                       difficulty_mix=diff, focus_topics=topics, custom_instructions=ci)
            elif tab == "pdfile":
                pdf_data = data.get("pdf_data")
                if not pdf_data:
                    return self._json(400, {"error": "Select a PDF file."})
                pdf_bytes = base64.b64decode(pdf_data)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(pdf_bytes); tmp = f.name
                try:
                    mcq = gen.from_pdf_path(tmp, n=n, pdf_title=data.get("pdf_title", "").strip(),
                                            difficulty_mix=diff, focus_topics=topics, custom_instructions=ci)
                finally:
                    try: os.unlink(tmp)
                    except: pass
            elif tab == "html":
                html = data.get("html", "").strip()
                if not html:
                    return self._json(400, {"error": "Paste HTML content."})
                mcq = gen.from_html(html, n=n, base_url=data.get("base_url", "").strip(),
                                    difficulty_mix=diff, focus_topics=topics,
                                    enrich_pdfs=False, enrich_images=True, custom_instructions=ci)
            else:
                return self._json(400, {"error": f"Unknown tab: {tab}"})

            easy = sum(1 for q in mcq.questions if q.difficulty == "easy")
            medium = sum(1 for q in mcq.questions if q.difficulty == "medium")
            hard = sum(1 for q in mcq.questions if q.difficulty == "hard")
            multi = sum(1 for q in mcq.questions if q.multi)

            return self._json(200, {
                "mcq": json.loads(mcq.to_json()),
                "summary": {"total_questions": mcq.total_questions, "easy": easy,
                            "medium": medium, "hard": hard, "multi": multi,
                            "exam_time": mcq.total_exam_time, "content_summary": mcq.content_summary},
            })
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"error": str(e)})

    def _html(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[app] {args[0]} {args[1]} {args[2]}\n")


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\U0001f310 html2mcq Web UI \u2192 http://localhost:{PORT}")
    print(f"   pip install html2mcq  (if not already installed)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
        server.server_close()
