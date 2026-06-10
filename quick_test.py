"""Quick test of one model to verify fix works."""
import os, sys, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"

gen = MCQGenerator(
    provider="auto",
    ocr_model="priority_list",
    method="onestep",
    ocr_models=["(gemini)/gemini-2.5-flash-lite"],
)

print("Calling from_image_paths...")
sys.stdout.flush()
t = time.time()
try:
    mcq = gen.from_image_paths(IMG, n=2)
    elapsed = time.time() - t
    print(f"Done in {elapsed:.1f}s, got {len(mcq.questions)} questions")
    for q in mcq.questions:
        diff = getattr(q, "difficulty", "?")
        print(f"  [{diff}] {q.question_html[:100]}")
except Exception as e:
    elapsed = time.time() - t
    print(f"FAIL after {elapsed:.1f}s: {type(e).__name__}: {e}")
