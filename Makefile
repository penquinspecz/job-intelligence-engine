.PHONY: run test-post test enrich score all

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
ifeq ($(wildcard $(PY)),)
PY = python3
endif

PROFILE ?= cs

run:
	$(PY) scripts/run_daily.py --profiles cs,tam,se --us_only --min_alert_score 85

test-post:
	$(PY) scripts/run_daily.py --test_post

test:
	$(PY) -m pytest -q

enrich:
	$(PY) scripts/run_ai_augment.py

score:
	$(PY) scripts/score_jobs.py --profile $(PROFILE)

all: test enrich score
