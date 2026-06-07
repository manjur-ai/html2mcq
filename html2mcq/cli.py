"""
html2mcq CLI
============

Usage examples
--------------
html2mcq https://docs.python.org/3/tutorial/ --n 15
html2mcq https://example.com/tutorial --n 10 --provider openai --output quiz.json
html2mcq --html page.html --n 5 --difficulty "50% easy, 50% medium"
"""
import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="html2mcq",
        description="Convert any HTML tutorial page to MCQ questions using AI.",
    )

    # Input
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("url", nargs="?", help="URL of the tutorial page")
    input_group.add_argument("--html", metavar="FILE", help="Path to a local HTML file")

    # Generation options
    parser.add_argument("-n", "--n", type=int, default=10, help="Number of questions (default: 10)")
    parser.add_argument("--difficulty", default=None, help='E.g. "30%% easy, 40%% medium, 30%% hard"')
    parser.add_argument("--topics", nargs="*", help="Focus topics")
    parser.add_argument("--instructions", "-i", default="",
                        help='Custom instructions e.g. "Make answers very close and confusing"')
    parser.add_argument("--batch-size", type=int, default=10, help="Questions per API call (default: 10)")

    # AI provider
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "openrouter"],
                        help="AI provider (default: anthropic)")
    parser.add_argument("--model", default="", help="Override model name")
    parser.add_argument("--api-key", default="", help="API key (or set env var)")

    # Output
    parser.add_argument("--output", "-o", default="", help="Output file (.json or .txt). Default: stdout")
    parser.add_argument("--format", choices=["json", "pretty"], default="pretty",
                        help="Output format (default: pretty)")

    args = parser.parse_args()

    # Lazy import to keep startup fast
    try:
        from html2mcq import MCQGenerator
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    api_key = args.api_key or ""
    try:
        gen = MCQGenerator(
            api_key=api_key or None,
            provider=args.provider,
            model=args.model,
            batch_size=args.batch_size,
        )
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.html:
            with open(args.html, encoding="utf-8") as f:
                html = f.read()
            mcq_set = gen.from_html(html, n=args.n,
                                    difficulty_mix=args.difficulty,
                                    focus_topics=args.topics,
                                    custom_instructions=args.instructions or None)
        else:
            print(f"Fetching and analysing: {args.url}", file=sys.stderr)
            mcq_set = gen.from_url(args.url, n=args.n,
                                   difficulty_mix=args.difficulty,
                                   focus_topics=args.topics,
                                   custom_instructions=args.instructions or None)
    except Exception as e:
        print(f"Generation failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Format output
    if args.format == "json":
        output = mcq_set.to_json()
    else:
        output = mcq_set.to_pretty_str()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved {mcq_set.total_questions} questions to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
