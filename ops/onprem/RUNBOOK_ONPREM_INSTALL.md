# Runbook: On-Prem Install (k3s on ARM)

## 1) Server node bootstrap

```bash
export K3S_VERSION=v1.31.5+k3s1
export NODE_NAME=jobintel-pi1
bash ops/onprem/mount-ssd.sh
bash ops/onprem/install-k3s-server.sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

Expected cue:
- `k3s server installed`

## 2) Agent join (run on each agent)

```bash
export K3S_VERSION=v1.31.5+k3s1
export NODE_NAME=jobintel-pi2
export K3S_URL=https://<server-ip>:6443
export K3S_TOKEN=<token-from-server>
bash ops/onprem/install-k3s-agent.sh
```

Expected cue:
- `k3s agent installed`

## 3) Verify cluster

```bash
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get storageclass
```

Expected cue:
- all nodes `Ready`
- `local-path` storage class present

## 4) VPN-first access

Pick one:
- Tailscale (recommended for simple node-to-node mesh)
- WireGuard (if your environment already has key management)

Expose only VPN addresses for dashboard/ingress.
