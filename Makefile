.PHONY: test lint format-check gates gate gate-fast gate-truth gate-ci docker-build docker-run-local report snapshot snapshot-openai smoke image smoke-fast smoke-ci image-ci ci ci-local docker-ok daily debug-snapshots explain-smoke dashboard weekly publish-last aws-env-check aws-deploy aws-smoke aws-first-run aws-schedule-status aws-oneoff-run aws-bootstrap aws-bootstrap-help deps deps-sync deps-check snapshot-guard verify-snapshots install-hooks replay gate-replay verify-publish verify-publish-live cronjob-smoke k8s-render k8s-validate k8s-commands k8s-run-once preflight eks-proof-run-help proof-run-vars tf-eks-apply-vars eks-proof-run aws-discover-subnets dr-plan dr-apply dr-validate dr-destroy dr-restore-check

# Prefer repo venv if present; fall back to system python3.
PY ?= .venv/bin/python
DEPS_PY ?= .venv/bin/python
TOOLING_PIP_VERSION ?= 25.0.1
TOOLING_PIPTOOLS_VERSION ?= 7.4.1
JOBINTEL_IMAGE_TAG ?= jobintel:local
SMOKE_PROVIDERS ?= openai
SMOKE_PROFILES ?= cs
SMOKE_SKIP_BUILD ?= 1
SMOKE_UPDATE_SNAPSHOTS ?= 0
SMOKE_MIN_SCORE ?= 40
EKS_S3_BUCKET ?=
# JSON list string, e.g. ["subnet-aaaa","subnet-bbbb"]
EKS_SUBNET_IDS ?=
ifeq ($(wildcard $(PY)),)
PY = python3
endif

define ensure_deps_venv
	@if [ ! -x "$(DEPS_PY)" ]; then \
		echo "Missing .venv. Create it with: PYENV_VERSION=3.12.12 python -m venv .venv"; \
		exit 2; \
	fi
endef

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

format:
	$(PY) -m ruff format .

format-check:
	$(PY) -m ruff format --check .

deps:
	$(call ensure_deps_venv)
	$(DEPS_PY) -m pip install -r requirements.txt

tooling-sync:
	@if [ ! -x "$(DEPS_PY)" ]; then \
		echo "Creating .venv with Python 3.12.12..."; \
		PYENV_VERSION=3.12.12 python -m venv .venv; \
	fi
	$(DEPS_PY) -m pip install --upgrade "pip==$(TOOLING_PIP_VERSION)" setuptools wheel \
		"pip-tools==$(TOOLING_PIPTOOLS_VERSION)"
	$(DEPS_PY) -m pip install -r requirements-dev.txt

deps-sync:
	$(call ensure_deps_venv)
	JIE_PIPTOOLS_VERSION=$(TOOLING_PIPTOOLS_VERSION) \
		$(DEPS_PY) scripts/export_requirements.py
	$(DEPS_PY) -m pip install -r requirements.txt

deps-check:
	$(call ensure_deps_venv)
	JIE_PIPTOOLS_VERSION=$(TOOLING_PIPTOOLS_VERSION) \
		$(DEPS_PY) scripts/export_requirements.py --check

deps-sync-commit:
	$(MAKE) deps-sync
	@git add requirements.txt requirements-dev.txt requirements.in 2>/dev/null || true
	@if git diff --cached --quiet; then \
		echo "No deps changes to commit."; \
		exit 0; \
	fi
	@git commit -m "chore(deps): sync requirements"

gates: format-check lint deps-check test snapshot-guard

gate-fast:
	@echo "==> pytest"
	$(PY) -m pytest -q
	@echo "==> snapshot immutability"
	$(PY) scripts/verify_snapshots_immutable.py
	@echo "==> replay smoke"
	$(PY) scripts/replay_smoke_fixture.py

gate-truth: gate-fast
	@echo "==> docker build (no-cache, RUN_TESTS=1)"
	@if [ "$${DOCKER_BUILDKIT:-1}" = "0" ]; then \
		echo "BuildKit is required (Dockerfile uses RUN --mount=type=cache). Set DOCKER_BUILDKIT=1."; \
		exit 1; \
	fi
	@DOCKER_BUILDKIT=1 docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .

gate: gate-fast

gate-ci: gate-truth

verify-snapshots:
	$(PY) scripts/verify_snapshots_immutable.py

install-hooks:
	@mkdir -p .git/hooks
	@cp scripts/hooks/pre-commit-snapshot-guard.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed pre-commit snapshot guard to .git/hooks/pre-commit"

snapshot-guard: verify-snapshots

