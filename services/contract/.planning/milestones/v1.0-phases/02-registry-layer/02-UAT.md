---
status: complete
phase: 02-registry-layer
source: [02-VALIDATION.md, implementation plan]
started: 2026-03-05
updated: 2026-03-05
---

## Dependency Tree
<!--
T1 (All 79 Move tests pass)
├── T2 (UserRegistry: register + update + paused guard)
├── T3 (ValidatorRegistry: register + session wallets + paused guard)
├── T4 (RelayRegistry: register + load/mode/RTT + paused guard)
├── T5 (ControlPlaneRegistry: register + heartbeat + room assignments)
├── T6 (RoomManager: create + close + rules + paused guard)
├── T7 (Error code namespaces correct per module)
├── T8 (Source of Truth rules enforced)
├── T9 (Package-gated functions not externally callable)
└── T10 (Constants: room statuses + heartbeat timeout)
-->

## Current Test

[testing complete]

## Tests

### 1. All 79 Move tests pass
expected: Run `sui move test --silence-warnings`. Output: "Total tests: 79; passed: 79; failed: 0"
depends_on: none
result: pass

### 2. UserRegistry: register, update, and paused guard
expected: User can register with display name, update profile, duplicate registration aborts 540, unregistered update aborts 541, paused register aborts 542, paused update aborts 542.
depends_on: 1
result: pass

### 3. ValidatorRegistry: register, session wallets, and paused guard
expected: Validator registers with MinerCap(role=VALIDATOR), wrong role aborts 530, duplicate aborts 531, paused aborts 533. Session wallet assign/reveal are package-only. SessionWalletAssigned event has no miner_id. Reputation and session count are package-only.
depends_on: 1
result: pass

### 4. RelayRegistry: register, load/mode/RTT, and paused guard
expected: Relay registers with MinerCap(role=RELAY), wrong role aborts 520, duplicate aborts 521, paused aborts 523. Load is operator-updated. Mode update validates SFU/MCU (invalid aborts 525). RTT is package-only. Paused mode update aborts 523.
depends_on: 1
result: pass

### 5. ControlPlaneRegistry: register, heartbeat, room assignments
expected: CP registers with ControlPlaneCap, duplicate aborts 511, paused aborts 513. Heartbeat updates last_heartbeat and is_active. Liveness fields support timeout computation. Room assignment/unassignment are package-only.
depends_on: 1
result: pass

### 6. RoomManager: create, close, rules, and paused guard
expected: Registered user creates room (SFU or MCU mode), unregistered user aborts 506, invalid mode aborts 504, paused aborts 500. Creator closes room. Nonexistent room close aborts 502. Admin updates room rules. Room count tracks correctly. E_NOT_CREATOR (501) deferred to Phase 3 integration.
depends_on: 1
result: pass

### 7. Error code namespaces are correct and non-overlapping
expected: room_manager 500-509, control_plane_registry 510-519, relay_registry 520-529, validator_registry 530-539, user_registry 540-549. No overlaps, all codes match constants.
depends_on: 1
result: pass

### 8. Source of Truth rules enforced
expected: (a) Every state-mutating entry fn checks is_paused, (b) RTT update is public(package) only, (c) SessionWalletAssigned event does NOT leak miner_id, (d) All cap constructors are public(package) or AdminCap-gated.
depends_on: 1
result: pass

### 9. Package-gated functions not externally callable
expected: set_room_status, update_rtt, set_reputation, assign_session_wallet, reveal_session_wallet, increment_room_count, assign_to_room, unassign_from_room, increment_session_count, has_session_wallet — all use `public(package)` visibility.
depends_on: 1
result: pass

### 10. Constants: room statuses and heartbeat timeout
expected: ROOM_STATUS_PENDING=0, READY=1, ACTIVE=2, CLOSED=3. DEFAULT_HEARTBEAT_TIMEOUT=10.
depends_on: 1
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

[none]
