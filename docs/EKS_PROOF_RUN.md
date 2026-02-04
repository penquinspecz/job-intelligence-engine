# EKS Proof Run (Golden Path)

This is the single, copy/paste path to produce proof receipts for Milestone 2.
It assumes you have valid AWS credentials and a target S3 bucket.

## 0) Prereqs

- Terraform >= 1.4
- `kubectl` configured
- AWS credentials with EKS + IAM + S3 access
- An S3 bucket for publish (S3-compatible object store)
- Docker (for image build/push)

## 1) Terraform apply (EKS + IRSA)

```bash
cd ops/aws/infra/eks
terraform init
terraform apply \
  -var 's3_bucket=<bucket>' \
  -var 'subnet_ids=["subnet-aaaa","subnet-bbbb"]'
```

Non-interactive apply (Makefile):

```bash
make tf-eks-apply-vars EKS_S3_BUCKET=<bucket> EKS_SUBNET_IDS='["subnet-aaaa","subnet-bbbb"]'
```

## 2) Configure kubectl (from Terraform output)

```bash
terraform -chdir=ops/aws/infra/eks output -raw update_kubeconfig_command
```

Copy/paste the command it prints, then select the context:

```bash
kubectl config use-context <your-eks-context>
```

## 3) Build + push image to ECR

```bash
IMAGE_URI="$(scripts/ecr_publish_image.sh | cut -d= -f2)"
export JOBINTEL_IMAGE="$IMAGE_URI"
```

## 4) Render + apply manifests (IRSA wired)

```bash
export JOBINTEL_IRSA_ROLE_ARN="$(terraform -chdir=ops/aws/infra/eks output -raw jobintel_irsa_role_arn)"
export JOBINTEL_S3_BUCKET=<bucket>

python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml
kubectl apply -f /tmp/jobintel.yaml
```

Optional sanity check:

```bash
kubectl -n jobintel auth can-i create pods --as=system:serviceaccount:jobintel:jobintel
```

## 5) Create secrets (no secrets in repo)

```bash
kubectl -n jobintel create secret generic jobintel-secrets \
  --from-literal=JOBINTEL_S3_BUCKET="$JOBINTEL_S3_BUCKET" \
  --from-literal=DISCORD_WEBHOOK_URL=... \
  --from-literal=OPENAI_API_KEY=...
```

## Permissions checklist

- Runtime (IRSA / pod role): can `PutObject` to `s3://<bucket>/<prefix>/...` and `ListBucket` for that prefix.
- Operator (your AWS user/role): can `GetObject`/`HeadObject` for `runs/` and `latest/` to verify.
- See `ops/aws/IAM.md` for the exact policy shapes.

## 6) Run one-off job from the CronJob template

```bash
kubectl delete job -n jobintel jobintel-manual-$(date +%Y%m%d) --ignore-not-found
kubectl create job -n jobintel --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
kubectl logs -n jobintel job/jobintel-manual-$(date +%Y%m%d)
```

You must see a log line like:

```
JOBINTEL_RUN_ID=<run_id>
```

## 7) Capture proof JSON (uses logs if run_id omitted)

```bash
python scripts/prove_cloud_run.py \
  --bucket "$JOBINTEL_S3_BUCKET" \
  --prefix jobintel \
  --namespace jobintel \
  --job-name jobintel-manual-$(date +%Y%m%d) \
  --kube-context <your-eks-context>
```

This writes the local proof receipt:

```
state/proofs/<run_id>.json
```

## 8) Verify latest keys

```bash
python scripts/verify_published_s3.py \
  --bucket "$JOBINTEL_S3_BUCKET" \
  --run-id <run_id> \
  --verify-latest
```

## Troubleshooting

- `AccessDenied` during publish: IRSA role missing `s3:PutObject` or `s3:ListBucket` prefix condition.
- `AccessDenied` during verify: operator role missing `s3:GetObject`/`s3:HeadObject`.
