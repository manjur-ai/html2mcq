"""Retest the two working models with both images to verify fix."""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG1 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
IMG2 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.25.jpeg"

WORKING = [
    "(gemini)/gemini-2.5-flash-lite",
    "(openrouter)/google/gemma-4-26b-a4b-it:free",
]

for model in WORKING:
    gen = MCQGenerator(provider="auto", ocr_model="priority_list", method="onestep", ocr_models=[model])
    for img_path, label in [(IMG1, "img1"), (IMG2, "img2")]:
        print(f"[{model[:40]:40s}] {label}: ", end="")
        sys.stdout.flush()
        t0 = time.time()
        try:
            mcq = gen.from_image_paths(img_path, n=3)
            sec = time.time() - t0
            qs = mcq.questions
            print(f"OK {len(qs)}q in {sec:.1f}s")
            for q in qs:
                d = getattr(q, "difficulty", "?")
                print(f"  [{d}] {q.question_html[:100]}")
        except Exception as e:
            sec = time.time() - t0
            print(f"FAIL in {sec:.1f}s: {type(e).__name__}: {str(e)[:120]}")
        sys.stdout.flush()
