#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/ops/eks_nodegroup_upgrade_triage.sh [options]

Read-only EKS nodegroup upgrade triage helper.
- Detects nodegroup health/errors
- Detects EKS nodegroup subnet vs ASG subnet mismatch
- Shows kubelet version distribution grouped by nodegroup
- Warns on kube-proxy version skew
- Prints recommended next actions and safe drain commands (not executed)

Options:
  --region <region>            AWS region (default: us-east-1)
  --cluster <name>             EKS cluster name (default: jobintel-eks)
  --nodegroup <name>           Nodegroup to triage (default: AL2023-131)
  --asg <name>                 Backing ASG name
                               (default: eks-AL2023-131-8cce18f7-8dc9-a072-2375-9e9b83219eef)
  --excluded-subnet <subnet>   Known constrained subnet to exclude in templates (default: subnet-f97176f7)
  --new-nodegroup-name <name>  Suggested replacement nodegroup name in template output (default: AL2023-132)
  -h, --help                   Show this help
USAGE
}

log() {
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required tool not found: $1" >&2
    exit 2
  }
}

REGION="us-east-1"
CLUSTER_NAME="jobintel-eks"
NODEGROUP_NAME="AL2023-131"
ASG_NAME="eks-AL2023-131-8cce18f7-8dc9-a072-2375-9e9b83219eef"
EXCLUDED_SUBNET="subnet-f97176f7"
NEW_NODEGROUP_NAME="AL2023-132"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      REGION="$2"
      shift 2
      ;;
    --cluster)
      CLUSTER_NAME="$2"
      shift 2
      ;;
    --nodegroup)
      NODEGROUP_NAME="$2"
      shift 2
      ;;
    --asg)
      ASG_NAME="$2"
      shift 2
      ;;
    --excluded-subnet)
      EXCLUDED_SUBNET="$2"
      shift 2
      ;;
    --new-nodegroup-name)
      NEW_NODEGROUP_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

require_cmd aws
require_cmd kubectl
require_cmd jq

log "Configuration"
echo "  region=$REGION"
echo "  cluster=$CLUSTER_NAME"
echo "  nodegroup=$NODEGROUP_NAME"
echo "  asg=$ASG_NAME"
echo "  excluded_subnet=$EXCLUDED_SUBNET"
echo "  suggested_new_nodegroup=$NEW_NODEGROUP_NAME"

log "Cluster health check"
if ! aws eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" --output json >/dev/null; then
  echo "ERROR: failed to describe cluster '$CLUSTER_NAME' in region '$REGION'" >&2
  exit 2
fi

CLUSTER_JSON="$(aws eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" --output json)"
CLUSTER_VERSION="$(echo "$CLUSTER_JSON" | jq -r '.cluster.version')"

NG_JSON="$(aws eks describe-nodegroup --region "$REGION" --cluster-name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP_NAME" --output json)"
NODE_ROLE_ARN="$(echo "$NG_JSON" | jq -r '.nodegroup.nodeRole')"
INSTANCE_TYPES_CSV="$(echo "$NG_JSON" | jq -r '.nodegroup.instanceTypes | join(",")')"
AMI_TYPE="$(echo "$NG_JSON" | jq -r '.nodegroup.amiType')"
CAPACITY_TYPE="$(echo "$NG_JSON" | jq -r '.nodegroup.capacityType')"
DISK_SIZE="$(echo "$NG_JSON" | jq -r '.nodegroup.diskSize')"
NG_STATUS="$(echo "$NG_JSON" | jq -r '.nodegroup.status')"

UPDATES_JSON="$(aws eks list-updates --region "$REGION" --name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP_NAME" --output json)"
LATEST_UPDATE_ID="$(echo "$UPDATES_JSON" | jq -r '.updateIds | last // empty')"

ASG_JSON="$(aws autoscaling describe-auto-scaling-groups --region "$REGION" --auto-scaling-group-names "$ASG_NAME" --output json)"
ASG_COUNT="$(echo "$ASG_JSON" | jq -r '.AutoScalingGroups | length')"
if [[ "$ASG_COUNT" != "1" ]]; then
  echo "ERROR: ASG not found or ambiguous: $ASG_NAME" >&2
  exit 2
fi

NG_SUBNETS_SORTED="$(echo "$NG_JSON" | jq -r '.nodegroup.subnets[]' | sort)"
ASG_SUBNETS_SORTED="$(echo "$ASG_JSON" | jq -r '.AutoScalingGroups[0].VPCZoneIdentifier' | tr ',' '\n' | sed '/^$/d' | sort)"
SUBNET_MISMATCH=0
if [[ "$NG_SUBNETS_SORTED" != "$ASG_SUBNETS_SORTED" ]]; then
  SUBNET_MISMATCH=1
fi

echo
log "Nodegroup summary"
echo "$NG_JSON" | jq '.nodegroup | {
  nodegroupName,
  status,
  version,
  releaseVersion,
  amiType,
  capacityType,
  instanceTypes,
  scalingConfig,
  healthIssues: .health.issues,
  subnets,
  asg: .resources.autoScalingGroups[0].name
}'

echo
log "Latest update summary"
echo "$UPDATES_JSON" | jq '{updateIds}'
if [[ -n "$LATEST_UPDATE_ID" ]]; then
  aws eks describe-update --region "$REGION" --name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP_NAME" --update-id "$LATEST_UPDATE_ID" --output json \
    | jq '.update | {id,status,type,createdAt,params,errors}'
else
  echo "No nodegroup updates found."
fi

