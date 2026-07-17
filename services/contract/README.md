# dvconf-contracts — Command Reference

## Run Tests (no network needed)

```powershell
# Run all tests (switch to testnet env first to avoid Move.toml env errors)
sui client switch --env testnet
sui move test

# Run single test module
sui move test --filter registration_tests
sui move test --filter network_registry_tests
sui move test --filter cp_queries_tests

# Silence lint warnings
sui move test --silence-warnings
```

---

## Deploy to Testnet

### One-time setup

```powershell
# Make sure testnet is active
sui client switch --env testnet
sui client active-address   # note your address

# Get gas from faucet
sui client faucet
# If the CLI faucet doesn't work, use the API:
# curl -X POST https://faucet.testnet.sui.io/v1/gas \
#   -H "Content-Type: application/json" \
#   -d '{"FixedAmountRequest":{"recipient":"<YOUR_ADDRESS>"}}'

# Verify gas arrived
sui client gas
```

### Publish

```powershell
cd C:\Thesis\dvconf\dvconf-contracts
sui client publish --gas-budget 100000000
```

### Save IDs from publish output

```powershell
$PACKAGE   = "0x..."  # Published Objects → PackageID
$REGISTRY  = "0x..."  # ObjectType: ...::NetworkRegistry  (Owner: Shared)
$STORE     = "0x..."  # ObjectType: ...::MinerStore        (Owner: Shared)
$ADMIN_CAP = "0x..."  # ObjectType: ...::AdminCap          (Owner: your address)
$TREASURY  = "0x..."  # ObjectType: ...::TreasuryCap       (Owner: your address)
$ME        = "$(sui client active-address)"
```

---

## Local Network (alternative to testnet)

### Terminal 1 — start node (keep running)

```powershell
$env:RUST_LOG="off,sui_node=info"; sui start --with-faucet --force-regenesis
```

Wait until you see `Fullnode rpc URL` in the output.

### Terminal 2 — setup

```powershell
sui client new-env --alias local --rpc http://127.0.0.1:9000
sui client switch --env local
sui client faucet
sui client gas

# Deploy (local uses test-publish)
sui client test-publish --gas-budget 1000000000 --build-env local
```

If you get `Ephemeral publication file has chain-id` error after a network restart:

```powershell
del Pub.local.toml
sui client test-publish --gas-budget 1000000000 --build-env local
```

---

## CLI Call Examples

### UC1: Mint & Register

```powershell
# Mint 1 DVCONF (= 1_000_000_000 base units) → Relay role
sui client call --package $PACKAGE --module token --function mint `
  --args $TREASURY 1000000000 $ME --gas-budget 10000000

# Find the TOKEN coin object ID
sui client objects
# Look for Coin<...::token::TOKEN>, copy its objectId
$COIN = "0x..."

# Register as relay (byte arrays: IP, STUN URL, TURN URL, region, credential hash)
sui client call --package $PACKAGE --module registration --function register `
  --args $REGISTRY $STORE $COIN `
  '[192,168,1,1]' 8080 `
  '[115,116,117,110,58,47,47,115,46,116,101,115,116]' `
  '[116,117,114,110,58,47,47,116,46,116,101,115,116]' `
  '[97,115,105,97,45,115,111,117,116,104,101,97,115,116,49]' `
  1000 100 8 0 '[]' `
  --gas-budget 10000000
# Note: last arg '[]' = empty turn_credential_hash for testing

# Find StakePosition ID
sui client objects
# Look for ...::staking::StakePosition, copy its objectId
$STAKE_POS = "0x..."

# Inspect it
sui client object $STAKE_POS
```

### UC2: Top Up (Role Upgrade)

```powershell
# Mint another 1 DVCONF → total 2 DVCONF → upgrades to CP
sui client call --package $PACKAGE --module token --function mint `
  --args $TREASURY 1000000000 $ME --gas-budget 10000000

sui client objects
$COIN2 = "0x..."

sui client call --package $PACKAGE --module registration --function top_up_stake `
  --args $REGISTRY $STORE $STAKE_POS $COIN2 --gas-budget 10000000

# Verify role changed to 3 (CP)
sui client object $STAKE_POS
```

### UC3: Unregister

```powershell
sui client call --package $PACKAGE --module registration --function unregister `
  --args $STORE $SIGNALING_REG $RELAY_REG $VALIDATOR_REG $CP_REG $STAKE_POS --gas-budget 10000000
