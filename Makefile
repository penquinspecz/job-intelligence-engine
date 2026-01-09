.PHONY: test lint docker-build docker-run-local report

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
ifeq ($(wildcard $(PY)),)
PY = python3
endif

PROFILE ?= cs
LIMIT ?= 15

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

docker-build:
	docker build -t jobintel:local .

docker-run-local:
	docker run --rm \
		-v "$$PWD/data:/app/data" \
		-v "$$PWD/state:/app/state" \
		jobintel:local \
		--profiles cs --us_only --no_post --no_enrich

report:
	docker run --rm \
		-v "$$PWD/state:/app/state" \
		--entrypoint python \
		jobintel:local \
		-m scripts.report_changes --profile $(PROFILE) --limit $(LIMIT)
