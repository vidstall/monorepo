# Open Questions — cp-voting-consensus

## Active
1. **Vote reset loop**: If CPs persistently can't find valid pairings, rooms stay PENDING indefinitely. Should there be a timeout fallback? — **Deferred post-thesis**
2. **Proposer reward source**: From room escrow (reduces participant rewards) or from protocol treasury (requires minting/reserve)? — **Decide in Phase 2 design**
3. **Region encoding**: Nodes self-report region as string. What's the taxonomy? (e.g., "us-east", "eu-west", continent codes?) — **Decide in Phase 2 design**
4. **History score bootstrapping**: New nodes default to 5000. How many sessions before history becomes reliable? — **Accepted as-is for thesis**
5. **Proportional validator formula**: `expected_participants / N` — what's N? Min 1, max cap? — **Decide in Phase 2 design**

## Resolved
- Consensus model → PVR (Propose-Verify-Reward), not appearance-count voting
- Formula determinism → Fully deterministic, all inputs on-chain, verifiable by contract
- Why CPs needed → CPs do expensive combinatorial search off-chain, contract verifies one result cheaply
- Ballot structure → Unified single TX: (relay_ids, validator_ids, signaling_id, computed_score)
- Validator assignment → Hybrid: CPs assign primary, any validator can backup-probe
- Reputation → Simple wins counter, used for tie-breaking
- Formula weights → RTT(3000) + Load(2500) + Stake(1500) + Liveness(1000) + Region(1000) + History(1000) = 10000
- Formula storage → Named constants in constants.move
- Scoring transparency → Off-chain scoring for search, on-chain verification for trust
- `assign_relay_and_signaling()` → Kept as fallback
- Gas concerns → Not a concern for thesis
- `expected_participants` accuracy → Accepted limitation, not enforced
