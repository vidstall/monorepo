#!/bin/bash
set -e

echo "=== Building ==="
sui move build

echo "=== Running tests ==="
sui move test

echo "=== Publishing to testnet ==="
sui client publish --gas-budget 100000000

echo ""
echo "Save these from the output above:"
echo "  DVCONF_PACKAGE_ID=0x..."
echo "  NETWORK_REGISTRY_ID=0x..."
echo "  MINER_STORE_ID=0x..."
echo "  ADMIN_CAP_ID=0x..."
