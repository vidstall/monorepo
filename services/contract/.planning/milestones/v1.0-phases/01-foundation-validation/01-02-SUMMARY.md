# Plan 01-02 Summary: Testnet Deployment

## Status: COMPLETE (pending human verification)

## What was done
1. Pre-flight: All 34 tests pass, testnet environment active, correct address
2. Faucet: User manually funded CLI address via web UI (API faucet was rate-limited)
3. Published: `sui client publish --gas-budget 500000000 --json` succeeded
4. Extracted all object IDs from JSON output
5. Created `.env.testnet` with all 7 object IDs
6. Updated `.planning/PROJECT.md` with deployment context

## Deployment Details

| Field | Value |
|-------|-------|
| Transaction Digest | `4HG67tjy5nJbkagmJgMoGwiLcstohqvsEZK7aCt46Kp8` |
| Checkpoint | 304173943 |
| Gas Used | ~0.114 SUI |
| Modules Published | caps, constants, cp_queries, miner_store, network_registry, registration, staking, token |

## Object IDs

| Object | ID |
|--------|----|
| Package | `0xf7cf30b14c70c62271674f45098ba7c912d5bcf9e44896e1fb700723c45d3ef3` |
| NetworkRegistry (shared) | `0x890e2a9a1b9eea5828f67d7e56638a09ee57ab5ac05cef87bdbdd7afc7ea367b` |
| MinerStore (shared) | `0x10f7fabfc0add3f2214b3a26af28ca501ea26a337983e03aa150b6e1a9fb6345` |
| TreasuryCap (owned) | `0xe02074748407d71b50abaded5a30142bc4ec1933b44d52aac3d545fa3d2d8a7c` |
| AdminCap (owned) | `0x940c5a4f4e40b7c44f8fe478a3a1800bb271cd2f41e9ed5446a7c92eabd6b12b` |
| UpgradeCap (owned) | `0xbbde36fe3d98b1fede07fca846abd9bc6780b889f42d3aa575ac36ccd6e55a2e` |
| CoinMetadata (immutable) | `0xc596cdaa22e11b1aee77a921bc979be68c26b70159b40595b51dd2acf4d7404f` |

## Requirements Covered
- FOUND-01: Token deployed
- FOUND-02: Registry deployed
- FOUND-12: All IDs recorded
