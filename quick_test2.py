import os, time, sys
sys.stdout.reconfigure(encoding="utf-8")

model = "(openrouter)/openai-4o-mini"
from html2mcq import MCQGenerator

gen = MCQGenerator(provider="auto", ocr_model="priority_list", method="onestep", ocr_models=[model])
img = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
print(f"Testing: {model}")
sys.stdout.flush()
t0 = time.time()
try:
    mcq = gen.from_image_paths(img, n=2)
    sec = time.time() - t0
    print(f"OK {len(mcq.questions)}q in {sec:.1f}s")
    for q in mcq.questions:
        d = getattr(q, "difficulty", "?")
        print(f"  [{d}] {q.question_html[:100]}")
except Exception as e:
    sec = time.time() - t0
    print(f"FAIL in {sec:.1f}s: {type(e).__name__}: {str(e)[:200]}")
