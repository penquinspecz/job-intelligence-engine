.PHONY: test lint format-check gates docker-build docker-run-local report snapshot snapshot-openai smoke image smoke-fast smoke-ci image-ci ci ci-local docker-ok

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
JOBINTEL_IMAGE_TAG ?= jobintel:local
ifeq ($(wildcard $(PY)),)
PY = python3
endif

PROFILE ?= cs
LIMIT ?= 15

define check_buildkit
	@if [ "$${DOCKER_BUILDKIT:-1}" = "0" ]; then \
		echo "BuildKit is required (Dockerfile uses RUN --mount=type=cache). Set DOCKER_BUILDKIT=1."; \
		exit 1; \
	fi
endef

define docker_diag
	@echo "Docker context: $$(docker context show 2>/dev/null || echo unknown)"; \
	context="$$(docker context show 2>/dev/null || echo default)"; \
	host="$$(docker context inspect "$$context" --format '{{json .Endpoints.docker.Host}}' 2>/dev/null || echo unknown)"; \
	echo "Docker host: $$host"
endef

docker-ok:
	$(call docker_diag)
	@if ! docker info >/dev/null 2>&1; then \
		echo "Docker is not available for the active context. Fix Docker permissions or context."; \
		exit 1; \
	fi
test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src

format-check:
	$(PY) -m ruff format --check src

gates: format-check lint test

docker-build:
	$(call check_buildkit)
	$(call docker_diag)
	docker build -t $(JOBINTEL_IMAGE_TAG) --build-arg RUN_TESTS=0 .

image: docker-build

image-ci:
	$(call check_buildkit)
	$(call docker_diag)
	docker build -t $(JOBINTEL_IMAGE_TAG) --build-arg RUN_TESTS=1 .

docker-run-local:
	docker run --rm \
		-v "$$PWD/data:/app/data" \
		-v "$$PWD/state:/app/state" \
		$(JOBINTEL_IMAGE_TAG) \
		--profiles cs --us_only --no_post --no_enrich

report:
	docker run --rm \
		-v "$$PWD/state:/app/state" \
		--entrypoint python \
		$(JOBINTEL_IMAGE_TAG) \
		-m scripts.report_changes --profile $(PROFILE) --limit $(LIMIT)

snapshot-openai:
	$(PY) scripts/update_snapshots.py --provider openai

snapshot:
	@if [ -z "$(provider)" ]; then echo "Usage: make snapshot provider=<name>"; exit 2; fi
	$(PY) scripts/update_snapshots.py --provider $(provider)

smoke:
	$(call check_buildkit)
	$(call docker_diag)
	$(MAKE) image
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 ./scripts/smoke_docker.sh --skip-build

smoke-fast:
	$(call check_buildkit)
	$(call docker_diag)
	@docker image inspect $(JOBINTEL_IMAGE_TAG) >/dev/null 2>&1 || ( \
		echo "$(JOBINTEL_IMAGE_TAG) image missing; building with make image..."; \
		$(MAKE) image; \
	)
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 ./scripts/smoke_docker.sh

smoke-ci:
	$(call check_buildkit)
	$(call docker_diag)
	$(MAKE) image-ci
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 ./scripts/smoke_docker.sh --skip-build --providers openai --profiles cs

ci: lint test docker-ok smoke-ci

ci-local: lint test
	@if $(MAKE) docker-ok >/dev/null 2>&1; then \
		echo "Docker OK; running smoke-ci."; \
		$(MAKE) smoke-ci; \
	else \
		echo "Docker unavailable; skipping smoke-ci for ci-local."; \
	fi
