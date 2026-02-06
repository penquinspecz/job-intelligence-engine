# EKS Nodegroup Upgrade Recovery Runbook

This runbook covers managed nodegroup upgrade incidents where upgrades stall or fail due to AZ capacity, ASG drift, or mixed-version node fleets.

Scope:
- Kubernetes-first recovery flow
- EKS-managed nodegroups and AWS Auto Scaling Groups
- Read-only triage first, then controlled remediation

## Symptoms

Typical signals:
- `aws eks describe-nodegroup` shows `status: DEGRADED` or prolonged `UPDATING`
- `aws eks describe-update` shows `NodeCreationFailure`
- ASG activities show `InsufficientInstanceCapacity` in one AZ
- Nodes remain mixed at old/new kubelet versions
- Cluster workload disruption risk during unmanaged drains

## Decision Tree

1. Run triage script first:
```bash
scripts/ops/eks_nodegroup_upgrade_triage.sh \
  --region us-east-1 \
  --cluster jobintel-eks \
  --nodegroup AL2023-131 \
  --asg eks-AL2023-131-8cce18f7-8dc9-a072-2375-9e9b83219eef
```
2. If nodegroup and ASG subnets match and update is merely slow:
- Wait for update completion and keep checking health.
3. If nodegroup and ASG subnets mismatch:
- Treat as config drift; do not keep ASG subnet mutations long-term.
- Create replacement nodegroup with correct subnets instead of forcing ASG-only changes.
4. If capacity in one AZ is repeatedly unavailable:
- Create replacement nodegroup excluding constrained subnet/AZ, then drain old nodes.
5. If replacement nodes are NotReady for >5 minutes:
- Stop drains, investigate CNI/kube-proxy/kubelet health before continuing.

## Safe Recovery Procedure

### 1) Capture state (read-only)

```bash
export AWS_REGION=us-east-1
export CLUSTER_NAME=jobintel-eks
export NODEGROUP_OLD=AL2023-131

aws eks describe-nodegroup \
  --region "$AWS_REGION" \
  --cluster-name "$CLUSTER_NAME" \
  --nodegroup-name "$NODEGROUP_OLD" \
  --output json | jq '.nodegroup | {nodegroupName,status,version,releaseVersion,health:.health.issues,subnets,asg:.resources.autoScalingGroups}'

aws eks list-updates \
  --region "$AWS_REGION" \
  --name "$CLUSTER_NAME" \
  --nodegroup-name "$NODEGROUP_OLD" \
  --output json
```

Expected cue:
- You can see current health issues, subnet set, and update ids/errors.

### 2) If required, create a replacement nodegroup (no ASG drift)

Use the template emitted by `scripts/ops/eks_nodegroup_upgrade_triage.sh`.

Expected cue:
- New nodegroup transitions to `ACTIVE`.
- New nodes join with target kubelet version.

### 3) Drain old-version nodes safely

List old-version nodes:
```bash
kubectl get nodes -o json | jq -r '
  .items[]
  | select(.status.nodeInfo.kubeletVersion | startswith("v1.31."))
  | .metadata.name
'
```

For each old node (one-by-one):
```bash
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force --grace-period=60 --timeout=20m
```

After each drain:
```bash
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running
```

Expected cue:
- Replacement nodes are `Ready`.
- No critical workload remains Pending/CrashLooping.

### 4) Delete failed/legacy nodegroup after workload migration

```bash
aws eks delete-nodegroup \
  --region "$AWS_REGION" \
  --cluster-name "$CLUSTER_NAME" \
  --nodegroup-name "$NODEGROUP_OLD"
```

Expected cue:
- Only the replacement nodegroup remains and all nodes are on target version.

## Verification Checks

### Node, pod, and PDB health

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl get pdb -A
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50
```

Expected cue:
- All nodes `Ready`
- No critical pods Pending/Failed due to disruption
- PDB constraints respected during drains

### kube-system sanity

```bash
kubectl -n kube-system get ds,deploy,pods -o wide
kubectl -n kube-system rollout status ds/aws-node
kubectl -n kube-system rollout status ds/kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide
```

Expected cue:
- `aws-node`, `kube-proxy`, and DNS pods healthy on all schedulable nodes.

## kube-proxy Version Skew Troubleshooting

Check cluster and kube-proxy versions:
```bash
aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" --output json | jq -r '.cluster.version'
kubectl -n kube-system get ds kube-proxy -o json | jq -r '.spec.template.spec.containers[] | select(.name=="kube-proxy") | .image'
```

If kube-proxy appears skewed:
```bash
kubectl -n kube-system rollout restart ds/kube-proxy
kubectl -n kube-system rollout status ds/kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy -o wide
```

If nodes are NotReady after rollout:
```bash
kubectl describe node <node-name>
kubectl -n kube-system logs daemonset/aws-node --tail=200
kubectl -n kube-system logs daemonset/kube-proxy --tail=200
```

## Important Guardrail

Do not use long-term ASG subnet mutations as the primary fix for managed nodegroups.
- Short-term ASG edits can unblock immediate incidents.
- Long-term recovery should restore EKS-managed consistency by creating/replacing nodegroups with intended subnets.
- Subnet mismatch between EKS nodegroup config and ASG is a known path to `DEGRADED` health and update failures.
