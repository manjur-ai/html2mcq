"""Test each model sequentially with live progress output."""
import os, time, json, sys, traceback
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

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

def test_one(model_entry, img_path, gen_kwargs):
    gen = MCQGenerator(**gen_kwargs)
    img_name = os.path.basename(img_path)
    import signal
    start = time.time()
    TIMEOUT = 60

    def handler(signum, frame):
        raise TimeoutError(f"API call timed out after {TIMEOUT}s")

    try:
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(TIMEOUT)
    except:
        pass

    try:
        mcq_set = gen.from_image_paths(img_path, n=3)
        elapsed = time.time() - start
        signal.alarm(0)
        qs = mcq_set.questions
        q_previews = []
        for q in qs:
            q_previews.append({
                "html": q.question_html[:120] if q.question_html else "",
                "answers": q.answers,
                "difficulty": getattr(q, 'difficulty', '?'),
                "explanation": getattr(q, 'explanation', '')[:80],
            })
        return {"status": "ok", "time_sec": round(elapsed, 2), "q_count": len(qs), "questions": q_previews}
    except Exception as e:
        elapsed = time.time() - start
        try:
            signal.alarm(0)
        except:
            pass
        return {"status": "fail", "time_sec": round(elapsed, 2), "error": f"{type(e).__name__}: {str(e)[:200]}"}

all_results = []
gen_kwargs = {"provider": "auto", "ocr_model": "priority_list", "method": "onestep"}

for idx, model in enumerate(CANDIDATES, 1):
    print(f"\n[{idx}/{len(CANDIDATES)}] TESTING: {model}")
    sys.stdout.flush()

    kw = {**gen_kwargs, "ocr_models": [model]}

    for img_path, label in [(IMG1, "img1"), (IMG2, "img2")]:
        res = test_one(model, img_path, kw)
        status = res["status"]
        if status == "ok":
            print(f"  {label}: OK {res['q_count']}q in {res['time_sec']}s")
            for q in res["questions"]:
                print(f"    [{q['difficulty']}] {q['html'][:80]}")
        else:
            print(f"  {label}: FAIL in {res['time_sec']}s - {res['error'][:120]}")
        sys.stdout.flush()

        all_results.append({
            "model": model,
            "image": os.path.basename(img_path),
            **res
        })

# Print summary
print(f"\n\n{'='*90}")
print("SUMMARY")
print(f"{'='*90}")
print(f"{'#':<3} {'Model':<55} {'Img1':>8} {'Img2':>8} {'Total':>6} {'AvgT':>6}")
print("-"*90)

rows = {}
for r in all_results:
    rows.setdefault(r["model"], {"ok": 0, "q": 0, "times": [], "label": r["model"]})
    if r["status"] == "ok":
        rows[r["model"]]["ok"] += 1
        rows[r["model"]]["q"] += r["q_count"]
    rows[r["model"]]["times"].append(r["time_sec"])

sorted_rows = sorted(rows.values(), key=lambda x: (-x["ok"], -x["q"], sum(x["times"])/len(x["times"])))
for rank, r in enumerate(sorted_rows, 1):
    q_per_img = {}
    for res in all_results:
        if res["model"] == r["label"]:
            img_label = "img1" if "13" in res["image"] else "img2"
            q_per_img[img_label] = f"+{res['q_count']}" if res["status"]=="ok" else "FAIL"
    avg_t = sum(r["times"])/len(r["times"])
    print(f"{rank:<3} {r['label'][:54]:<55} {q_per_img.get('img1','?'):>8} {q_per_img.get('img2','?'):>8} {r['q']:>6} {avg_t:>5.1f}s")

report_path = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\model_test_results.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to: {report_path}")