replay:
	@if [ -z "$(RUN_ID)" ]; then echo "Usage: make replay RUN_ID=<id>"; exit 2; fi
	$(PY) scripts/replay_run.py --run-id $(RUN_ID) --strict

gate-replay:
	$(PY) -m pytest -q
	$(MAKE) verify-snapshots
	$(PY) scripts/replay_smoke_fixture.py

ecs-shape-smoke:
	$(PY) scripts/ecs_shape_smoke.py

cronjob-smoke:
	@tmp_data=$$(mktemp -d); tmp_state=$$(mktemp -d); \
		JOBINTEL_DATA_DIR=$$tmp_data JOBINTEL_STATE_DIR=$$tmp_state \
		JOBINTEL_CRONJOB_RUN_ID=2026-01-01T00:00:00Z \
		CAREERS_MODE=SNAPSHOT EMBED_PROVIDER=stub ENRICH_MAX_WORKERS=1 DISCORD_WEBHOOK_URL= \
		$(PY) scripts/cronjob_simulate.py; \
		$(PY) scripts/replay_run.py --run-dir $$tmp_state/runs/20260101T000000Z --profile cs --strict --json >/dev/null; \
		rm -rf $$tmp_data $$tmp_state

k8s-render:
	$(PY) scripts/k8s_render.py --secrets

k8s-validate:
	$(PY) scripts/k8s_render.py --secrets --validate || true

prove-cloud-run:
	@echo "Usage: scripts/prove_cloud_run.py --bucket <bucket> --prefix <prefix> --namespace <ns> --job-name <job> [--kube-context <ctx>] [--run-id <id>]"

eks-proof-run-help:
	@role_arn="$$(terraform -chdir=ops/aws/infra/eks output -raw jobintel_irsa_role_arn 2>/dev/null || true)"; \
	update_kube="$$(terraform -chdir=ops/aws/infra/eks output -raw update_kubeconfig_command 2>/dev/null || true)"; \
	if [ -z "$$role_arn" ]; then role_arn="arn:aws:iam::<account>:role/<role>"; fi; \
	if [ -z "$$update_kube" ]; then update_kube="aws eks update-kubeconfig --region <region> --name <cluster>"; fi; \
	echo "$$update_kube"; \
	echo "kubectl config use-context <your-eks-context>"; \
	echo "export JOBINTEL_IRSA_ROLE_ARN=$$role_arn"; \
	echo "export JOBINTEL_S3_BUCKET=<bucket>"; \
	echo "python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml"; \
	echo "kubectl apply -f /tmp/jobintel.yaml"; \
	echo "kubectl -n jobintel create secret generic jobintel-secrets --from-literal=JOBINTEL_S3_BUCKET=$$JOBINTEL_S3_BUCKET --from-literal=DISCORD_WEBHOOK_URL=... --from-literal=OPENAI_API_KEY=..."; \
	echo "kubectl -n jobintel create job --from=cronjob/jobintel-daily jobintel-manual-<yyyymmdd>"; \
	echo "kubectl -n jobintel logs -f job/jobintel-manual-<yyyymmdd>"; \
	echo "python scripts/prove_cloud_run.py --bucket $$JOBINTEL_S3_BUCKET --prefix jobintel --namespace jobintel --job-name jobintel-manual-<yyyymmdd> --kube-context <context>"; \
	echo "python scripts/verify_published_s3.py --bucket $$JOBINTEL_S3_BUCKET --run-id <run_id> --verify-latest"

eks-proof-run:
	@role_arn="$$(terraform -chdir=ops/aws/infra/eks output -raw jobintel_irsa_role_arn 2>/dev/null || true)"; \
	update_kube="$$(terraform -chdir=ops/aws/infra/eks output -raw update_kubeconfig_command 2>/dev/null || true)"; \
	if [ -z "$$role_arn" ]; then role_arn="arn:aws:iam::<account>:role/<role>"; fi; \
	if [ -z "$$update_kube" ]; then update_kube="aws eks update-kubeconfig --region <region> --name <cluster>"; fi; \
	bucket="$(EKS_S3_BUCKET)"; \
	if [ -z "$$bucket" ]; then bucket="<bucket>"; fi; \
	echo "$$update_kube"; \
	echo "kubectl config use-context <your-eks-context>"; \
	echo "export JOBINTEL_IRSA_ROLE_ARN=$$role_arn"; \
	echo "export JOBINTEL_S3_BUCKET=$$bucket"; \
	echo "python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml"; \
	echo "kubectl apply -f /tmp/jobintel.yaml"; \
	echo "kubectl -n jobintel create secret generic jobintel-secrets --from-literal=JOBINTEL_S3_BUCKET=$$JOBINTEL_S3_BUCKET --from-literal=DISCORD_WEBHOOK_URL=... --from-literal=OPENAI_API_KEY=..."; \
	echo "kubectl -n jobintel create job --from=cronjob/jobintel-daily jobintel-manual-<yyyymmdd>"; \
	echo "kubectl -n jobintel logs -f job/jobintel-manual-<yyyymmdd>"; \
	echo "python scripts/prove_cloud_run.py --bucket $$JOBINTEL_S3_BUCKET --prefix jobintel --namespace jobintel --job-name jobintel-manual-<yyyymmdd> --kube-context <context>"; \
	echo "python scripts/verify_published_s3.py --bucket $$JOBINTEL_S3_BUCKET --run-id <run_id> --verify-latest"

