#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/ops/finish_nodegroup_upgrade_no1f.sh [options]

Purpose:
  Validate EKS nodegroup upgrade preconditions when one AZ/subnet is excluded for capacity,
  show upgrade/drain evidence, and optionally execute safe node drains and AZRebalance finalize.

Options:
  --region <region>             AWS region (default: us-east-1)
  --cluster <name>              EKS cluster name (default: jobintel-eks)
  --nodegroup <name>            EKS managed nodegroup (default: AL2023-131)
  --asg <name>                  Backing ASG name
                                (default: eks-AL2023-131-8cce18f7-8dc9-a072-2375-9e9b83219eef)
  --excluded-subnet <subnet>    Subnet that must be excluded from ASG zone identifiers
                                (default: subnet-f97176f7)
  --execute-drain               Actually cordon/drain v1.31 nodes one by one
  --execute-finalize            Actually resume AZRebalance once all nodes are on v1.32.*
  -h, --help                    Show this help

Safety:
  - Dry-run by default for drain/finalize actions.
  - Exits non-zero on validation failures or command failures.
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
EXECUTE_DRAIN=0
EXECUTE_FINALIZE=0

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
    --execute-drain)
      EXECUTE_DRAIN=1
      shift
      ;;
    --execute-finalize)
      EXECUTE_FINALIZE=1
      shift
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
echo "  execute_drain=$EXECUTE_DRAIN"
echo "  execute_finalize=$EXECUTE_FINALIZE"

EKS_DESCRIBE_NODEGROUP_CMD=(
  aws eks describe-nodegroup
  --region "$REGION"
  --cluster-name "$CLUSTER_NAME"
  --nodegroup-name "$NODEGROUP_NAME"
  --output json
)

log "EKS self-check command (describe-nodegroup):"
printf '  %q ' "${EKS_DESCRIBE_NODEGROUP_CMD[@]}"
printf '\n'

log "Validating cluster exists and is readable"
if ! aws eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" --output json >/dev/null; then
  echo "ERROR: failed to describe cluster '$CLUSTER_NAME' in region '$REGION'" >&2
  echo "Check cluster name/region and AWS identity permissions, then retry." >&2
  exit 2
fi

log "Validating ASG excludes subnet: $EXCLUDED_SUBNET"
ASG_JSON="$(aws autoscaling describe-auto-scaling-groups \
  --region "$REGION" \
  --auto-scaling-group-names "$ASG_NAME" \
  --output json)"

ASG_FOUND="$(echo "$ASG_JSON" | jq -r '.AutoScalingGroups | length')"
if [[ "$ASG_FOUND" != "1" ]]; then
  echo "ERROR: ASG not found or ambiguous: $ASG_NAME" >&2
  exit 2
fi

VPC_ZONE_IDS="$(echo "$ASG_JSON" | jq -r '.AutoScalingGroups[0].VPCZoneIdentifier')"
if echo "$VPC_ZONE_IDS" | tr ',' '\n' | grep -qx "$EXCLUDED_SUBNET"; then
  echo "ERROR: excluded subnet is still present in ASG VPCZoneIdentifier: $EXCLUDED_SUBNET" >&2
  echo "Fix with:" >&2
  echo "  aws autoscaling update-auto-scaling-group --region $REGION --auto-scaling-group-name $ASG_NAME --vpc-zone-identifier '<comma-separated-subnet-list-without-$EXCLUDED_SUBNET>'" >&2
  exit 3
fi
log "ASG subnet validation passed"

log "Nodegroup status"
NG_JSON="$("${EKS_DESCRIBE_NODEGROUP_CMD[@]}")"

echo "$NG_JSON" | jq '.nodegroup | {
  nodegroupName,
  status,
  version,
  releaseVersion,
  instanceTypes,
  scalingConfig,
  subnets,
  nodeRole,
  asg: .resources.autoScalingGroups[0].name
}'

log "Latest nodegroup update status"
UPDATES_JSON="$(aws eks list-updates --region "$REGION" --name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP_NAME" --output json)"
LATEST_UPDATE_ID="$(echo "$UPDATES_JSON" | jq -r '.updateIds | last // empty')"
if [[ -n "$LATEST_UPDATE_ID" ]]; then
  aws eks describe-update \
    --region "$REGION" \
    --name "$CLUSTER_NAME" \
    --nodegroup-name "$NODEGROUP_NAME" \
    --update-id "$LATEST_UPDATE_ID" \
    --output json | jq '.update | {id,status,type,createdAt,errors,params}'
else
  echo "No nodegroup updates found."
fi

log "Recent ASG scaling activities"
aws autoscaling describe-scaling-activities \
  --region "$REGION" \
  --auto-scaling-group-name "$ASG_NAME" \
  --max-items 15 \
  --output json | jq '.Activities[] | {StartTime,StatusCode,Description,Details}'

