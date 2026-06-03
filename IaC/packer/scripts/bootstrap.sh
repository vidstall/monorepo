#!/usr/bin/env bash
set -euo pipefail

ROLE="${ROLE:-unknown}"

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y cloud-init qemu-guest-agent
fi

mkdir -p /etc/depin-testbed
cat > /etc/depin-testbed/role <<EOF
${ROLE}
EOF