proof-run-vars:
	@echo "Required:"
	@echo "  BUCKET=<s3_bucket>"
	@echo "  KUBE_CONTEXT=<kubectl_context>"
	@echo "  NAMESPACE=jobintel"
	@echo "Optional:"
	@echo "  PREFIX=jobintel"

aws-discover-subnets:
	@exclude="$(EXCLUDE_AZ)"; \
	args=""; \
	if [ -n "$$exclude" ]; then \
		IFS=','; set -- $$exclude; \
		for az in $$@; do \
			if [ -n "$$az" ]; then args="$$args --exclude-az $$az"; fi; \
		done; \
	fi; \
	$(PY) scripts/aws_discover_subnets.py $$args

dr-plan:
	APPLY=0 scripts/ops/dr_bringup.sh

dr-apply:
	APPLY=1 scripts/ops/dr_bringup.sh

dr-restore-check:
	@if [ -z "$(BACKUP_URI)" ]; then echo "Usage: make dr-restore-check BACKUP_URI=s3://<bucket>/<prefix>/backups/<backup_id>"; exit 2; fi
	scripts/ops/dr_restore.sh --backup-uri "$(BACKUP_URI)"

dr-validate:
	RUN_JOB=1 scripts/ops/dr_validate.sh

dr-destroy:
	CONFIRM_DESTROY=1 scripts/ops/dr_teardown.sh

k8s-commands:
	@echo "kubectl apply -f ops/k8s/namespace.yaml"
	@echo "kubectl apply -f ops/k8s/serviceaccount.yaml"
	@echo "kubectl apply -f ops/k8s/role.yaml"
	@echo "kubectl apply -f ops/k8s/rolebinding.yaml"
	@echo "kubectl apply -f ops/k8s/configmap.yaml"
	@echo "kubectl apply -f ops/k8s/secret.example.yaml"
	@echo "kubectl apply -f ops/k8s/cronjob.yaml"
	@echo "kubectl apply -f ops/k8s/job.once.yaml  # optional one-off job"

k8s-run-once:
	@echo "kubectl apply -f ops/k8s/namespace.yaml"
	@echo "kubectl apply -f ops/k8s/serviceaccount.yaml"
	@echo "kubectl apply -f ops/k8s/role.yaml"
	@echo "kubectl apply -f ops/k8s/rolebinding.yaml"
	@echo "kubectl apply -f ops/k8s/configmap.yaml"
	@echo "kubectl apply -f ops/k8s/secret.example.yaml"
	@echo "kubectl apply -f ops/k8s/job.once.yaml"
	@echo "kubectl logs -n jobintel job/jobintel-once"
	@echo "# Artifacts live in /app/state inside the pod (emptyDir by default)."

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
	$(PY) scripts/update_snapshots.py --provider openai --out_dir data/openai_snapshots

snapshot:
	@if [ -z "$(provider)" ]; then echo "Usage: make snapshot provider=<name>"; exit 2; fi
	$(PY) scripts/update_snapshots.py --provider $(provider) --out_dir data/$(provider)_snapshots

snapshot-guard:
	bash scripts/assert_snapshots_clean.sh

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
	@$(PY) - <<'PY'
	import importlib.util, sys
	missing = [name for name in ("fastapi", "uvicorn") if importlib.util.find_spec(name) is None]
	if missing:
	    print("Dashboard deps missing (%s). Install with: pip install -e '.[dashboard]'" % ", ".join(missing))
	    sys.exit(2)
	PY
	$(PY) -m uvicorn ji_engine.dashboard.app:app --reload --port 8000

weekly:
	AI_ENABLED=1 AI_JOB_BRIEFS_ENABLED=1 $(PY) scripts/run_daily.py --profiles $(SMOKE_PROFILES) --providers $(SMOKE_PROVIDERS)

