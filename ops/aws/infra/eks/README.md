# EKS bootstrap (minimal)

This directory provides a minimal EKS cluster + IRSA role for JobIntel.

## Prerequisites

- Terraform >= 1.4
- AWS credentials with EKS + IAM + EC2 permissions
- Existing VPC subnets suitable for EKS (recommended: private subnets)

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

## Apply

```bash
terraform init
terraform apply \
  -var 's3_bucket=<bucket>' \
  -var 'subnet_ids=["subnet-aaaa","subnet-bbbb"]'
```

## How to find subnet_ids

Use the helper script (AWS CLI required):

```bash
python scripts/aws_discover_subnets.py
```

It prints a deterministic JSON summary and a suggested terraform command snippet.

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
- The IRSA role is scoped for runtime publish (PutObject + ListBucket with prefix).
- Operator verification may require a separate role with `s3:GetObject` and `s3:HeadObject`.
