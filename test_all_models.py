"""Test all models sequentially with live progress."""
import os, sys, time, json
sys.stdout.reconfigure(encoding="utf-8")

from html2mcq import MCQGenerator

IMG1 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
IMG2 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.25.jpeg"

CANDIDATES = [
    "(gemini)/gemini-2.5-flash-lite",
    "(gemini)/gemini-1.5-flash",
    "(groq)/meta-llama/llama-4-scout-17b-16e-instruct",
    "(openrouter)/google/gemma-4-31b-it:free",
    "(openrouter)/google/gemma-4-26b-a4b-it:free",
    "(openrouter)/google/gemma-3-27b-it:free",
    "(openrouter)/google/gemini-2.0-flash-lite:free",
    "(openrouter)/nvidia/nemotron-nano-12b-v2-vl:free",
    "(openrouter)/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "(openrouter)/google/gemma-3-12b-it:free",
]

all_results = []
gen_base = {"provider": "auto", "ocr_model": "priority_list", "method": "onestep"}

for idx, model in enumerate(CANDIDATES, 1):
    for img_path, label in [(IMG1, "img1"), (IMG2, "img2")]:
        print(f"[{idx}/{len(CANDIDATES)}] {label:4s} => {model}")
        sys.stdout.flush()

        gen = MCQGenerator(**gen_base, ocr_models=[model])
        t0 = time.time()
        try:
            mcq = gen.from_image_paths(img_path, n=3)
            sec = time.time() - t0
            qs = mcq.questions
            print(f"  OK {len(qs)}q in {sec:.1f}s")
            sys.stdout.flush()
            for q in qs:
                d = getattr(q, "difficulty", "?")
                print(f"    [{d}] {q.question_html[:90]}")
                sys.stdout.flush()
            all_results.append({
                "model": model, "img": label, "status": "ok",
                "time": round(sec, 1), "q": len(qs)
            })
        except Exception as e:
            sec = time.time() - t0
            print(f"  FAIL in {sec:.1f}s: {type(e).__name__}: {str(e)[:100]}")
            sys.stdout.flush()
            all_results.append({
                "model": model, "img": label, "status": "fail",
                "time": round(sec, 1), "q": 0, "err": str(e)[:120]
            })

print()
print("=" * 90)
print("SUMMARY (sorted: both images OK first, then by total questions, then by speed)")
print("=" * 90)

models = set(r["model"] for r in all_results)
rows = []
for m in models:
    entries = [r for r in all_results if r["model"] == m]
    ok = sum(1 for r in entries if r["status"] == "ok")
    qs = sum(r.get("q", 0) for r in entries)
    ts = [r["time"] for r in entries]
    avg_t = sum(ts) / len(ts)
    img1 = next((r for r in entries if r.get("img") == "img1"), {})
    img2 = next((r for r in entries if r.get("img") == "img2"), {})
    s1 = str(img1.get("q", "F")) if img1.get("status") == "ok" else "F"
    s2 = str(img2.get("q", "F")) if img2.get("status") == "ok" else "F"
    rows.append((ok, qs, avg_t, m, s1, s2))
rows.sort(key=lambda x: (-x[0], -x[1], x[2]))

rank_header = f"{'#':<3} {'Model':<55} {'I1':>4} {'I2':>4} {'Qs':>5} {'Avg':>6}"
print(rank_header)
print("-" * 90)
for rank, (ok, qs, avg_t, mod, s1, s2) in enumerate(rows, 1):
    print(f"{rank:<3} {mod[:54]:<55} {s1:>4} {s2:>4} {qs:>5} {avg_t:>5.1f}s")

report_path = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\model_test_results.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to: {report_path}")