publish-last:
	@if [ -z "$(RUN_ID)" ]; then echo "Usage: make publish-last RUN_ID=<id>"; exit 2; fi
	$(PY) scripts/publish_s3.py --run_id $(RUN_ID) --require_s3

verify-publish:
	@if [ -z "$(RUN_ID)" ]; then echo "Usage: make verify-publish RUN_ID=<id> [VERIFY_LATEST=1] [PREFIX=jobintel] [REGION=us-east-1]"; exit 2; fi
	@if [ -z "$${JOBINTEL_S3_BUCKET:-}" ]; then echo "Missing JOBINTEL_S3_BUCKET"; exit 2; fi
	@prefix="$${PREFIX:-$${JOBINTEL_S3_PREFIX:-jobintel}}"; \
	region="$${REGION:-$${JOBINTEL_AWS_REGION:-$${AWS_REGION:-$${AWS_DEFAULT_REGION:-}}}}"; \
	$(PY) scripts/verify_published_s3.py --bucket "$${JOBINTEL_S3_BUCKET}" --run-id "$(RUN_ID)" --prefix "$${prefix}" --offline $$( [ "$${VERIFY_LATEST:-0}" = "1" ] && printf %s "--verify-latest" ) $$( [ -n "$${region}" ] && printf %s " --region $${region}" )

verify-publish-live:
	@if [ -z "$(RUN_ID)" ]; then echo "Usage: make verify-publish-live RUN_ID=<id> [VERIFY_LATEST=1] [PREFIX=jobintel] [REGION=us-east-1]"; exit 2; fi
	@if [ -z "$${JOBINTEL_S3_BUCKET:-}" ]; then echo "Missing JOBINTEL_S3_BUCKET"; exit 2; fi
	@prefix="$${PREFIX:-$${JOBINTEL_S3_PREFIX:-jobintel}}"; \
	region="$${REGION:-$${JOBINTEL_AWS_REGION:-$${AWS_REGION:-$${AWS_DEFAULT_REGION:-}}}}"; \
	$(PY) scripts/verify_published_s3.py --bucket "$${JOBINTEL_S3_BUCKET}" --run-id "$(RUN_ID)" --prefix "$${prefix}" $$( [ "$${VERIFY_LATEST:-0}" = "1" ] && printf %s "--verify-latest" ) $$( [ -n "$${region}" ] && printf %s " --region $${region}" )

aws-env-check:
	@echo "JOBINTEL_S3_BUCKET=$${JOBINTEL_S3_BUCKET:-<unset>}"
	@echo "JOBINTEL_S3_PREFIX=$${JOBINTEL_S3_PREFIX:-jobintel}"
	@if [ -z "$${JOBINTEL_S3_BUCKET:-}" ]; then \
		echo "Missing JOBINTEL_S3_BUCKET"; exit 2; \
	fi

preflight:
	$(PY) scripts/preflight_env.py

tf-eks-init:
	terraform -chdir=ops/aws/infra/eks init

tf-eks-validate:
	terraform -chdir=ops/aws/infra/eks validate

tf-eks-plan:
	@vars=""; \
	if [ -n "$(EKS_S3_BUCKET)" ]; then vars="$$vars -var 's3_bucket=$(EKS_S3_BUCKET)'"; fi; \
	if [ -n "$(EKS_SUBNET_IDS)" ]; then vars="$$vars -var 'subnet_ids=$(EKS_SUBNET_IDS)'"; fi; \
	terraform -chdir=ops/aws/infra/eks plan $$vars

tf-eks-apply:
	@vars=""; \
	if [ -n "$(EKS_S3_BUCKET)" ]; then vars="$$vars -var 's3_bucket=$(EKS_S3_BUCKET)'"; fi; \
	if [ -n "$(EKS_SUBNET_IDS)" ]; then vars="$$vars -var 'subnet_ids=$(EKS_SUBNET_IDS)'"; fi; \
	terraform -chdir=ops/aws/infra/eks apply $$vars

tf-eks-apply-vars:
	@if [ -z "$(EKS_S3_BUCKET)" ] || [ -z "$(EKS_SUBNET_IDS)" ]; then \
		echo "Usage: make tf-eks-apply-vars EKS_S3_BUCKET=<bucket> EKS_SUBNET_IDS='[\"subnet-aaa\",\"subnet-bbb\"]'"; \
		exit 2; \
	fi
	terraform -chdir=ops/aws/infra/eks apply -input=false -auto-approve \
		-var 's3_bucket=$(EKS_S3_BUCKET)' \
		-var 'subnet_ids=$(EKS_SUBNET_IDS)'

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
