import os, time, sys
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"

# Free vision models from OpenRouter that haven't been tested or might have reset limits
MODELS = [
    "(openrouter)/nex-agi/nex-n2-pro:free",
    "(openrouter)/google/gemma-4-31b-it:free",
]

for model in MODELS:
    gen = MCQGenerator(provider="auto", ocr_model="priority_list", method="onestep", ocr_models=[model])
    print(f"{model:55s}  ", end="")
    sys.stdout.flush()
    t0 = time.time()
    try:
        mcq = gen.from_image_paths(IMG)
        sec = time.time() - t0
        qs = mcq.questions
        print(f"{len(qs)}q in {sec:.1f}s")
        for q in qs:
            d = getattr(q, "difficulty", "?")
            print(f"  [{d}] {q.question_html[:100]}")
    except Exception as e:
        sec = time.time() - t0
        err = str(e)[:150]
        print(f"FAIL in {sec:.1f}s: {type(e).__name__}: {err}")
    sys.stdout.flush()
