#!/usr/bin/env bash
set -euo pipefail

# Prepare and persist USB SSD mount for k3s and app state.
DEVICE="${DEVICE:-/dev/sda}"
PARTITION="${PARTITION:-${DEVICE}1}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/jobintel-ssd}"
FSTAB_TAG="jobintel-ssd"

if [[ ! -b "${DEVICE}" ]]; then
  echo "device not found: ${DEVICE}" >&2
  exit 1
fi

sudo mkdir -p "${MOUNT_POINT}"

if ! lsblk -no FSTYPE "${PARTITION}" >/dev/null 2>&1 || [[ -z "$(lsblk -no FSTYPE "${PARTITION}" 2>/dev/null)" ]]; then
  echo "partition ${PARTITION} has no filesystem; creating ext4"
  sudo mkfs.ext4 -F "${PARTITION}"
fi

UUID="$(blkid -s UUID -o value "${PARTITION}")"
if [[ -z "${UUID}" ]]; then
  echo "failed to read UUID for ${PARTITION}" >&2
  exit 1
fi

if ! grep -q "${FSTAB_TAG}" /etc/fstab; then
  echo "UUID=${UUID} ${MOUNT_POINT} ext4 defaults,nofail,x-systemd.device-timeout=10 0 2 # ${FSTAB_TAG}" | sudo tee -a /etc/fstab >/dev/null
fi

sudo mount -a
mount | grep " ${MOUNT_POINT} " >/dev/null
sudo chown -R "$(id -u):$(id -g)" "${MOUNT_POINT}"

echo "SSD mounted at ${MOUNT_POINT}"
df -h "${MOUNT_POINT}"
