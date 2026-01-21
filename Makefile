.PHONY: test lint format-check gates docker-build docker-run-local report snapshot snapshot-openai smoke

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
	$(PY) -m ruff check src

format-check:
	$(PY) -m ruff format --check src

gates: format-check lint test

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

snapshot-openai:
	$(PY) scripts/update_snapshots.py --provider openai

snapshot:
	@if [ -z "$(provider)" ]; then echo "Usage: make snapshot provider=<name>"; exit 2; fi
	$(PY) scripts/update_snapshots.py --provider $(provider)

smoke:
	./scripts/smoke_docker.sh

smoke-fast:
	SMOKE_SKIP_BUILD=1 ./scripts/smoke_docker.sh
