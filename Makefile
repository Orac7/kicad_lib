# Component library tooling — lives in <library>/management_scripts/
#
#   make scan     — scan KiCad symbol libs (one level up), sync ../klib_contents.csv
#   make serve    — serve the search page locally with live tag editing to disk
#   make check    — list components still missing datasheet / order code
#   make deps     — install the Python dependency (kiutils)
#   make install-hooks — enable the pre-push hook
#
# Targets work whether you run `make` from here or via `make -C management_scripts`.
# The scripts anchor their own paths to the parent (library root), so the CSV and
# KiCad files are always found regardless of the working directory.
#
# On Windows, run from Git Bash. If `python3` is unset, pass PY=python.

# Directory this Makefile lives in, so paths are correct from any CWD.
HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PY   ?= python3
PORT ?= 8000

.PHONY: scan serve check deps install-hooks

scan:
	$(PY) "$(HERE)scan_lib.py"

# Tag edits in the browser save straight into ../klib_contents.csv on disk.
serve:
	PORT=$(PORT) $(PY) "$(HERE)serve_local.py"

check:
	@$(PY) -c "import csv; \
rows=list(csv.DictReader(open('$(HERE)../klib_contents.csv'))); \
miss=[r['name'] for r in rows if not r['datasheet'] or not r['order_code']]; \
print('Missing metadata:', ', '.join(miss) if miss else 'none')"

deps:
	$(PY) -m pip install kiutils

# Hook script lives in the repo root's .githooks/; enable from the root.
install-hooks:
	git -C "$(HERE).." config core.hooksPath .githooks
	@echo "pre-push hook enabled (.githooks/pre-push)."