echo
log "ASG summary"
echo "$ASG_JSON" | jq '.AutoScalingGroups[0] | {
  AutoScalingGroupName,
  MinSize,
  DesiredCapacity,
  MaxSize,
  VPCZoneIdentifier,
  AvailabilityZones,
  InServiceCount: ([.Instances[] | select(.LifecycleState=="InService")] | length),
  Instances: [.Instances[] | {InstanceId,AvailabilityZone,LifecycleState,HealthStatus}]
}'

echo
log "Subnet consistency check (EKS nodegroup vs ASG)"
if [[ "$SUBNET_MISMATCH" -eq 1 ]]; then
  echo "WARNING: subnet mismatch detected (this can cause DEGRADED nodegroup health)."
  echo "EKS nodegroup subnets:"
  echo "$NG_SUBNETS_SORTED" | sed 's/^/  - /'
  echo "ASG subnets:"
  echo "$ASG_SUBNETS_SORTED" | sed 's/^/  - /'
else
  echo "OK: ASG subnets match EKS nodegroup subnets."
fi

echo
log "Recent ASG scaling activities"
aws autoscaling describe-scaling-activities --region "$REGION" --auto-scaling-group-name "$ASG_NAME" --max-items 15 --output json \
  | jq '.Activities[] | {StartTime,StatusCode,Description,Details}'

echo
log "Kubelet versions grouped by nodegroup"
NODE_ALL_JSON="$(kubectl get nodes -o json)"
echo "$NODE_ALL_JSON" | jq -r '
  .items
  | sort_by(.metadata.labels["eks.amazonaws.com/nodegroup"] // "unlabeled", .status.nodeInfo.kubeletVersion)
  | group_by(.metadata.labels["eks.amazonaws.com/nodegroup"] // "unlabeled")[]
  | .[0].metadata.labels["eks.amazonaws.com/nodegroup"] // "unlabeled" as $ng
  | (sort_by(.status.nodeInfo.kubeletVersion)
     | group_by(.status.nodeInfo.kubeletVersion)[]
     | "\($ng)\t\(.[0].status.nodeInfo.kubeletVersion)\tcount=\(length)")
'

echo
log "Target nodegroup nodes"
kubectl get nodes -l "eks.amazonaws.com/nodegroup=$NODEGROUP_NAME" -o wide

OLD_NODES="$(kubectl get nodes -l "eks.amazonaws.com/nodegroup=$NODEGROUP_NAME" -o json | jq -r '.items[] | select(.status.nodeInfo.kubeletVersion | startswith("v1.31.")) | .metadata.name')"

echo
log "kube-proxy skew check"
KP_IMAGE="$(kubectl -n kube-system get daemonset kube-proxy -o json | jq -r '.spec.template.spec.containers[] | select(.name=="kube-proxy") | .image')"
KP_TAG="${KP_IMAGE##*:}"
CLUSTER_MINOR="$(printf '%s' "$CLUSTER_VERSION" | awk -F. '{print $2}')"
KP_MINOR="$(printf '%s' "$KP_TAG" | sed -n 's/^v1\.\([0-9][0-9]*\).*/\1/p')"
echo "cluster_version=$CLUSTER_VERSION"
echo "kube_proxy_image=$KP_IMAGE"
if [[ -n "$KP_MINOR" && -n "$CLUSTER_MINOR" && "$KP_MINOR" != "$CLUSTER_MINOR" ]]; then
  echo "WARNING: kube-proxy tag ($KP_TAG) appears skewed from cluster minor ($CLUSTER_VERSION)."
  echo "Troubleshoot: kubectl -n kube-system rollout status daemonset/kube-proxy"
  echo "Troubleshoot: kubectl -n kube-system get pods -l k8s-app=kube-proxy -o wide"
fi

echo
log "Recommended next actions"
if [[ "$NG_STATUS" != "ACTIVE" ]]; then
  echo "1) Inspect nodegroup updates before retrying mutation:"
  echo "   aws eks list-updates --region $REGION --name $CLUSTER_NAME --nodegroup-name $NODEGROUP_NAME --output json"
  echo "   aws eks describe-update --region $REGION --name $CLUSTER_NAME --nodegroup-name $NODEGROUP_NAME --update-id <LATEST_UPDATE_ID> --output json"
fi
if [[ "$SUBNET_MISMATCH" -eq 1 ]]; then
  echo "2) Do not keep ASG subnet mutations long-term on managed nodegroups. Prefer creating a replacement nodegroup with healthy subnets."
fi
if [[ -n "$OLD_NODES" ]]; then
  echo "3) Safe drain plan for v1.31 nodes (review, then run manually one-by-one):"
  while IFS= read -r n; do
    [[ -n "$n" ]] || continue
    echo "   kubectl cordon $n"
    echo "   kubectl drain $n --ignore-daemonsets --delete-emptydir-data --force --grace-period=60 --timeout=20m"
  done <<< "$OLD_NODES"
else
  echo "3) No v1.31 nodes detected in target nodegroup."
fi

echo
log "Optional template: create replacement nodegroup excluding constrained subnet (NOT EXECUTED)"
GOOD_SUBNETS_CSV="$(echo "$NG_SUBNETS_SORTED" | grep -v "^${EXCLUDED_SUBNET}$" | tr '\n' ',' | sed 's/,$//')"
cat <<TEMPLATE
aws eks create-nodegroup \
  --region "$REGION" \
  --cluster-name "$CLUSTER_NAME" \
  --nodegroup-name "$NEW_NODEGROUP_NAME" \
  --subnets $GOOD_SUBNETS_CSV \
  --node-role "$NODE_ROLE_ARN" \
  --instance-types $INSTANCE_TYPES_CSV \
  --ami-type "$AMI_TYPE" \
  --capacity-type "$CAPACITY_TYPE" \
  --disk-size $DISK_SIZE \
  --scaling-config minSize=1,maxSize=3,desiredSize=2
TEMPLATE
