import os, time, sys
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
MODELS = [
    "(gemini)/gemini-2.5-flash-lite",
    "(openrouter)/openai-4o-mini",
    "(openrouter)/google/gemma-4-26b-a4b-it:free",
]

for model in MODELS:
    gen = MCQGenerator(provider="auto", ocr_model="priority_list", method="onestep", ocr_models=[model])
    print(f"{model:55s}  ", end="")
    sys.stdout.flush()
    t0 = time.time()
    try:
        mcq = gen.from_image_paths(IMG)  # no n=, uses default n=999
        sec = time.time() - t0
        qs = mcq.questions
        print(f"{len(qs):>2}q in {sec:.1f}s")
        for q in qs:
            d = getattr(q, "difficulty", "?")
            print(f"  [{d}] {q.question_html[:100]}")
    except Exception as e:
        sec = time.time() - t0
        print(f"FAIL in {sec:.1f}s: {type(e).__name__}: {str(e)[:120]}")
    sys.stdout.flush()
