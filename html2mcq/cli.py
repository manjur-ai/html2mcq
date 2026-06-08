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
    parser.add_argument("--provider", default="openrouter", choices=["anthropic", "openai", "openrouter", "ollama"],
                        help="AI provider (default: openrouter). Use 'ollama' for local LLM.")
    parser.add_argument("--mcq-model", default="", help="MCQ generation model (or 'auto' to try --mcq-models)")
    parser.add_argument("--mcq-models", default="",
                        help="Comma-separated priority model list for --mcq-model auto. "
                             "Runtime-reloadable via HTML2MCQ_MCQ_MODELS env var.")
    parser.add_argument("--api-key", default="", help="API key (or set env var)")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434/v1",
                        help="Ollama API base URL (default: http://localhost:11434/v1). "
                             "Only used when --provider ollama.")
    parser.add_argument("--ocr-model", default="pytesseract",
                        help="OCR backend: 'pytesseract', 'auto', or any OpenRouter model ID "
                             "(e.g. 'openai/gpt-4o'). (default: pytesseract)")
    parser.add_argument("--ocr-models", default="",
                        help="Comma-separated priority model list for --ocr-model auto. "
                             "E.g. 'gpt-4o,gemma-27b,gemma-12b,pytesseract'")
    parser.add_argument("--method", default="twostep", choices=["twostep", "images2mcq"],
                        help="Image processing: 'twostep' (OCR→MCQ) or 'images2mcq' (vision direct). (default: twostep)")
    parser.add_argument("--save-ocr-path", default="",
                        help="File path to save OCR text when method=twostep")
    parser.add_argument("--prompt-log-path", default="",
                        help="Dump prompts to file, or 'stdout' / '-' for terminal")

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
    ocr_models = None
    if args.ocr_models:
        ocr_models = [m.strip() for m in args.ocr_models.split(",") if m.strip()]
    mcq_model_list = None
    if args.mcq_models:
        mcq_model_list = [m.strip() for m in args.mcq_models.split(",") if m.strip()]
    try:
        gen = MCQGenerator(
            api_key=api_key or None,
            provider=args.provider,
            mcq_model=args.mcq_model,
            mcq_model_list=mcq_model_list,
            batch_size=args.batch_size,
            ocr_model=args.ocr_model,
            ocr_models=ocr_models,
            method=args.method,
            save_ocr_path=args.save_ocr_path or None,
            prompt_log_path=args.prompt_log_path or None,
            ollama_base_url=args.ollama_base_url,
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
