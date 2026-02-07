# Runbook: On-Prem Install (k3s on ARM)

## Preflight checks

```bash
uname -m
lsblk
ip -br a
timedatectl status
```

Expected:
- ARM64 nodes reachable on LAN with static/reserved IPs.
- USB3 SSD visible for persistent state.
- NTP synchronized on each node.

If it fails:
- If clock is unsynced, fix NTP first (do not form cluster with skewed time).
- If SSD is not visible, replace cable/enclosure before continuing.

## 1) Server node bootstrap (pinned k3s version)

```bash
export K3S_VERSION=v1.31.5+k3s1
export NODE_NAME=jobintel-pi1
bash ops/onprem/mount-ssd.sh
bash ops/onprem/install-k3s-server.sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

Success criteria:
- `k3s server installed` appears in script output.
- `sudo systemctl is-active k3s` returns `active`.

If it fails:
- `sudo journalctl -u k3s -n 200 --no-pager`
- verify `/etc/rancher/k3s/config.yaml` has expected node IP.

## 2) Agent join (run on each agent)

```bash
export K3S_VERSION=v1.31.5+k3s1
export NODE_NAME=jobintel-pi2
export K3S_URL=https://<server-ip>:6443
export K3S_TOKEN=<token-from-server>
bash ops/onprem/install-k3s-agent.sh
```

Success criteria:
- `k3s agent installed` appears in script output.
- `sudo systemctl is-active k3s-agent` returns `active`.

If it fails:
- `sudo journalctl -u k3s-agent -n 200 --no-pager`
- verify token and server IP reachability (`nc -vz <server-ip> 6443`).

## 3) Verify cluster baseline

```bash
kubectl get nodes -o wide
kubectl get storageclass
kubectl -n kube-system get pods
```

Success criteria:
- All nodes `Ready`.
- `local-path` storage class present.
- No persistent CrashLoopBackOff in `kube-system`.

If it fails:
- `kubectl describe node <node-name>`
- `kubectl -n kube-system logs -l k8s-app=local-path-provisioner --tail=200`

## 4) Networking + access strategy contract

Preferred:
- VPN-first access only (Tailscale or WireGuard).
- Internal DNS name for dashboard (for example `jobintel.internal`) resolves over VPN.

Not allowed by default:
- Opening random WAN ports to dashboard/API without a documented exception.

Validation commands:

```bash
kubectl -n jobintel get ingress
kubectl -n kube-system get svc traefik
```
