.PHONY: test lint format-check gates gate docker-build docker-run-local report snapshot snapshot-openai smoke image smoke-fast smoke-ci image-ci ci ci-local docker-ok daily debug-snapshots explain-smoke dashboard weekly publish-last aws-env-check aws-deploy aws-smoke aws-first-run aws-schedule-status aws-oneoff-run aws-bootstrap aws-bootstrap-help deps deps-sync deps-check snapshot-guard

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
JOBINTEL_IMAGE_TAG ?= jobintel:local
SMOKE_PROVIDERS ?= openai
SMOKE_PROFILES ?= cs
SMOKE_SKIP_BUILD ?= 1
SMOKE_UPDATE_SNAPSHOTS ?= 0
SMOKE_MIN_SCORE ?= 40
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

deps:
	$(PY) -m pip install -r requirements.txt

deps-sync:
	$(PY) scripts/export_requirements.py
	$(PY) -m pip install -r requirements.txt

deps-check:
	$(PY) scripts/export_requirements.py --check

gates: format-check lint deps-check test snapshot-guard

gate: gates

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
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=$(SMOKE_SKIP_BUILD) SMOKE_UPDATE_SNAPSHOTS=$(SMOKE_UPDATE_SNAPSHOTS) \
		SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) SMOKE_MIN_SCORE=$(SMOKE_MIN_SCORE) \
		./scripts/smoke_docker.sh $(if $(filter 1,$(SMOKE_SKIP_BUILD)),--skip-build,) \
		--providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES)

smoke-fast:
	$(call check_buildkit)
	$(call docker_diag)
	@if [ "$(SMOKE_SKIP_BUILD)" = "1" ]; then \
		docker image inspect $(JOBINTEL_IMAGE_TAG) >/dev/null 2>&1 || ( \
			echo "$(JOBINTEL_IMAGE_TAG) image missing; building with make image..."; \
			$(MAKE) image; \
		); \
	fi
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=$(SMOKE_SKIP_BUILD) SMOKE_UPDATE_SNAPSHOTS=$(SMOKE_UPDATE_SNAPSHOTS) \
		SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) SMOKE_MIN_SCORE=$(SMOKE_MIN_SCORE) \
		./scripts/smoke_docker.sh $(if $(filter 1,$(SMOKE_SKIP_BUILD)),--skip-build,) \
		--providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES)

smoke-ci:
	$(call check_buildkit)
	$(call docker_diag)
	$(MAKE) image-ci
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_UPDATE_SNAPSHOTS=$(SMOKE_UPDATE_SNAPSHOTS) \
		SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) SMOKE_MIN_SCORE=$(SMOKE_MIN_SCORE) \
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
	IMAGE_TAG=$(JOBINTEL_IMAGE_TAG) SMOKE_SKIP_BUILD=1 SMOKE_UPDATE_SNAPSHOTS=$(SMOKE_UPDATE_SNAPSHOTS) \
		SMOKE_PROVIDERS=$(SMOKE_PROVIDERS) SMOKE_PROFILES=$(SMOKE_PROFILES) SMOKE_MIN_SCORE=$(SMOKE_MIN_SCORE) \
		./scripts/smoke_docker.sh --skip-build --providers $(SMOKE_PROVIDERS) --profiles $(SMOKE_PROFILES) $$offline_flag

debug-snapshots:
	$(call docker_diag)
	docker run --rm --entrypoint sh $(JOBINTEL_IMAGE_TAG) -lc '\
		echo "==> /app/data/openai_snapshots"; \
		ls -la /app/data/openai_snapshots | head; \
		echo "==> /app/data/openai_snapshots/jobs"; \
		if [ -d /app/data/openai_snapshots/jobs ]; then \
			ls -la /app/data/openai_snapshots/jobs | head; \
			ls -la /app/data/openai_snapshots/jobs | wc -l; \
		else \
			echo "Missing /app/data/openai_snapshots/jobs"; \
		fi'

explain-smoke:
	@if [ ! -f smoke_artifacts/openai_enriched_jobs.json ]; then \
		echo "Missing smoke_artifacts/openai_enriched_jobs.json. Run make smoke-fast first."; \
		exit 1; \
	fi
	$(PY) scripts/score_jobs.py --profile cs \
		--in_path smoke_artifacts/openai_enriched_jobs.json \
		--min_score $(SMOKE_MIN_SCORE) \
		--explain_top_n 10 \
		--out_json /tmp/openai_ranked_jobs.cs.json \
		--out_md /tmp/openai_shortlist.cs.md \
		--out_md_top_n /tmp/openai_top.cs.md

dashboard:
	@$(PY) - <<'PY' || true
import importlib.util
if importlib.util.find_spec("uvicorn") is None:
    print('Warning: dashboard deps missing. Run: pip install ".[dashboard]"')
PY
	$(PY) -m uvicorn jobintel.dashboard.app:app --reload --port 8000

weekly:
	AI_ENABLED=1 AI_JOB_BRIEFS_ENABLED=1 $(PY) scripts/run_daily.py --profiles $(SMOKE_PROFILES) --providers $(SMOKE_PROVIDERS)

publish-last:
	@if [ -z "$(RUN_ID)" ]; then echo "Usage: make publish-last RUN_ID=<id>"; exit 2; fi
	$(PY) scripts/publish_s3.py --run_id $(RUN_ID) --require_s3

aws-env-check:
	@echo "JOBINTEL_S3_BUCKET=$${JOBINTEL_S3_BUCKET:-<unset>}"
	@echo "JOBINTEL_S3_PREFIX=$${JOBINTEL_S3_PREFIX:-jobintel}"
	@if [ -z "$${JOBINTEL_S3_BUCKET:-}" ]; then \
		echo "Missing JOBINTEL_S3_BUCKET"; exit 2; \
	fi

aws-deploy:
	@cd ops/aws/infra && terraform apply

aws-smoke:
	$(PY) scripts/aws_deploy_smoke.py

aws-first-run:
	@$(MAKE) aws-smoke
	@echo "One-off ECS task (edit placeholders):"
	@echo "aws ecs run-task \\"
	@echo "  --cluster <cluster-arn> \\"
	@echo "  --task-definition jobintel-daily \\"
	@echo "  --launch-type FARGATE \\"
	@echo "  --network-configuration \"awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}\""

aws-schedule-status:
	$(PY) scripts/aws_schedule_status.py

aws-oneoff-run:
	$(PY) scripts/aws_oneoff_run.py

aws-bootstrap:
	@if [ -z "$${IMAGE_URI:-}" ]; then echo "IMAGE_URI is required (ECR image URI)."; exit 2; fi
	$(PY) scripts/aws_bootstrap_prod.py

aws-bootstrap-help:
	@echo "Required env: IMAGE_URI=<ecr image uri>"
	@echo "Find cluster ARN: aws ecs list-clusters --region <region>"
	@echo "Describe subnets: aws ec2 describe-subnets --region <region>"
	@echo "Describe security groups: aws ec2 describe-security-groups --region <region>"
