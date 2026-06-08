"""
html2mcq_gui.py — Tkinter desktop app for html2mcq
====================================================
A full-featured GUI to generate MCQ questions from:
  • HTML page URL
  • PDF URL
  • Local PDF file
  • Raw HTML paste

Usage
-----
python html2mcq_gui.py
"""

import os
import re
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path


# ── Theme colours ─────────────────────────────────────────────────────────────

BG         = "#1e1e2e"
BG2        = "#2a2a3e"
BG3        = "#313145"
ACCENT     = "#7c3aed"
ACCENT_H   = "#6d28d9"
GREEN      = "#22c55e"
RED        = "#ef4444"
YELLOW     = "#f59e0b"
TEXT       = "#e2e8f0"
TEXT_DIM   = "#94a3b8"
BORDER     = "#3f3f5a"
CARD       = "#252538"
INPUT_BG   = "#1a1a2e"
FONT       = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_LARGE = ("Segoe UI", 13, "bold")
FONT_MONO  = ("Consolas", 9)


# ── Main App ──────────────────────────────────────────────────────────────────

class Html2MCQApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("html2mcq — MCQ Generator")
        self.geometry("1100x850")
        self.minsize(900, 700)
        self.configure(bg=BG)
        self._result_mcq = None
        self._build_ui()
        self._apply_styles()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header bar
        header = tk.Frame(self, bg=ACCENT, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="  ⚡ html2mcq", font=("Segoe UI", 14, "bold"),
                 bg=ACCENT, fg="white").pack(side="left", padx=16, pady=10)
        tk.Label(header, text="v2.0.0  •  AI-powered MCQ Generator",
                 font=("Segoe UI", 9), bg=ACCENT, fg="#ddd6fe").pack(side="left", pady=10)

        # ── Main body: left config + right output
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        # Scrollable left panel
        left_outer = tk.Frame(body, bg=BG, width=430)
        left_outer.pack(side="left", fill="y", padx=(0,10))
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, bg=BG, highlightthickness=0, width=415)
        left_scrollbar = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = tk.Frame(left_canvas, bg=BG)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        def _on_canvas_resize(e):
            left_canvas.itemconfig(left_window, width=e.width)
        left.bind("<Configure>", _on_left_configure)
        left_canvas.bind("<Configure>", _on_canvas_resize)

        # Mouse wheel scroll
        def _on_mousewheel(e):
            delta = -1 if e.delta > 0 else 1
            left_canvas.yview_scroll(delta, "units")
        left_canvas.bind("<MouseWheel>", _on_mousewheel)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent):
        # ── Section: API config
        self._section(parent, "🔑  AI Provider & API Key")
        api_frame = self._card(parent)

        row0 = tk.Frame(api_frame, bg=CARD)
        row0.pack(fill="x", pady=(0,6))
        tk.Label(row0, text="Provider", width=10, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.provider_var = tk.StringVar(value="openrouter")
        for p in ("anthropic", "openai", "openrouter"):
            tk.Radiobutton(row0, text=p, variable=self.provider_var, value=p,
                           font=FONT, bg=CARD, fg=TEXT, selectcolor=ACCENT,
                           activebackground=CARD, activeforeground=TEXT,
                           command=self._on_provider_change).pack(side="left", padx=6)

        row1 = tk.Frame(api_frame, bg=CARD)
        row1.pack(fill="x", pady=(0,6))
        tk.Label(row1, text="API Key", width=10, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.api_key_var = tk.StringVar()
        self.api_key_entry = self._entry(row1, self.api_key_var, show="•")
        self.api_key_entry.pack(side="left", fill="x", expand=True)

        row2 = tk.Frame(api_frame, bg=CARD)
        row2.pack(fill="x")
        tk.Label(row2, text="Model", width=10, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.model_var = tk.StringVar(value="meta-llama/llama-3.3-70b-instruct:free")
        self.model_combo = ttk.Combobox(row2, textvariable=self.model_var,
                                         values=[
                                             "meta-llama/llama-3.3-70b-instruct:free",
                                             "meta-llama/llama-3.3-70b-instruct",
                                             "google/gemini-2.5-flash-lite",
                                             "google/gemini-2.5-pro",
                                             "google/gemma-3-27b-it",
                                             "google/gemma-3-12b-it",
                                             "google/gemma-4-31b-it:free",
                                             "google/gemma-4-26b-a4b-it:free",
                                             "openai/gpt-4o",
                                             "openai/gpt-4o-mini",
                                             "openai/gpt-oss-120b:free",
                                             "openai/gpt-oss-20b:free",
                                             "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                                             "nvidia/nemotron-3-super-120b-a12b:free",
                                             "nvidia/nemotron-3-ultra-550b-a55b:free",
                                             "claude-opus-4-6",
                                             "claude-sonnet-4-6",
                                             "claude-haiku-3-5",
                                             "qwen2.5:7b",
                                             "llama3.1:8b",
                                             "mistral:7b",
                                             "auto",
                                         ], state="normal", font=FONT)
        self.model_combo.pack(side="left", fill="x", expand=True)

        # ── Section: Input type tabs
        self._section(parent, "📥  Input Source")
        tab_frame = tk.Frame(parent, bg=BG)
        tab_frame.pack(fill="x", pady=(0,4))

        self.input_tabs = ttk.Notebook(tab_frame)
        self.input_tabs.pack(fill="x")

        # Tab: URL
        t_url = self._tab_frame(self.input_tabs, "🌐 URL")
        self.input_tabs.add(t_url, text="  🌐 Web URL  ")
        lbl = tk.Label(t_url, text="Page URL (HTML tutorial or direct PDF link):",
                       font=FONT, bg=CARD, fg=TEXT_DIM)
        lbl.pack(anchor="w", pady=(0,4))
        self.url_var = tk.StringVar()
        self._entry(t_url, self.url_var,
                    placeholder="https://docs.python.org/3/tutorial/").pack(fill="x")
        self.enrich_pdfs_var   = tk.BooleanVar(value=True)
        self.enrich_images_var = tk.BooleanVar(value=True)
        cb_row = tk.Frame(t_url, bg=CARD)
        cb_row.pack(fill="x", pady=(6,0))
        self._checkbox(cb_row, "Auto-extract PDF links", self.enrich_pdfs_var).pack(side="left", padx=(0,12))
        self._checkbox(cb_row, "Auto-OCR images", self.enrich_images_var).pack(side="left")

        # Tab: PDF URL
        t_pdfurl = self._tab_frame(self.input_tabs, "📄 PDF URL")
        self.input_tabs.add(t_pdfurl, text="  📄 PDF URL  ")
        tk.Label(t_pdfurl, text="Direct PDF URL:", font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(0,4))
        self.pdf_url_var = tk.StringVar()
        self._entry(t_pdfurl, self.pdf_url_var,
                    placeholder="https://example.com/tutorial.pdf").pack(fill="x")
        tk.Label(t_pdfurl, text="PDF title (optional):", font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(8,4))
        self.pdf_url_title_var = tk.StringVar()
        self._entry(t_pdfurl, self.pdf_url_title_var, placeholder="e.g. Python Cheatsheet").pack(fill="x")
        # PDF backend picker
        be_row = tk.Frame(t_pdfurl, bg=CARD)
        be_row.pack(fill="x", pady=(8,0))
        tk.Label(be_row, text="PDF backend:", font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left", padx=(0,8))
        self.pdf_backend_var = tk.StringVar(value="auto_detect")
        for be in ("auto_detect", "pymupdf", "image"):
            tk.Radiobutton(be_row, text=be, variable=self.pdf_backend_var, value=be,
                           font=FONT, bg=CARD, fg=TEXT, selectcolor=ACCENT,
                           activebackground=CARD).pack(side="left", padx=4)

        # Tab: Local PDF
        t_pdffile = self._tab_frame(self.input_tabs, "📁 Local PDF")
        self.input_tabs.add(t_pdffile, text="  📁 Local PDF  ")
        tk.Label(t_pdffile, text="PDF file path:", font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(0,4))
        file_row = tk.Frame(t_pdffile, bg=CARD)
        file_row.pack(fill="x")
        self.pdf_path_var = tk.StringVar()
        self._entry(file_row, self.pdf_path_var, placeholder="Select a PDF file...").pack(side="left", fill="x", expand=True)
        self._btn(file_row, "Browse", self._browse_pdf, small=True).pack(side="left", padx=(6,0))
        tk.Label(t_pdffile, text="PDF title (optional):", font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(8,4))
        self.pdf_file_title_var = tk.StringVar()
        self._entry(t_pdffile, self.pdf_file_title_var, placeholder="e.g. Flask Guide").pack(fill="x")

        # Tab: Raw HTML
        t_html = self._tab_frame(self.input_tabs, "📝 Raw HTML")
        self.input_tabs.add(t_html, text="  📝 Raw HTML  ")
        tk.Label(t_html, text="Paste HTML content:", font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(0,4))
        self.raw_html_text = scrolledtext.ScrolledText(
            t_html, height=7, font=FONT_MONO,
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", borderwidth=0
        )
        self.raw_html_text.pack(fill="both", expand=True)
        tk.Label(t_html, text="Base URL (for resolving relative links):",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(6,4))
        self.base_url_var = tk.StringVar()
        self._entry(t_html, self.base_url_var, placeholder="https://example.com/").pack(fill="x")

        # ── Section: Generation options
        self._section(parent, "⚙️  Generation Options")
        opt_card = self._card(parent)

        row_n = tk.Frame(opt_card, bg=CARD)
        row_n.pack(fill="x", pady=(0,6))
        tk.Label(row_n, text="Questions (N)", width=16, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.n_var = tk.IntVar(value=10)
        tk.Spinbox(row_n, from_=1, to=100, textvariable=self.n_var, width=6,
                   font=FONT, bg=INPUT_BG, fg=TEXT, buttonbackground=BG3,
                   relief="flat", insertbackground=TEXT).pack(side="left")
        tk.Label(row_n, text="  Batch size", font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left", padx=(12,4))
        self.batch_var = tk.IntVar(value=10)
        tk.Spinbox(row_n, from_=1, to=30, textvariable=self.batch_var, width=5,
                   font=FONT, bg=INPUT_BG, fg=TEXT, buttonbackground=BG3,
                   relief="flat", insertbackground=TEXT).pack(side="left")

        row_diff = tk.Frame(opt_card, bg=CARD)
        row_diff.pack(fill="x", pady=(0,6))
        tk.Label(row_diff, text="Difficulty mix", width=16, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.diff_var = tk.StringVar(value="")
        self._entry(row_diff, self.diff_var,
                    placeholder='e.g. "40% easy, 40% medium, 20% hard"  or leave blank').pack(side="left", fill="x", expand=True)

        row_topics = tk.Frame(opt_card, bg=CARD)
        row_topics.pack(fill="x", pady=(0,6))
        tk.Label(row_topics, text="Focus topics", width=16, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.topics_var = tk.StringVar()
        self._entry(row_topics, self.topics_var,
                    placeholder="e.g. loops, functions, OOP  (comma-separated)").pack(side="left", fill="x", expand=True)

        row_ocr = tk.Frame(opt_card, bg=CARD)
        row_ocr.pack(fill="x", pady=(0,6))
        tk.Label(row_ocr, text="OCR model", width=16, anchor="w",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(side="left")
        self.ocr_model_var = tk.StringVar(value="pytesseract")
        ocr_combo = ttk.Combobox(row_ocr, textvariable=self.ocr_model_var,
                                  values=[
                                      "pytesseract",
                                      "auto",
                                      "vision_api",
                                      "google/gemini-2.5-flash-lite",
                                      "google/gemma-3-27b-it",
                                      "google/gemma-3-12b-it",
                                      "openai/gpt-4o",
                                      "openai/gpt-4o-mini",
                                  ],
                                  state="normal", font=FONT)
        ocr_combo.pack(side="left", fill="x", expand=True)

        # Custom instructions
        tk.Label(opt_card, text="Custom instructions",
                 font=FONT, bg=CARD, fg=TEXT_DIM).pack(anchor="w", pady=(0,4))
        self.custom_instructions_text = tk.Text(
            opt_card, height=4, font=FONT,
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=4, wrap="word"
        )
        self.custom_instructions_text.pack(fill="x")
        # Placeholder
        placeholder_ci = "e.g. Make answers very close and confusing. Only people with sharp attention should get 100%. Avoid straightforward questions."
        self.custom_instructions_text.insert("1.0", placeholder_ci)
        self.custom_instructions_text.config(fg=TEXT_DIM)
        def _ci_focus_in(e):
            if self.custom_instructions_text.get("1.0","end-1c") == placeholder_ci:
                self.custom_instructions_text.delete("1.0","end")
                self.custom_instructions_text.config(fg=TEXT)
        def _ci_focus_out(e):
            if not self.custom_instructions_text.get("1.0","end-1c").strip():
                self.custom_instructions_text.insert("1.0", placeholder_ci)
                self.custom_instructions_text.config(fg=TEXT_DIM)
        self.custom_instructions_text.bind("<FocusIn>", _ci_focus_in)
        self.custom_instructions_text.bind("<FocusOut>", _ci_focus_out)
        tk.Label(opt_card, text="Leave blank to use defaults only.",
                 font=("Segoe UI", 8), bg=CARD, fg=TEXT_DIM).pack(anchor="w")

        # ── Generate button
        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(fill="x", pady=(10,0))
        self.gen_btn = self._btn(btn_frame, "⚡  Generate MCQs", self._start_generation)
        self.gen_btn.pack(fill="x", ipady=8)

        # ── Progress bar
        self.progress = ttk.Progressbar(parent, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6,0))

        # ── Status label
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(parent, textvariable=self.status_var, font=FONT,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(4,0))

    def _build_right(self, parent):
        # ── Output toolbar
        toolbar = tk.Frame(parent, bg=BG2, height=38)
        toolbar.pack(fill="x", pady=(0,6))
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="📋  Output", font=FONT_LARGE,
                 bg=BG2, fg=TEXT).pack(side="left", padx=12, pady=6)

        # Format toggle
        self.fmt_var = tk.StringVar(value="pretty")
        for fmt in ("pretty", "json"):
            tk.Radiobutton(toolbar, text=fmt.upper(), variable=self.fmt_var, value=fmt,
                           font=FONT, bg=BG2, fg=TEXT, selectcolor=ACCENT,
                           activebackground=BG2, command=self._refresh_output).pack(side="left", padx=4)

        # Action buttons
        self._btn(toolbar, "💾 Save JSON", self._save_json, small=True).pack(side="right", padx=4, pady=5)
        self._btn(toolbar, "📋 Copy", self._copy_output, small=True).pack(side="right", padx=4, pady=5)
        self._btn(toolbar, "🗑 Clear", self._clear_output, small=True).pack(side="right", padx=4, pady=5)

        # ── Stats bar
        self.stats_frame = tk.Frame(parent, bg=BG3, height=30)
        self.stats_frame.pack(fill="x", pady=(0,6))
        self.stats_frame.pack_propagate(False)
        self.stats_var = tk.StringVar(value="No results yet")
        tk.Label(self.stats_frame, textvariable=self.stats_var, font=FONT,
                 bg=BG3, fg=TEXT_DIM).pack(side="left", padx=10, pady=4)

        # ── Output text area
        self.output_text = scrolledtext.ScrolledText(
            parent, font=FONT_MONO, wrap="word",
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", borderwidth=0, state="disabled",
            selectbackground=ACCENT
        )
        self.output_text.pack(fill="both", expand=True)

        # ── Tag colours for pretty view
        self.output_text.tag_config("header",   foreground=ACCENT,  font=("Consolas", 9, "bold"))
        self.output_text.tag_config("correct",  foreground=GREEN)
        self.output_text.tag_config("option",   foreground=TEXT)
        self.output_text.tag_config("meta",     foreground=TEXT_DIM, font=("Consolas", 8))
        self.output_text.tag_config("easy",     foreground=GREEN)
        self.output_text.tag_config("medium",   foreground=YELLOW)
        self.output_text.tag_config("hard",     foreground=RED)
        self.output_text.tag_config("multi",    foreground=YELLOW)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_provider_change(self):
        provider = self.provider_var.get()
        defaults = {
            "anthropic":   "claude-opus-4-6",
            "openai":      "gpt-4o",
            "openrouter":  "meta-llama/llama-3.3-70b-instruct:free",
        }
        self.model_var.set(defaults.get(provider, ""))

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="Select PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if path:
            self.pdf_path_var.set(path)
            stem = Path(path).stem.replace("-", " ").replace("_", " ").title()
            if not self.pdf_file_title_var.get():
                self.pdf_file_title_var.set(stem)

    def _start_generation(self):
        self.gen_btn.config(state="disabled", text="⏳  Generating...")
        self.progress.start(10)
        self.status_var.set("Initialising generator...")
        self._clear_output()
        threading.Thread(target=self._run_generation, daemon=True).start()

    def _run_generation(self):
        try:
            self._generate()
        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _generate(self):
        api_key = self.api_key_var.get().strip()
        provider = self.provider_var.get()
        model = self.model_var.get().strip()
        n = self.n_var.get()
        batch = self.batch_var.get()
        diff = self.diff_var.get().strip() or None
        topics_raw = self.topics_var.get().strip()
        topics = [t.strip() for t in topics_raw.split(",") if t.strip()] or None
        ci_raw = self.custom_instructions_text.get("1.0", "end-1c").strip()
        custom_instructions = ci_raw if ci_raw and ci_raw != "e.g. Make answers very close and confusing. Only people with sharp attention should get 100%. Avoid straightforward questions." else None

        env_map = {
            "anthropic":  "ANTHROPIC_API_KEY",
            "openai":     "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        if not api_key:
            api_key = os.environ.get(env_map.get(provider, ""), "")
        if not api_key:
            raise ValueError(f"No API key. Enter it above or set {env_map[provider]} env var.")

        self.after(0, self.status_var.set, "Building generator...")

        from html2mcq import MCQGenerator
        gen = MCQGenerator(
            api_key=api_key,
            provider=provider,
            mcq_model=model,
            batch_size=batch,
            pdf_backend=self.pdf_backend_var.get(),
            ocr_model=self.ocr_model_var.get(),
            method="twostep",
            custom_instructions=custom_instructions,
        )

        tab = self.input_tabs.index(self.input_tabs.select())
        self.after(0, self.status_var.set, f"Generating {n} questions...")

        if tab == 0:    # Web URL
            url = self.url_var.get().strip()
            if not url:
                raise ValueError("Please enter a URL.")
            mcq = gen.from_url(
                url, n=n,
                difficulty_mix=diff, focus_topics=topics,
                enrich_pdfs=self.enrich_pdfs_var.get(),
                enrich_images=self.enrich_images_var.get(),
                custom_instructions=custom_instructions,
            )

        elif tab == 1:  # PDF URL
            url = self.pdf_url_var.get().strip()
            if not url:
                raise ValueError("Please enter a PDF URL.")
            mcq = gen.from_pdf_url(
                url, n=n,
                pdf_title=self.pdf_url_title_var.get().strip(),
                difficulty_mix=diff, focus_topics=topics,
                custom_instructions=custom_instructions,
            )

        elif tab == 2:  # Local PDF
            path = self.pdf_path_var.get().strip()
            if not path:
                raise ValueError("Please select a PDF file.")
            mcq = gen.from_pdf_path(
                path, n=n,
                pdf_title=self.pdf_file_title_var.get().strip(),
                difficulty_mix=diff, focus_topics=topics,
                custom_instructions=custom_instructions,
            )

        else:           # Raw HTML
            html = self.raw_html_text.get("1.0", "end-1c").strip()
            if not html:
                raise ValueError("Please paste some HTML content.")
            mcq = gen.from_html(
                html, n=n,
                base_url=self.base_url_var.get().strip(),
                difficulty_mix=diff, focus_topics=topics,
                enrich_pdfs=False, enrich_images=True,
                custom_instructions=custom_instructions,
            )

        self.after(0, self._on_success, mcq)

    def _on_success(self, mcq):
        self._result_mcq = mcq
        self.progress.stop()
        self.gen_btn.config(state="normal", text="⚡  Generate MCQs")

        easy   = sum(1 for q in mcq.questions if q.difficulty == "easy")
        medium = sum(1 for q in mcq.questions if q.difficulty == "medium")
        hard   = sum(1 for q in mcq.questions if q.difficulty == "hard")
        multi  = sum(1 for q in mcq.questions if q.multi)

        self.stats_var.set(
            f"✓  {mcq.total_questions} questions  •  "
            f"Easy:{easy}  Medium:{medium}  Hard:{hard}  •  "
            f"Multi-answer:{multi}  •  "
            f"Exam time: {mcq.total_exam_time} min  •  "
            f"{mcq.content_summary}"
        )
        self.status_var.set(f"Done — {mcq.total_questions} questions generated.")
        self._refresh_output()

    def _on_error(self, msg):
        self.progress.stop()
        self.gen_btn.config(state="normal", text="⚡  Generate MCQs")
        self.status_var.set(f"Error: {msg}")
        self._write_output(f"ERROR:\n{msg}", clear=True)
        messagebox.showerror("Generation failed", msg)

    def _refresh_output(self):
        if not self._result_mcq:
            return
        mcq = self._result_mcq
        if self.fmt_var.get() == "json":
            self._write_output(mcq.to_json(), clear=True)
        else:
            self._render_pretty(mcq)

    def _render_pretty(self, mcq):
        """Syntax-highlighted pretty output."""
        t = self.output_text
        t.config(state="normal")
        t.delete("1.0", "end")

        def ins(text, tag=None):
            if tag:
                t.insert("end", text, tag)
            else:
                t.insert("end", text)

        ins("=" * 62 + "\n", "header")
        ins(f"  {mcq.page_title}\n", "header")
        ins(f"  Source   : {mcq.source_url or 'N/A'}\n", "meta")
        ins(f"  Questions: {mcq.total_questions}  |  Exam time: {mcq.total_exam_time} min\n", "meta")
        ins(f"  {mcq.content_summary}\n", "meta")
        ins("=" * 62 + "\n\n", "header")

        for i, q in enumerate(mcq.questions, 1):
            diff_tag = q.difficulty
            multi_tag = "  [MULTI]" if q.multi else ""
            ins(f"Q{i}. ", "header")
            ins(f"[{q.difficulty.upper()}]", diff_tag)
            if q.multi:
                ins(multi_tag, "multi")
            ins(f"  {q.question_html}\n")
            ins(f"     Marks: +{q.marks} / -{q.negative_marks}\n", "meta")
            ins("\n")
            for j, opt in enumerate(q.options):
                if j in q.answers:
                    ins(f"  ✓  {chr(65+j)}) {opt}\n", "correct")
                else:
                    ins(f"       {chr(65+j)}) {opt}\n", "option")
            if q.explaination:
                ins(f"\n     💡 {q.explaination}\n", "meta")
            ins("\n")

        t.config(state="disabled")

    def _write_output(self, text, clear=False):
        self.output_text.config(state="normal")
        if clear:
            self.output_text.delete("1.0", "end")
        self.output_text.insert("end", text)
        self.output_text.config(state="disabled")

    def _clear_output(self):
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.config(state="disabled")
        self.stats_var.set("No results yet")

    def _copy_output(self):
        content = self.output_text.get("1.0", "end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.status_var.set("Copied to clipboard!")

    def _save_json(self):
        if not self._result_mcq:
            messagebox.showwarning("No results", "Generate questions first.")
            return
        safe = re.sub(r'[\\/*?:"<>|]', "", self._result_mcq.page_title[:30].replace(" ", "_")) or "mcq"
        path = filedialog.asksaveasfilename(
            title="Save MCQ as JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"{safe}_mcq.json"
        )
        if path:
            Path(path).write_text(self._result_mcq.to_json(), encoding="utf-8")
            self.status_var.set(f"Saved to {path}")
            messagebox.showinfo("Saved", f"MCQ JSON saved to:\n{path}")

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _section(self, parent, text):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(10,4))
        tk.Label(f, text=text, font=FONT_BOLD, bg=BG, fg=TEXT).pack(side="left")
        tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(8,0), pady=5)

    def _card(self, parent):
        frame = tk.Frame(parent, bg=CARD, relief="flat", bd=0, padx=12, pady=10)
        frame.pack(fill="x", pady=(0,4))
        return frame

    def _tab_frame(self, parent, _):
        f = tk.Frame(parent, bg=CARD, padx=10, pady=10)
        return f

    def _entry(self, parent, var, placeholder="", show=""):
        e = tk.Entry(parent, textvariable=var, font=FONT,
                     bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=4, show=show)
        if placeholder and not var.get():
            e.insert(0, placeholder)
            e.config(fg=TEXT_DIM)
            def on_focus_in(ev):
                if e.get() == placeholder:
                    e.delete(0, "end")
                    e.config(fg=TEXT)
            def on_focus_out(ev):
                if not e.get():
                    e.insert(0, placeholder)
                    e.config(fg=TEXT_DIM)
            e.bind("<FocusIn>",  on_focus_in)
            e.bind("<FocusOut>", on_focus_out)
        return e

    def _btn(self, parent, text, command, small=False):
        font = ("Segoe UI", 8) if small else FONT_BOLD
        return tk.Button(
            parent, text=text, command=command,
            font=font, bg=ACCENT, fg="white",
            activebackground=ACCENT_H, activeforeground="white",
            relief="flat", bd=0, cursor="hand2",
            padx=10, pady=4
        )

    def _checkbox(self, parent, text, var):
        return tk.Checkbutton(
            parent, text=text, variable=var,
            font=FONT, bg=CARD, fg=TEXT,
            selectcolor=ACCENT, activebackground=CARD,
            activeforeground=TEXT
        )

    def _apply_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG3, foreground=TEXT_DIM,
                         padding=[10, 5], font=FONT)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", TEXT)])
        style.configure("TProgressbar", troughcolor=BG3, background=ACCENT, thickness=4)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = Html2MCQApp()
    app.mainloop()