```

### UC4: Update Info

```powershell
# Update endpoint (all 5 fields required: ip, port, stun_url, turn_url, turn_credential_hash)
sui client call --package $PACKAGE --module registration --function update_endpoint `
  --args $STORE $STAKE_POS '[10,0,0,1]' 9090 '[115,116,117,110]' '[116,117,114,110]' '[]' `
  --gas-budget 10000000

# Update load (current sessions count)
sui client call --package $PACKAGE --module registration --function update_load `
  --args $STORE $STAKE_POS 42 --gas-budget 10000000

# Go offline
sui client call --package $PACKAGE --module registration --function set_active `
  --args $STORE $STAKE_POS false --gas-budget 10000000
```

### UC5: CP Queries (requires ControlPlaneCap)

```powershell
# Find ControlPlaneCap from objects list
sui client objects
$CP_CAP = "0x..."

# Get role counts
sui client call --package $PACKAGE --module cp_queries --function get_counts `
  --args $CP_CAP $STORE --gas-budget 10000000

# Get relay set
sui client call --package $PACKAGE --module cp_queries --function get_relay_set `
  --args $CP_CAP $STORE --gas-budget 10000000

# Get validator set
sui client call --package $PACKAGE --module cp_queries --function get_validator_set `
  --args $CP_CAP $STORE --gas-budget 10000000
```

### UC6: Governance

```powershell
# Pause / unpause protocol
sui client call --package $PACKAGE --module network_registry --function set_paused `
  --args $ADMIN_CAP $REGISTRY true --gas-budget 10000000

sui client call --package $PACKAGE --module network_registry --function set_paused `
  --args $ADMIN_CAP $REGISTRY false --gas-budget 10000000

# Update role thresholds (cp >= relay >= validator, in base units)
sui client call --package $PACKAGE --module network_registry --function update_role_thresholds `
  --args $ADMIN_CAP $REGISTRY 2000000000 1000000000 500000000 --gas-budget 10000000

# Update scoring weights (must sum to 10000)
sui client call --package $PACKAGE --module network_registry --function update_scoring_weights `
  --args $ADMIN_CAP $REGISTRY 3000 2500 2000 1500 1000 --gas-budget 10000000

# Update reward ratios (relay + validator + cp must sum to 10000)
sui client call --package $PACKAGE --module network_registry --function update_reward_ratios `
  --args $ADMIN_CAP $REGISTRY 7000 1500 1500 --gas-budget 10000000

# Update base rate per MB
sui client call --package $PACKAGE --module network_registry --function update_base_rate `
  --args $ADMIN_CAP $REGISTRY 100 --gas-budget 10000000
```

---

## Quick Reference

### Roles

| Role | ID | Min Stake |
|---|---|---|
| User | 0 | 0 |
| Validator | 1 | 500_000_000 (0.5 DVCONF) |
| Relay | 2 | 1_000_000_000 (1 DVCONF) |
| CP | 3 | 2_000_000_000 (2 DVCONF) |

### Error Codes

