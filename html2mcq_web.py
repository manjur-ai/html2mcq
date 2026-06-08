"""
html2mcq_web.py — Flask web app for html2mcq
=============================================
A browser-based GUI to generate MCQ questions from:
  • HTML page URL
  • PDF URL
  • Local PDF file
  • Raw HTML paste

Usage
-----
python html2mcq_web.py
  → opens http://localhost:5000
"""

import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import flask
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)


# ── HTML template (dark theme matching tkinter GUI) ──────────────────────

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>html2mcq — MCQ Generator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1e1e2e;color:#e2e8f0;min-height:100vh}
:root{--bg:#1e1e2e;--bg2:#2a2a3e;--bg3:#313145;--accent:#7c3aed;--accent-h:#6d28d9;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--text:#e2e8f0;--dim:#94a3b8;--border:#3f3f5a;--card:#252538;--input:#1a1a2e}
/* Header */
header{background:var(--accent);padding:10px 20px;display:flex;align-items:center;gap:12px}
header h1{font-size:18px;font-weight:700;color:#fff}
header span{font-size:12px;color:#ddd6fe}
/* Body */
.body{display:flex;gap:12px;padding:12px 14px;height:calc(100vh - 52px)}
/* Left panel */
.left{width:430px;min-width:430px;overflow-y:auto;padding-right:4px}
.left::-webkit-scrollbar{width:6px}
.left::-webkit-scrollbar-track{background:transparent}
.left::-webkit-scrollbar-thumb{background:var(--bg3);border-radius:3px}
.section{display:flex;align-items:center;gap:8px;margin:10px 0 4px;font-weight:700;font-size:13px}
.section hr{flex:1;border:none;border-top:1px solid var(--border)}
.card{background:var(--card);padding:10px 12px;border-radius:6px;margin-bottom:4px}
.row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.row:last-child{margin-bottom:0}
label{color:var(--dim);font-size:12px;min-width:80px;white-space:nowrap}
input,select,textarea{background:var(--input);color:var(--text);border:none;border-radius:4px;padding:6px 8px;font-size:12px;font-family:inherit;width:100%;outline:none}
input:focus,textarea:focus{box-shadow:0 0 0 2px var(--accent)}
input::placeholder,textarea::placeholder{color:#555}
.radio-group{display:flex;gap:4px}
.radio-group label{cursor:pointer;display:flex;align-items:center;gap:4px;min-width:auto;color:var(--text);font-size:12px}
.radio-group input[type=radio]{accent-color:var(--accent);width:14px;height:14px}
.checkbox-row{display:flex;gap:16px;margin-top:6px}
.checkbox-row label{display:flex;align-items:center;gap:4px;cursor:pointer;min-width:auto;color:var(--text);font-size:12px}
.checkbox-row input[type=checkbox]{accent-color:var(--accent);width:14px;height:14px}
/* Tabs */
.tabs{display:flex;gap:2px;margin-bottom:0}
.tab-btn{flex:1;padding:7px 6px;font-size:11px;background:var(--bg3);color:var(--dim);border:none;cursor:pointer;border-radius:4px 4px 0 0;transition:.15s}
.tab-btn.active{background:var(--card);color:var(--text);font-weight:600}
.tab-btn:hover{background:var(--border)}
.tab-content{display:none}
.tab-content.active{display:block}
/* Buttons */
.btn{background:var(--accent);color:#fff;border:none;border-radius:4px;padding:8px 14px;font-size:12px;font-weight:600;cursor:pointer;transition:.15s;display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn:hover{background:var(--accent-h)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sm{padding:5px 10px;font-size:11px}
.btn-block{width:100%;padding:10px;margin-top:8px}
/* Right panel */
.right{flex:1;display:flex;flex-direction:column;min-width:0}
.toolbar{background:var(--bg2);padding:6px 12px;border-radius:6px;display:flex;align-items:center;gap:6px;margin-bottom:6px}
.toolbar h2{font-size:14px;font-weight:700;margin-right:12px}
.toolbar .spacer{flex:1}
.stats-bar{background:var(--bg3);padding:5px 10px;border-radius:4px;font-size:12px;color:var(--dim);margin-bottom:6px;min-height:26px}
.output{flex:1;background:var(--input);border-radius:6px;padding:10px;font-family:Consolas,'Courier New',monospace;font-size:12px;overflow:auto;white-space:pre-wrap;word-wrap:break-word;line-height:1.5}
.output .header{color:var(--accent);font-weight:700}
.output .correct{color:var(--green)}
.output .option{color:var(--text)}
.output .meta{color:var(--dim);font-size:11px}
.output .easy{color:var(--green)}
.output .medium{color:var(--yellow)}
.output .hard{color:var(--red)}
.output .multi{color:var(--yellow)}
/* Status */
.status{font-size:11px;color:var(--dim);margin-top:4px}
/* Spinner */
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--dim);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
/* Scrollbar */
.output::-webkit-scrollbar{width:6px}
.output::-webkit-scrollbar-track{background:transparent}
.output::-webkit-scrollbar-thumb{background:var(--bg3);border-radius:3px}
/* Error flash */
.error{background:var(--red);color:#fff;padding:8px 12px;border-radius:4px;margin-bottom:6px;font-size:12px;display:none}
</style>
</head>
<body>

<header>
  <h1>&#9889; html2mcq</h1>
  <span>v2.0.0 &bull; AI-powered MCQ Generator</span>
</header>

<div class="body">

  <!-- LEFT PANEL -->
  <div class="left" id="leftPanel">

    <!-- API Config -->
    <div class="section">&#128273; AI Provider &amp; API Key<hr></div>
    <div class="card">
      <div class="row">
        <label>Provider</label>
        <div class="radio-group" id="providerGroup">
          <label><input type="radio" name="provider" value="anthropic"> anthropic</label>
          <label><input type="radio" name="provider" value="openai"> openai</label>
          <label><input type="radio" name="provider" value="openrouter" checked> openrouter</label>
        </div>
      </div>
      <div class="row">
        <label>API Key</label>
        <input type="password" id="apiKey" placeholder="sk-..." autocomplete="off">
      </div>
      <div class="row">
        <label>Model</label>
        <input type="text" id="model" value="meta-llama/llama-3.3-70b-instruct:free" list="mcqModelList">
        <datalist id="mcqModelList">
          <option value="meta-llama/llama-3.3-70b-instruct:free">
          <option value="meta-llama/llama-3.3-70b-instruct">
          <option value="google/gemini-2.5-flash-lite">
          <option value="google/gemini-2.5-pro">
          <option value="google/gemma-3-27b-it">
          <option value="google/gemma-3-12b-it">
          <option value="google/gemma-4-31b-it:free">
          <option value="google/gemma-4-26b-a4b-it:free">
          <option value="openai/gpt-4o">
          <option value="openai/gpt-4o-mini">
          <option value="openai/gpt-oss-120b:free">
          <option value="openai/gpt-oss-20b:free">
          <option value="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free">
          <option value="nvidia/nemotron-3-super-120b-a12b:free">
          <option value="nvidia/nemotron-3-ultra-550b-a55b:free">
          <option value="claude-opus-4-6">
          <option value="claude-sonnet-4-6">
          <option value="claude-haiku-3-5">
          <option value="qwen2.5:7b">
          <option value="llama3.1:8b">
          <option value="mistral:7b">
          <option value="auto">
        </datalist>
      </div>
    </div>

    <!-- Input Source -->
    <div class="section">&#128229; Input Source<hr></div>
    <div class="card" style="padding:0">
      <div class="tabs" id="inputTabs">
        <button class="tab-btn active" data-tab="url">&#127760; Web URL</button>
        <button class="tab-btn" data-tab="pdfurl">&#128196; PDF URL</button>
        <button class="tab-btn" data-tab="pdffile">&#128193; Local PDF</button>
        <button class="tab-btn" data-tab="html">&#128221; Raw HTML</button>
      </div>

      <!-- Tab: URL -->
      <div class="tab-content active" id="tab-url" style="padding:10px 12px">
        <label style="display:block;margin-bottom:4px;min-width:auto">Page URL (HTML tutorial or direct PDF link):</label>
        <input type="text" id="webUrl" placeholder="https://docs.python.org/3/tutorial/">
        <div class="checkbox-row">
          <label><input type="checkbox" id="enrichPdfs" checked> Auto-extract PDF links</label>
          <label><input type="checkbox" id="enrichImages" checked> Auto-OCR images</label>
        </div>
      </div>

      <!-- Tab: PDF URL -->
      <div class="tab-content" id="tab-pdfurl" style="padding:10px 12px">
        <label style="display:block;margin-bottom:4px;min-width:auto">Direct PDF URL:</label>
        <input type="text" id="pdfUrl" placeholder="https://example.com/tutorial.pdf">
        <label style="display:block;margin:8px 0 4px;min-width:auto">PDF title (optional):</label>
        <input type="text" id="pdfUrlTitle" placeholder="e.g. Python Cheatsheet">
        <div class="row" style="margin-top:8px">
          <label>PDF backend:</label>
          <div class="radio-group" id="pdfBackendGroup">
            <label><input type="radio" name="pdfBackend" value="auto_detect" checked> auto_detect</label>
            <label><input type="radio" name="pdfBackend" value="pymupdf"> pymupdf</label>
            <label><input type="radio" name="pdfBackend" value="image"> image</label>
          </div>
        </div>
      </div>

      <!-- Tab: Local PDF -->
      <div class="tab-content" id="tab-pdffile" style="padding:10px 12px">
        <label style="display:block;margin-bottom:4px;min-width:auto">PDF file:</label>
        <input type="file" id="pdfFile" accept=".pdf">
        <label style="display:block;margin:8px 0 4px;min-width:auto">PDF title (optional):</label>
        <input type="text" id="pdfFileTitle" placeholder="e.g. Flask Guide">
      </div>

      <!-- Tab: Raw HTML -->
      <div class="tab-content" id="tab-html" style="padding:10px 12px">
        <label style="display:block;margin-bottom:4px;min-width:auto">Paste HTML content:</label>
        <textarea id="rawHtml" rows="5" style="resize:vertical;font-family:Consolas,monospace;font-size:11px"></textarea>
        <label style="display:block;margin:8px 0 4px;min-width:auto">Base URL (for resolving relative links):</label>
        <input type="text" id="baseUrl" placeholder="https://example.com/">
      </div>
    </div>

    <!-- Generation Options -->
    <div class="section">&#9881;&#65039; Generation Options<hr></div>
    <div class="card">
      <div class="row">
        <label>Questions (N)</label>
        <input type="number" id="questionCount" value="10" min="1" max="100" style="width:70px">
        <label style="min-width:auto;margin-left:12px">Batch size</label>
        <input type="number" id="batchSize" value="10" min="1" max="30" style="width:60px">
      </div>
      <div class="row">
        <label>Difficulty mix</label>
        <input type="text" id="difficultyMix" placeholder='e.g. "40% easy, 40% medium, 20% hard" or leave blank'>
      </div>
      <div class="row">
        <label>Focus topics</label>
        <input type="text" id="focusTopics" placeholder="e.g. loops, functions, OOP (comma-separated)">
      </div>
      <div class="row">
        <label>OCR model</label>
        <input type="text" id="ocrModel" value="pytesseract" list="ocrModelList">
        <datalist id="ocrModelList">
          <option value="pytesseract">
          <option value="auto">
          <option value="vision_api">
          <option value="google/gemini-2.5-flash-lite">
          <option value="google/gemma-3-27b-it">
          <option value="google/gemma-3-12b-it">
          <option value="openai/gpt-4o">
          <option value="openai/gpt-4o-mini">
        </datalist>
      </div>
      <label style="display:block;margin:6px 0 4px;min-width:auto">Custom instructions</label>
      <textarea id="customInstructions" rows="3" style="resize:vertical">e.g. Make answers very close and confusing. Only people with sharp attention should get 100%. Avoid straightforward questions.</textarea>
      <div style="font-size:10px;color:var(--dim);margin-top:2px">Leave blank to use defaults only.</div>
    </div>

    <button class="btn btn-block" id="generateBtn">&#9889; Generate MCQs</button>
    <div class="status" id="status">Ready</div>
  </div>

  <!-- RIGHT PANEL -->
  <div class="right">
    <div class="toolbar">
      <h2>&#128203; Output</h2>
      <div class="radio-group">
        <label><input type="radio" name="format" value="pretty" checked> PRETTY</label>
        <label><input type="radio" name="format" value="json"> JSON</label>
      </div>
      <div class="spacer"></div>
      <button class="btn btn-sm" id="saveJsonBtn">&#128190; Save JSON</button>
      <button class="btn btn-sm" id="copyBtn">&#128203; Copy</button>
      <button class="btn btn-sm" id="clearBtn">&#128465;&#65039; Clear</button>
    </div>
    <div class="stats-bar" id="statsBar">No results yet</div>
    <div id="errorFlash" class="error"></div>
    <div class="output" id="output"></div>
  </div>

</div>

<script>
// ── Tab switching ──
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

// ── Provider → default model ──
document.querySelectorAll('input[name="provider"]').forEach(rb => {
  rb.addEventListener('change', () => {
    const map = { anthropic: 'claude-opus-4-6', openai: 'gpt-4o', openrouter: 'meta-llama/llama-3.3-70b-instruct:free' };
    const modelInput = document.getElementById('model');
    const dl = document.getElementById('mcqModelList');
    // Show/hide relevant options based on provider
    const show = { anthropic: ['claude-opus-4-6','claude-sonnet-4-6','claude-haiku-3-5'],
                   openai: ['openai/gpt-4o','openai/gpt-4o-mini','openai/gpt-oss-120b:free','openai/gpt-oss-20b:free'],
                   openrouter: Array.from(dl.options).map(o => o.value) };
    modelInput.value = map[rb.value] || '';
  });
});

// ── Local PDF file picker → title auto-fill ──
document.getElementById('pdfFile').addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const title = file.name.replace(/\.pdf$/i, '').replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  if (!document.getElementById('pdfFileTitle').value) {
    document.getElementById('pdfFileTitle').value = title;
  }
});

// ── Custom instructions placeholder ──
const ciEl = document.getElementById('customInstructions');
const CI_PLACEHOLDER = ciEl.value;
ciEl.addEventListener('focus', () => {
  if (ciEl.value === CI_PLACEHOLDER) { ciEl.value = ''; ciEl.style.color = '#e2e8f0'; }
});
ciEl.addEventListener('blur', () => {
  if (!ciEl.value.trim()) { ciEl.value = CI_PLACEHOLDER; ciEl.style.color = '#94a3b8'; }
});
if (ciEl.value === CI_PLACEHOLDER) ciEl.style.color = '#94a3b8';

// ── Generate ──
document.getElementById('generateBtn').addEventListener('click', generate);

async function generate() {
  const btn = document.getElementById('generateBtn');
  const status = document.getElementById('status');
  const output = document.getElementById('output');
  const statsBar = document.getElementById('statsBar');
  const errorFlash = document.getElementById('errorFlash');

  errorFlash.style.display = 'none';
  output.innerHTML = '';
  statsBar.textContent = 'Generating...';
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating...';
  status.textContent = 'Initialising generator...';

  const provider = document.querySelector('input[name="provider"]:checked').value;
  const tab = document.querySelector('.tab-btn.active').dataset.tab;

  const payload = {
    api_key: document.getElementById('apiKey').value,
    provider: provider,
    model: document.getElementById('model').value,
    n: parseInt(document.getElementById('questionCount').value) || 10,
    batch_size: parseInt(document.getElementById('batchSize').value) || 10,
    difficulty_mix: document.getElementById('difficultyMix').value || null,
    focus_topics: document.getElementById('focusTopics').value || null,
    ocr_model: document.getElementById('ocrModel').value,
    custom_instructions: (ciEl.value === CI_PLACEHOLDER || !ciEl.value.trim()) ? '' : ciEl.value,
    tab: tab,
  };

  // Tab-specific fields
  if (tab === 'url') {
    payload.url = document.getElementById('webUrl').value;
    payload.enrich_pdfs = document.getElementById('enrichPdfs').checked;
    payload.enrich_images = document.getElementById('enrichImages').checked;
  } else if (tab === 'pdfurl') {
    payload.url = document.getElementById('pdfUrl').value;
    payload.pdf_title = document.getElementById('pdfUrlTitle').value;
    payload.pdf_backend = document.querySelector('input[name="pdfBackend"]:checked').value;
  } else if (tab === 'pdffile') {
    const fileInput = document.getElementById('pdfFile');
    if (!fileInput.files[0]) { showError('Please select a PDF file.'); return; }
    payload.pdf_title = document.getElementById('pdfFileTitle').value;
    // Read file as base64
    const b64 = await readFileAsBase64(fileInput.files[0]);
    payload.pdf_data = b64;
    payload.pdf_filename = fileInput.files[0].name;
  } else if (tab === 'html') {
    payload.html = document.getElementById('rawHtml').value;
    payload.base_url = document.getElementById('baseUrl').value;
  }

  if (!payload.api_key) payload.api_key = '';

  status.textContent = 'Sending request...';
  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || 'Request failed'); return; }
    renderResult(data);
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '&#9889; Generate MCQs';
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function showError(msg) {
  const flash = document.getElementById('errorFlash');
  flash.textContent = msg;
  flash.style.display = 'block';
  document.getElementById('status').textContent = 'Error: ' + msg;
  document.getElementById('statsBar').textContent = 'Error';
  document.getElementById('generateBtn').disabled = false;
  document.getElementById('generateBtn').innerHTML = '&#9889; Generate MCQs';
  const output = document.getElementById('output');
  output.innerHTML = '<span class="meta">ERROR:\n' + escapeHtml(msg) + '</span>';
}

function renderResult(data) {
  const output = document.getElementById('output');
  const statsBar = document.getElementById('statsBar');
  const status = document.getElementById('status');

  if (data.error) { showError(data.error); return; }

  const fmt = document.querySelector('input[name="format"]:checked').value;

  if (fmt === 'json') {
    output.innerHTML = escapeHtml(JSON.stringify(data.mcq, null, 2));
  } else {
    renderPretty(data.mcq, output);
  }

  const s = data.summary;
  statsBar.innerHTML = '&#10003; ' + s.total_questions + ' questions &bull; '
    + 'Easy:' + s.easy + ' Medium:' + s.medium + ' Hard:' + s.hard + ' &bull; '
    + 'Multi-answer:' + s.multi + ' &bull; '
    + 'Exam time: ' + s.exam_time + ' min &bull; '
    + escapeHtml(s.content_summary);
  status.textContent = 'Done — ' + s.total_questions + ' questions generated.';
  window._mcqData = data.mcq;
}

function renderPretty(mcq, el) {
  let h = '';
  h += '<span class="header">' + '='.repeat(62) + '\n';
  h += '  ' + escapeHtml(mcq.page_title) + '\n';
  h += '  Source   : ' + escapeHtml(mcq.source_url || 'N/A') + '\n';
  h += '  Questions: ' + mcq.total_questions + '  |  Exam time: ' + mcq.total_exam_time + ' min\n';
  h += '  ' + escapeHtml(mcq.content_summary) + '\n';
  h += '='.repeat(62) + '\n\n</span>';

  mcq.questions.forEach((q, i) => {
    const diffTag = q.difficulty;
    h += '<span class="header">Q' + (i+1) + '. </span>';
    h += '<span class="' + diffTag + '">[' + q.difficulty.toUpperCase() + ']</span>';
    if (q.multi) h += '<span class="multi">  [MULTI]</span>';
    h += '  ' + escapeHtml(q.question_html) + '\n';
    h += '<span class="meta">     Marks: +' + q.marks + ' / -' + q.negative_marks + '\n</span>';
    h += '\n';
    q.options.forEach((opt, j) => {
      const cls = q.answers.indexOf(j) !== -1 ? 'correct' : 'option';
      const mark = q.answers.indexOf(j) !== -1 ? '\u2713  ' : '     ';
      h += '<span class="' + cls + '">' + mark + String.fromCharCode(65+j) + ') ' + escapeHtml(opt) + '\n</span>';
    });
    if (q.explaination) {
      h += '<span class="meta">\n     \uD83D\uDCA1 ' + escapeHtml(q.explaination) + '\n</span>';
    }
    h += '\n';
  });

  el.innerHTML = h;
}

function escapeHtml(s) {
  if (typeof s !== 'string') return String(s);
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Format toggle ──
document.querySelectorAll('input[name="format"]').forEach(rb => {
  rb.addEventListener('change', () => {
    if (window._mcqData) renderResult({ mcq: window._mcqData, summary: window._summaryData });
  });
});

// ── Copy ──
document.getElementById('copyBtn').addEventListener('click', async () => {
  const text = document.getElementById('output').textContent;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    document.getElementById('status').textContent = 'Copied to clipboard!';
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    document.getElementById('status').textContent = 'Copied to clipboard!';
  }
});

// ── Clear ──
document.getElementById('clearBtn').addEventListener('click', () => {
  document.getElementById('output').innerHTML = '';
  document.getElementById('statsBar').textContent = 'No results yet';
  document.getElementById('status').textContent = 'Ready';
  window._mcqData = null;
});

// ── Save JSON ──
document.getElementById('saveJsonBtn').addEventListener('click', () => {
  if (!window._mcqData) { showError('Generate questions first.'); return; }
  const title = (window._mcqData.page_title || 'mcq').replace(/[\\/*?:"<>|]/g, '_').slice(0,30);
  const blob = new Blob([JSON.stringify(window._mcqData, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = title + '_mcq.json';
  a.click();
  URL.revokeObjectURL(a.href);
  document.getElementById('status').textContent = 'Saved as ' + a.download;
});
</script>
</body>
</html>"""


# ── API Route ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True)
    if not data:
        return jsonify(error="Empty request"), 400

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
        pdf_backend = data.get("pdf_backend", "auto_detect")
        tab = data.get("tab", "url")

        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        if not api_key:
            api_key = os.environ.get(env_map.get(provider, ""), "")
        if not api_key:
            raise ValueError(f"No API key. Enter it above or set {env_map[provider]} env var.")

        gen = MCQGenerator(
            api_key=api_key,
            provider=provider,
            mcq_model=model,
            batch_size=batch_size,
            pdf_backend=pdf_backend,
            ocr_model=ocr_model,
            method="twostep",
            custom_instructions=ci,
        )

        if tab == "url":
            url = data.get("url", "").strip()
            if not url:
                return jsonify(error="Please enter a URL."), 400
            mcq = gen.from_url(
                url, n=n,
                difficulty_mix=diff, focus_topics=topics,
                enrich_pdfs=bool(data.get("enrich_pdfs", True)),
                enrich_images=bool(data.get("enrich_images", True)),
                custom_instructions=ci,
            )
        elif tab == "pdfurl":
            url = data.get("url", "").strip()
            if not url:
                return jsonify(error="Please enter a PDF URL."), 400
            mcq = gen.from_pdf_url(
                url, n=n,
                pdf_title=data.get("pdf_title", "").strip(),
                difficulty_mix=diff, focus_topics=topics,
                custom_instructions=ci,
            )
        elif tab == "pdffile":
            pdf_data = data.get("pdf_data")
            if not pdf_data:
                return jsonify(error="Please select a PDF file."), 400
            pdf_bytes = __import__("base64").b64decode(pdf_data)
            # Write to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = f.name
            try:
                mcq = gen.from_pdf_path(
                    tmp_path, n=n,
                    pdf_title=data.get("pdf_title", "").strip(),
                    difficulty_mix=diff, focus_topics=topics,
                    custom_instructions=ci,
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        elif tab == "html":
            html = data.get("html", "").strip()
            if not html:
                return jsonify(error="Please paste some HTML content."), 400
            mcq = gen.from_html(
                html, n=n,
                base_url=data.get("base_url", "").strip(),
                difficulty_mix=diff, focus_topics=topics,
                enrich_pdfs=False, enrich_images=True,
                custom_instructions=ci,
            )
        else:
            return jsonify(error=f"Unknown tab: {tab}"), 400

        easy = sum(1 for q in mcq.questions if q.difficulty == "easy")
        medium = sum(1 for q in mcq.questions if q.difficulty == "medium")
        hard = sum(1 for q in mcq.questions if q.difficulty == "hard")
        multi = sum(1 for q in mcq.questions if q.multi)

        return jsonify(
            mcq=json.loads(mcq.to_json()),
            summary={
                "total_questions": mcq.total_questions,
                "easy": easy,
                "medium": medium,
                "hard": hard,
                "multi": multi,
                "exam_time": mcq.total_exam_time,
                "content_summary": mcq.content_summary,
            },
        )

    except Exception as e:
        return jsonify(error=str(e)), 500


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🌐 html2mcq Web UI → http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
