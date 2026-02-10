# EKS bootstrap (minimal)

This directory provides a minimal EKS cluster + IRSA role for JobIntel.

## Prerequisites

- OpenTofu (or Terraform) >= 1.4
- AWS CLI configured with EKS + IAM + EC2 permissions
- Existing EKS cluster `jobintel-eks` and subnets

## Required variables

- `s3_bucket`: bucket name for publish
- `subnet_ids`: list of subnet IDs for the EKS cluster/node group

## Optional variables

- `region`: default `us-east-1`
- `cluster_name`: default `jobintel-eks`
- `k8s_version`: default `1.29`
- `node_instance_types`: default `["t3.medium"]`
- `node_min`, `node_desired`, `node_max`
- `s3_prefix`: default `jobintel`
- `k8s_namespace`: default `jobintel`
- `serviceaccount_name`: default `jobintel`
- `tag_subnets`: default `true` (adds `kubernetes.io/cluster/<name>=shared`)

## Boring non-interactive flow (canonical)

Run from repo root:

```bash
export AWS_PROFILE=jobintel-deployer AWS_REGION=us-east-1 AWS_EC2_METADATA_DISABLED=true CLUSTER_NAME=jobintel-eks JOBINTEL_ARTIFACTS_BUCKET=<bucket> RUN_ID=local
python scripts/tofu_eks_vars_from_aws.py
scripts/ops/tofu_eks_guardrails.sh && scripts/ops/tofu_state_check.sh
make ops-eks-plan RUN_ID="$RUN_ID"
```

Makefile equivalent:

```bash
make tofu-eks-vars
make tofu-eks-guardrails
make ops-eks-plan RUN_ID=local
```

`scripts/tofu_eks_vars_from_aws.py` writes `ops/aws/infra/eks/local.auto.tfvars.json` using authoritative AWS cluster data (`aws eks describe-cluster`).  
`scripts/ops/tofu_eks_guardrails.sh` hard-fails when identity/state checks are unsafe (for example, empty state or mismatched cluster name).

## One-command plan bundle (no apply)

Use the operator-safe wrapper to run identity checks, var generation, state alignment checks, `tofu fmt`, `tofu validate`, and `tofu plan -out=...` while capturing evidence:

```bash
AWS_PROFILE=jobintel-deployer AWS_REGION=us-east-1 AWS_EC2_METADATA_DISABLED=true RUN_ID=local make ops-eks-plan
```

Bundle output:

- `ops/proof/bundles/m4-<run_id>/eks_infra/receipt.json`
- `ops/proof/bundles/m4-<run_id>/eks_infra/manifest.json`
- `ops/proof/bundles/m4-<run_id>/eks_infra/eks_infra.tfplan`
- `ops/proof/bundles/m4-<run_id>/eks_infra/tofu_plan_sanitized.txt`

The command is plan-only and fails fast when state is empty while the live cluster exists.

## EKS control plane AZ restrictions

If EKS reports an `UnsupportedAvailabilityZoneException`, exclude that AZ when discovering subnets:

```bash
python scripts/aws_discover_subnets.py --exclude-az us-east-1e
```

Makefile equivalent:

```bash
make aws-discover-subnets EXCLUDE_AZ=us-east-1e
```

## Outputs

- `update_kubeconfig_command`: use to configure kubectl
- `jobintel_irsa_role_arn`: paste into `ops/k8s/overlays/aws-eks/patch-serviceaccount.yaml`
- `serviceaccount_annotation`: full annotation string
- `cluster_name`: EKS cluster name
- `region`: AWS region for the cluster
- `oidc_provider_arn`: OIDC provider ARN for IRSA
- `node_role_arn`: managed node group role ARN (ECR pull via this role)
- `subnet_ids`: subnets used by cluster and node group
- `cluster_security_group_id`: cluster security group ID

## Notes

- This module uses local state by default (no remote backend configured).
- `ops/aws/infra/eks/local.auto.tfvars.json` is local-only and gitignored.
- The IRSA role is scoped for runtime publish (PutObject + ListBucket with prefix).
- Operator verification may require a separate role with `s3:GetObject` and `s3:HeadObject`.

## State alignment (avoid duplicate EKS)

If `tofu plan` shows `aws_eks_cluster.this` and related resources as `to add` while `jobintel-eks` already exists, the usual root cause is state alignment, not missing variables.

`var.s3_bucket` is for runtime artifacts written by JobIntel workloads.  
Backend state bucket (if configured) is where OpenTofu stores `.tfstate`.  
These are different concerns and can have different bucket names.

### Checklist before any plan/apply

1. Confirm backend source: local vs remote backend in `ops/aws/infra/eks/*.tf`.
2. Confirm workspace: `tofu -chdir=ops/aws/infra/eks workspace show`.
3. Confirm state has resources: `tofu -chdir=ops/aws/infra/eks state list`.
4. Confirm live cluster exists: `aws eks describe-cluster --name jobintel-eks --region us-east-1`.
5. If cluster exists but state is empty, import first, then plan.

Use the helper:

```bash
AWS_PROFILE=jobintel-deployer AWS_REGION=us-east-1 CLUSTER_NAME=jobintel-eks scripts/ops/tofu_state_check.sh
```

### Deterministic import plan (preview only by default)

This repo currently uses local backend by default. If `state list` is empty but cluster exists, preview imports:

```bash
AWS_PROFILE=jobintel-deployer AWS_REGION=us-east-1 CLUSTER_NAME=jobintel-eks scripts/ops/tofu_state_check.sh --print-imports
```

This writes a deterministic import script to:

- `ops/proof/bundles/m4-<run_id>/eks_infra/import.sh`

Manually review the script, then execute it explicitly:

```bash
DO_IMPORT=1 bash ops/proof/bundles/m4-<run_id>/eks_infra/import.sh
```

After imports:

```bash
tofu -chdir=ops/aws/infra/eks state list
tofu -chdir=ops/aws/infra/eks plan -input=false -var-file=local.auto.tfvars.json
```
