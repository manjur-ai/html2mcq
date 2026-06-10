import os, time, sys
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG1 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
IMG2 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.25.jpeg"

model = "(groq)/meta-llama/llama-4-scout-17b-16e-instruct"
gen = MCQGenerator(provider="auto", ocr_model="priority_list", method="onestep", ocr_models=[model])

for img_path, label in [(IMG1, "img1"), (IMG2, "img2")]:
    print(f"[{model[:45]:45s}] {label}: ", end="")
    sys.stdout.flush()
    t0 = time.time()
    try:
        mcq = gen.from_image_paths(img_path)
        sec = time.time() - t0
        qs = mcq.questions
        print(f"{len(qs)}q in {sec:.1f}s")
        for q in qs:
            d = getattr(q, "difficulty", "?")
            print(f"  [{d}] {q.question_html[:100]}")
    except Exception as e:
        sec = time.time() - t0
        print(f"FAIL in {sec:.1f}s: {type(e).__name__}: {str(e)[:150]}")
    sys.stdout.flush()
