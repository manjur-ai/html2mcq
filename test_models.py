"""Test each model in the priority list against two test images, compare results."""
import os, time, json, sys, traceback
from html2mcq import MCQGenerator

IMG1 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.13.jpeg"
IMG2 = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\WhatsApp Image 2026-06-07 at 18.53.25.jpeg"

# Each model candidate as it would appear in HTML2MCQ_OCR_MODELS
CANDIDATES = [
    "(gemini)/gemini-2.5-flash-lite",
    "(groq)/meta-llama/llama-4-scout-17b-16e-instruct",
    "(gemini)/gemini-1.5-flash",
    "(openrouter)/google/gemma-4-31b-it:free",
    "(openrouter)/google/gemma-4-26b-a4b-it:free",
    "(openrouter)/google/gemma-3-27b-it:free",
    "(openrouter)/google/gemini-2.0-flash-lite:free",
    "(openrouter)/nvidia/nemotron-nano-12b-v2-vl:free",
    "(openrouter)/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "(openrouter)/google/gemma-3-12b-it:free",
]


def test_model(model_entry):
    """Test a single model against both images."""
    print(f"\n{'='*65}")
    print(f"  MODEL: {model_entry}")
    print(f"{'='*65}")

    gen = MCQGenerator(
        provider="auto",
        ocr_model="priority_list",
        method="onestep",
        ocr_models=[model_entry],
    )

    result = {
        "model": model_entry,
        "images": {},
        "total_questions": 0,
        "succeeded": 0,
        "failed": 0,
    }

    for img_path in [IMG1, IMG2]:
        img_name = os.path.basename(img_path)
        print(f"\n  --- {img_name} ---")

        start = time.time()
        try:
            mcq_set = gen.from_image_paths(img_path, n=3)
            elapsed = time.time() - start
            qs = mcq_set.questions
            q_count = len(qs)
            result["succeeded"] += 1
            result["total_questions"] += q_count

            q_previews = []
            for i, q in enumerate(qs):
                q_html = q.question_html[:120] if q.question_html else "(no html)"
                answers = q.answers
                difficulty = getattr(q, 'difficulty', '?')
                explanation = getattr(q, 'explanation', '')[:60]
                q_previews.append({
                    "html": q_html,
                    "answers": answers,
                    "difficulty": difficulty,
                    "explanation": explanation,
                })

            result["images"][img_name] = {
                "status": "ok",
                "time_sec": round(elapsed, 2),
                "question_count": q_count,
                "questions": q_previews,
            }
            print(f"  OK {q_count} questions in {elapsed:.1f}s")
            for i, q in enumerate(qs):
                diff = getattr(q, 'difficulty', '?')
                print(f"      Q{i+1}: [{diff}] {q.question_html[:100]}")
        except Exception as e:
            elapsed = time.time() - start
            tb = traceback.format_exc()
            err_msg = f"{type(e).__name__}: {str(e)[:300]}"
            result["failed"] += 1
            result["images"][img_name] = {
                "status": "fail",
                "time_sec": round(elapsed, 2),
                "error": err_msg,
                "traceback": tb,
            }
            print(f"  FAIL {elapsed:.1f}s: {err_msg}")

    return result


def main():
    print("=" * 65)
    print("  MODEL COMPARISON - TWO TEST IMAGES")
    print("=" * 65)

    all_results = []
    for model_entry in CANDIDATES:
        res = test_model(model_entry)
        all_results.append(res)

    print(f"\n\n{'='*90}")
    print("  S U M M A R Y   (sorted: fully working first, then by quality)")
    print(f"{'='*90}")
    print(f"{'#':<3} {'Model':<55} {'Img1':>8} {'Img2':>8} {'TotalQs':>8} {'AvgT':>7}")
    print("-"*90)

    all_results.sort(key=lambda r: (-r["succeeded"], -r["total_questions"]))
    for rank, r in enumerate(all_results, 1):
        short = r["model"][:54]
        img1 = r["images"].get(os.path.basename(IMG1), {})
        img2 = r["images"].get(os.path.basename(IMG2), {})
        s1 = f"+{img1.get('question_count','?')}" if img1.get("status")=="ok" else "FAIL"
        s2 = f"+{img2.get('question_count','?')}" if img2.get("status")=="ok" else "FAIL"
        total_q = r["total_questions"]
        times = [v.get("time_sec",0) for v in r["images"].values() if v.get("time_sec")]
        avg_t = sum(times)/len(times) if times else 0
        print(f"{rank:<3} {short:<55} {s1:>8} {s2:>8} {total_q:>8} {avg_t:>6.1f}s")

    report_path = r"C:\Users\ASUS\Downloads\html2mcq\html2mcq\model_test_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {report_path}")


if __name__ == "__main__":
    main()
