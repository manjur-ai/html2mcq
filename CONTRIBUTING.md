# Contributing to html2mcq

## Setup

```bash
git clone https://github.com/manjur-ai/html2mcq
cd html2mcq
pip install -e ".[dev,pdf,anthropic]"
```

## Running tests

```bash
pytest tests/ -v --cov=html2mcq
```

## Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```
