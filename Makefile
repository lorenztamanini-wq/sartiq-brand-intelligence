# Brand Intelligence Agent — one-command setup + demo.
# `make setup` then `make demo` takes you from clone to three ranked briefs.
.PHONY: help setup demo test live clean
VENV := .venv
PY := $(VENV)/bin/python

help:
	@echo "make setup   # venv + install deps + scaffold .env"
	@echo "make demo    # OVS/Sandro/Diesel briefs + ranked dashboard (offline, no key)"
	@echo "make test    # run the test suite"
	@echo "make live    # one live brief (needs ANTHROPIC_API_KEY in .env)"
	@echo "make clean   # remove generated output + caches"

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "Setup done. Run 'make demo'."

demo:
	$(PY) cli.py --all --offline
	@echo "→ open output/index.html (ranked dashboard, click any brief)"

test:
	$(PY) -m unittest discover -s tests

live:
	$(PY) cli.py "Sandro" --live

clean:
	rm -rf output __pycache__ */__pycache__ tests/__pycache__ tool_impl/__pycache__
