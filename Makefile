.PHONY: test lint format-check gates docker-build docker-run-local report snapshot snapshot-openai smoke image smoke-fast smoke-ci image-ci ci ci-local docker-ok daily

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
JOBINTEL_IMAGE_TAG ?= jobintel:local
SMOKE_PROVIDERS ?= openai
SMOKE_PROFILES ?= cs
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
	$(PY) -m ruff check src scripts tests

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
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) \
		./scripts/smoke_docker.sh --skip-build --providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES)

smoke-fast:
	$(call check_buildkit)
	$(call docker_diag)
	@docker image inspect $(JOBINTEL_IMAGE_TAG) >/dev/null 2>&1 || ( \
		echo "$(JOBINTEL_IMAGE_TAG) image missing; building with make image..."; \
		$(MAKE) image; \
	)
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) \
		./scripts/smoke_docker.sh --providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES)

smoke-ci:
	$(call check_buildkit)
	$(call docker_diag)
	$(MAKE) image-ci
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) \
		./scripts/smoke_docker.sh --skip-build --providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES)

ci: lint test docker-ok smoke-ci

ci-local: lint test

print-config:
	@echo "JOBINTEL_IMAGE_TAG=$(JOBINTEL_IMAGE_TAG)"
	@echo "SMOKE_PROVIDERS=$(SMOKE_PROVIDERS)"
	@echo "SMOKE_PROFILES=$(SMOKE_PROFILES)"
	$(call docker_diag)

daily:
	$(MAKE) print-config
	$(MAKE) image
	@mode="$${JOBINTEL_MODE:-SNAPSHOT}"; \
	offline_flag="--offline"; \
	if [ "$$mode" = "LIVE" ]; then offline_flag=""; fi; \
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) \
		./scripts/smoke_docker.sh --skip-build --providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES) $$offline_flag
