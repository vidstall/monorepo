from __future__ import annotations

from ..context import DOCKER_SERVICES, ROOT

NETWORKS = ("devnet", "testnet", "mainnet")
PROVIDERS = ("aws", "gcp", "azure", "alibaba", "digitalocean", "upcloud", "akamai", "tencent", "cloudflare", "oci")
SERVICE_BACKENDS = {service: "vm" for service in DOCKER_SERVICES}
REQUIRED_CONTRACT_KEYS = ("CONTRACT_PACKAGE_ID", "NETWORK_REGISTRY_ID")
# cp-daemon/validator-daemon have no externally-published port
# (default 0 via SERVICE_PORTS.get(service, 0)) — they're chain-facing
# daemons/CLIs, not client-facing servers. bot's port is its own HTTP
# control API (POST/GET/DELETE /bots), reverse-proxied directly via Caddy --
# not a media-plane port like relay/signaling.
# prometheus has no entry here deliberately -- it's never publicly exposed
# (Grafana, the only thing that used to reach it over xaisen-net, is no
# longer managed here -- it's self-hosted by the operator), so base_port
# stays 0 for it, same as cp-daemon/validator-daemon.
# node_exporter is public (not loopback-gated like prometheus/tempo/grafana/
# pushgateway below) -- unlike those, it colocates on the REMOTE worker
# droplet, not on the same host as Prometheus, so Prometheus can only reach
# it over the public sslip.io endpoint (same reasoning as relay/signaling's
# public ports), never over loopback.
SERVICE_PORTS = {"relay": 4000, "bot": 8095, "node_exporter": 9100}
VM_INSTANCE_SIZES = {
    "aws": "t3.micro",
    "gcp": "e2-micro",
    # This subscription (Azure for Students) has no B-series/A-series x86_64
    # capacity in any tested region (eastus, eastus2, westus2) -- confirmed
    # via `az vm list-skus` restrictions, not just live SkuNotAvailable
    # errors. Standard_D2als_v7 (AMD, low-memory v7-gen) is the actual floor:
    # the cheapest x86_64 SKU this subscription can provision at all. ARM
    # (`*p*` prefixed) SKUs ARE available but unusable -- worker images are
    # built linux/amd64 only (see TARGET_PLATFORM in cli/registry.py).
    "azure": "Standard_D2als_v7",
    "alibaba": "ecs.t6-c1m1.large",
    "digitalocean": "s-1vcpu-1gb",
    "tencent": "S5.SMALL1",
    "upcloud": "1xCPU-1GB",
    "akamai": "g6-nanode-1",
    # Fixed (non-flex) shape, Always-Free-eligible -- avoids OCI's
    # shape_config OCPU/memory sizing complexity for the default case.
    "oci": "VM.Standard.E2.1.Micro",
}
# Per-(provider, service) override, for cases where a role needs more
# headroom than the provider's cheapest default (e.g. relay/mediasoup under
# real call load). Currently empty -- Azure's cheapest available SKU already
# exceeds what relay needs.
VM_INSTANCE_SIZE_OVERRIDES: dict[tuple[str, str], str] = {}
SSH_KEY_ROOT = ROOT / "runtime" / "ssh_key"
# Backed-up Caddy /data (TLS cert storage) per (provider, address) -- see
# cert_cache.py. Keyed by the actual resolved IP (not scenario host id),
# since the whole point is reusing a cached cert when a NEW host id lands
# on an IP that already has one, not per-host-id identity.
CERT_CACHE_ROOT = ROOT / "runtime" / "cert_cache"
