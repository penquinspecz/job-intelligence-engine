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

## Boring non-interactive flow

Run from repo root:

```bash
export AWS_PROFILE=jobintel-deployer AWS_REGION=us-east-1 CLUSTER_NAME=jobintel-eks JOBINTEL_ARTIFACTS_BUCKET=<bucket>
python scripts/tofu_eks_vars_from_aws.py
scripts/ops/tofu_eks_guardrails.sh && tofu -chdir=ops/aws/infra/eks plan -input=false -var-file=local.auto.tfvars.json
```

Makefile equivalent:

```bash
make tofu-eks-vars
make tofu-eks-plan
```

`scripts/tofu_eks_vars_from_aws.py` writes `ops/aws/infra/eks/local.auto.tfvars.json` using authoritative AWS cluster data (`aws eks describe-cluster`).  
`scripts/ops/tofu_eks_guardrails.sh` hard-fails when identity/state checks are unsafe (for example, empty state or mismatched cluster name).

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
