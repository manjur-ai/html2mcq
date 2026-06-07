"""
examples/basic_usage.py
=======================
Demonstrates all major html2mcq usage patterns.
Set your API key before running:
    export ANTHROPIC_API_KEY="sk-ant-..."
"""
import os
import json

# ── 1. From a live URL ────────────────────────────────────────────────────────
from html2mcq import MCQGenerator

gen = MCQGenerator(provider="anthropic")   # reads ANTHROPIC_API_KEY from env

mcq_set = gen.from_url(
    "https://docs.python.org/3/tutorial/introduction.html",
    n=5,
    difficulty_mix="40% easy, 40% medium, 20% hard",
    focus_topics=["data types", "operators"],
)

print(mcq_set.to_pretty_str())


# ── 2. From raw HTML ─────────────────────────────────────────────────────────
HTML = """
<html><body>
<h1>Sorting Algorithms</h1>
<p>Bubble sort repeatedly steps through the list, compares adjacent elements,
and swaps them if they are in the wrong order.</p>
<p>Quick sort selects a pivot element and partitions the array around it,
recursively sorting each partition.</p>
<pre><code class="language-python">
def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(n-i-1):
            if arr[j] > arr[j+1]:
                arr[j], arr[j+1] = arr[j+1], arr[j]
</code></pre>
<img src="https://upload.wikimedia.org/wikipedia/commons/c/c8/Bubble_sort.png"
     alt="Bubble sort animation showing element swaps">
<a href="https://www.youtube.com/watch?v=xli_FI7CuzA">Watch: Merge Sort Explained</a>
<a href="/docs/sorting-cheatsheet.pdf">Download Sorting Algorithms PDF</a>
</body></html>
"""

mcq_set2 = gen.from_html(HTML, n=3, base_url="https://example.com/")

# Save as JSON
with open("/tmp/sorting_quiz.json", "w") as f:
    f.write(mcq_set2.to_json())
print("Saved to /tmp/sorting_quiz.json")

# ── 3. Filter by difficulty ───────────────────────────────────────────────────
easy_only = mcq_set2.filter_by_difficulty("easy")
print(f"\nEasy questions: {easy_only.total_questions}")

# ── 4. Using OpenAI ───────────────────────────────────────────────────────────
# gen_oai = MCQGenerator(provider="openai", model="gpt-4o-mini")
# mcq_oai = gen_oai.from_url("https://example.com/tutorial", n=10)

# ── 5. Using OpenRouter (free models) ────────────────────────────────────────
# gen_or = MCQGenerator(
#     provider="openrouter",
#     model="meta-llama/llama-3.3-70b-instruct:free",
#     api_key=os.environ["OPENROUTER_API_KEY"],
# )
# mcq_or = gen_or.from_url("https://example.com/tutorial", n=10)