| Constant | Code | Module | Meaning |
|---|---|---|---|
| E_INVALID_WEIGHT | 100 | network_registry | Scoring weights don't sum to 10 000 |
| E_INVALID_THRESHOLD | 101 | network_registry | cp < relay or relay < validator |
| E_INVALID_RATIO | 102 | network_registry | Reward ratios don't sum to 10 000 |
| E_INSUFFICIENT_STAKE | 200 | staking | Slash amount exceeds balance |
| E_NOT_REGISTERED | 300 | miner_store | Profile not found in store |
| E_INSUFFICIENT_STAKE | 400 | registration | Not enough tokens for role |
| E_STAKE_LOCKED | 401 | registration | Can't unregister during active session |
| E_NOT_OWNER | 402 | registration | Wrong wallet calling update/unregister |
| E_PROTOCOL_PAUSED | 403 | registration | Protocol is paused |
| E_ALREADY_REGISTERED | 404 | registration | Wallet already has a miner profile |
| E_PAUSED | 500 | room_manager | Protocol is paused |
| E_NOT_CREATOR | 501 | room_manager | Caller is not the room creator |
| E_NOT_FOUND | 502 | room_manager | Room ID not found |
| E_ALREADY_CLOSED | 503 | room_manager | Room is already closed |
| E_INVALID_MODE | 504 | room_manager | Invalid conference mode |
| E_INVALID_MIN | 505 | room_manager | Invalid minimum participants value |
| E_USER_NOT_REGISTERED | 506 | room_manager | Caller has no user profile |
| E_NOT_CP | 510 | control_plane_registry | Caller does not hold a ControlPlaneCap |
| E_ALREADY_REGISTERED | 511 | control_plane_registry | CP already registered |
| E_NOT_REGISTERED | 512 | control_plane_registry | CP not registered |
| E_PAUSED | 513 | control_plane_registry | Protocol is paused |
| E_NOT_ACTIVE | 514 | control_plane_registry | CP is not in active state |
| E_ALREADY_ASSIGNED | 515 | control_plane_registry | Room already has a CP assigned |
| E_NOT_RELAY | 520 | relay_registry | Caller does not hold a RelayCap |
| E_ALREADY_REGISTERED | 521 | relay_registry | Relay already registered |
| E_NOT_REGISTERED | 522 | relay_registry | Relay not registered |
| E_PAUSED | 523 | relay_registry | Protocol is paused |
| E_NOT_OPERATOR | 524 | relay_registry | Caller is not the relay operator |
| E_INVALID_MODE | 525 | relay_registry | Invalid relay mode |
| E_NOT_VALIDATOR | 530 | validator_registry | Caller does not hold a ValidatorCap |
| E_ALREADY_REGISTERED | 531 | validator_registry | Validator already registered |
| E_NOT_REGISTERED | 532 | validator_registry | Validator not registered |
| E_PAUSED | 533 | validator_registry | Protocol is paused |
| E_SESSION_EXISTS | 534 | validator_registry | Session wallet already assigned |
| E_NO_SESSION | 535 | validator_registry | No active session wallet found |
| E_ALREADY_REGISTERED | 540 | user_registry | User already registered |
| E_NOT_REGISTERED | 541 | user_registry | User not registered |
| E_PAUSED | 542 | user_registry | Protocol is paused |
| E_NOT_SIGNALING | 600 | signaling_registry | Caller does not hold a SignalingCap |
| E_ALREADY_REGISTERED | 601 | signaling_registry | Signaling node already registered |
| E_NOT_REGISTERED | 602 | signaling_registry | Signaling node not registered |
| E_PAUSED | 603 | signaling_registry | Protocol is paused |
| E_NOT_OPERATOR | 604 | signaling_registry | Caller is not the signaling operator |
| E_PAUSED | 650 | economic_layer | Protocol is paused |
| E_NOT_ROOM_CREATOR | 651 | economic_layer | Caller is not the room creator |
| E_ROOM_NOT_FOUND | 652 | economic_layer | Room ID not found in escrow table |
| E_ROOM_NOT_PENDING | 653 | economic_layer | Room escrow is not in pending state |
| E_INVALID_SIGNATURE | 654 | economic_layer | Proof signature verification failed |
| E_SESSION_WALLET_NOT_FOUND | 655 | economic_layer | Validator session wallet not found |
| E_ALREADY_SUBMITTED | 656 | economic_layer | Proof already submitted for this session |
| E_ROOM_NOT_CLOSED | 657 | economic_layer | Room must be closed before distribution |
| E_INSUFFICIENT_PROOFS | 658 | economic_layer | Not enough validator proofs to distribute |
| E_ALREADY_DISTRIBUTED | 659 | economic_layer | Rewards already distributed for this room |
| E_ZERO_ESCROW | 660 | economic_layer | Escrow balance is zero |
| E_RELAY_NOT_REGISTERED | 661 | economic_layer | Relay node is not registered |
| E_VALIDATOR_NOT_ASSIGNED | 662 | economic_layer | Validator not assigned to room |
| E_NO_SLASH_PENDING | 663 | economic_layer | No pending slash obligation |
| E_WRONG_STAKE | 664 | economic_layer | Wrong StakePosition for slash |

### Default Parameters (from constants.move)

| Parameter | Value |
|---|---|
| CP threshold | 2 DVCONF (2_000_000_000) |
| Relay threshold | 1 DVCONF (1_000_000_000) |
| Validator threshold | 0.5 DVCONF (500_000_000) |
| Min relays per room | 2 |
| Min validators per room | 2 |
| Min CPs per room | 3 |
| Initial reputation | 5 000 |
| Default scoring weights | rep=3000 rtt=2500 load=2000 stake=1500 region=1000 |
| Default reward ratios | relay=7000 validator=1500 cp=1500 |

---

## Useful Commands

```powershell
# See all your objects
sui client objects

# Inspect specific object (shows all fields)
sui client object <ID>

# Check gas balance
sui client gas

# Current address
sui client active-address

# Switch environment
sui client switch --env testnet
sui client switch --env local
```