NG_STATUS="$(echo "$NG_JSON" | jq -r '.nodegroup.status')"
if [[ "$NG_STATUS" != "ACTIVE" ]]; then
  log "Nodegroup is not ACTIVE (status=$NG_STATUS). Next commands to inspect/rerun upgrade:"
  echo "aws eks list-updates --region $REGION --name $CLUSTER_NAME --nodegroup-name $NODEGROUP_NAME --output json"
  echo "aws eks describe-update --region $REGION --name $CLUSTER_NAME --nodegroup-name $NODEGROUP_NAME --update-id <LATEST_UPDATE_ID> --output json"
  echo "# Re-run the same upgrade explicitly (replace values with your last known target):"
  echo "aws eks update-nodegroup-version --region $REGION --cluster-name $CLUSTER_NAME --nodegroup-name $NODEGROUP_NAME --kubernetes-version <target> --release-version <release>"
fi

log "Listing node versions for nodegroup=$NODEGROUP_NAME"
NODES_JSON="$(kubectl get nodes -l "eks.amazonaws.com/nodegroup=$NODEGROUP_NAME" -o json)"

echo "$NODES_JSON" | jq -r '
  .items[] |
  {
    name: .metadata.name,
    kubelet: .status.nodeInfo.kubeletVersion,
    ready: ((.status.conditions[] | select(.type=="Ready") | .status) // "Unknown")
  } |
  "\(.name)\t\(.kubelet)\tReady=\(.ready)"
'

mapfile -t OLD_NODES < <(echo "$NODES_JSON" | jq -r '.items[] | select(.status.nodeInfo.kubeletVersion | startswith("v1.31.")) | .metadata.name')

if [[ ${#OLD_NODES[@]} -eq 0 ]]; then
  log "No v1.31 nodes detected in this nodegroup"
else
  log "Nodes still on v1.31.* (${#OLD_NODES[@]}):"
  printf '  %s\n' "${OLD_NODES[@]}"
fi

log "Safe drain plan"
if [[ ${#OLD_NODES[@]} -eq 0 ]]; then
  echo "No drain required."
else
  for node in "${OLD_NODES[@]}"; do
    echo "kubectl cordon $node"
    echo "kubectl drain $node --ignore-daemonsets --delete-emptydir-data --force --grace-period=60 --timeout=20m"
  done
  if [[ "$EXECUTE_DRAIN" -eq 0 ]]; then
    echo "Dry-run mode: no drains executed. Re-run with --execute-drain to apply."
  fi
fi

count_old_nodes() {
  kubectl get nodes -l "eks.amazonaws.com/nodegroup=$NODEGROUP_NAME" -o json \
    | jq '[.items[] | select(.status.nodeInfo.kubeletVersion | startswith("v1.31."))] | length'
}

count_ready_nodes() {
  kubectl get nodes -l "eks.amazonaws.com/nodegroup=$NODEGROUP_NAME" -o json \
    | jq '[.items[] | select(any(.status.conditions[]; .type=="Ready" and .status=="True"))] | length'
}

if [[ "$EXECUTE_DRAIN" -eq 1 && ${#OLD_NODES[@]} -gt 0 ]]; then
  log "Executing one-by-one drains"
  for node in "${OLD_NODES[@]}"; do
    if ! kubectl get node "$node" >/dev/null 2>&1; then
      log "Node already gone: $node"
      continue
    fi

    BEFORE_OLD="$(count_old_nodes)"
    BEFORE_READY="$(count_ready_nodes)"
    log "Draining node=$node (old_before=$BEFORE_OLD ready_before=$BEFORE_READY)"

    kubectl cordon "$node"
    kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --force --grace-period=60 --timeout=20m

    log "Waiting for replacement readiness before next drain"
    ATTEMPTS=0
    MAX_ATTEMPTS=80
    while true; do
      ATTEMPTS=$((ATTEMPTS + 1))
      CURRENT_OLD="$(count_old_nodes)"
      CURRENT_READY="$(count_ready_nodes)"
      if [[ "$CURRENT_OLD" -lt "$BEFORE_OLD" && "$CURRENT_READY" -ge "$BEFORE_READY" ]]; then
        log "Replacement condition met (old_now=$CURRENT_OLD ready_now=$CURRENT_READY)"
        break
      fi
      if [[ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]]; then
        echo "ERROR: timeout waiting for replacement node readiness after draining $node" >&2
        echo "State: old_now=$CURRENT_OLD ready_now=$CURRENT_READY expected old<$BEFORE_OLD ready>=$BEFORE_READY" >&2
        exit 4
      fi
      sleep 15
    done
  done
fi

FINAL_OLD="$(count_old_nodes)"
if [[ "$FINAL_OLD" -eq 0 ]]; then
  log "All nodegroup nodes are on v1.32.*"
  RESUME_CMD="aws autoscaling resume-processes --region $REGION --auto-scaling-group-name $ASG_NAME --scaling-processes AZRebalance"
  echo "$RESUME_CMD"
  if [[ "$EXECUTE_FINALIZE" -eq 1 ]]; then
    log "Resuming AZRebalance"
    eval "$RESUME_CMD"
    log "AZRebalance resumed"
  else
    echo "Dry-run finalize: add --execute-finalize to run resume command."
  fi
else
  log "Remaining v1.31 nodes: $FINAL_OLD"
  echo "Not finalizing AZRebalance yet."
fi
