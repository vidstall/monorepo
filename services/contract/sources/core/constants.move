/// Network-wide constants for the DVConf protocol.
///
/// All numeric parameters (role thresholds, scoring weights, reward ratios,
/// and network minimums) are collected here so every module reads from one
/// source of truth.  Weights and ratios are expressed as *basis points*
/// (integers, base 10 000) — never floating point.
module dvconf::constants {

    // ── Basis points ──
    const BASIS_POINTS: u64 = 10_000;

    // ── Miner roles ──
    const ROLE_USER: u8      = 0;
    const ROLE_VALIDATOR: u8 = 1;
    const ROLE_RELAY: u8     = 2;
    const ROLE_CP: u8        = 3;
    const ROLE_SIGNALING: u8 = 4;

    // ── Relay modes ──
    const RELAY_MODE_SFU: u8 = 0;
    const RELAY_MODE_MCU: u8 = 1;

    // ── Default role thresholds (MIST; 1 SUI = 1_000_000_000) ──
    // Only CP is auto-assigned by stake; all other roles enter voting queue.
    const DEFAULT_CP_THRESHOLD: u64        = 500_000_000; // 0.5 SUI (base for first CP)
    const CP_THRESHOLD_STEP: u64           = 100_000_000; // +0.1 SUI per existing CP
    // Legacy thresholds kept for minimum_for_role (stake validation only, not role assignment)
    const DEFAULT_RELAY_THRESHOLD: u64     = 250_000_000; // 0.25 SUI
    const DEFAULT_VALIDATOR_THRESHOLD: u64 = 100_000_000; // 0.1 SUI
    const DEFAULT_SIGNALING_THRESHOLD: u64 =  50_000_000; // 0.05 SUI

    // ── Default scoring weights (basis points, sum = BASIS_POINTS) ──
    const DEFAULT_W_REPUTATION: u64   = 3_000;
    const DEFAULT_W_RTT: u64          = 2_500;
    const DEFAULT_W_LOAD: u64         = 2_000;
    const DEFAULT_W_STAKE: u64        = 1_500;
    const DEFAULT_W_REGION_MATCH: u64 = 1_000;

    // ── Default reward ratios (basis points, sum = BASIS_POINTS) ──
    const DEFAULT_RATIO_RELAY: u64         = 7_000;
    const DEFAULT_RATIO_VALIDATOR: u64     = 1_500;
    const DEFAULT_RATIO_CONTROL_PLANE: u64 = 1_500;

    // ── Default network parameters ──
    const DEFAULT_BASE_RATE_PER_MB: u64           =   100;
    // ADR-0006: BFT (n >= 3f+1) — n=4 (f=1) minimum non-trivial; quorum = 2f+1 = 3.
    const DEFAULT_MIN_VALIDATORS_PER_ROOM: u64    =     4;
    const QUORUM_THRESHOLD: u64                   =     3;
    const DEFAULT_MIN_RELAYS_PER_ROOM: u64        =     2;
    const DEFAULT_MIN_CPS_PER_ROOM: u64           =     3;
    const DEFAULT_CP_CONSENSUS_THRESHOLD_BPS: u64 = 6_667;
    const DEFAULT_VERSION: u64                    =     1;

    // ── Relay failover (ADR-0004) ──
    // N consecutive heartbeat misses before CP declares the relay crashed (~30s at 10s cadence).
    const HEARTBEAT_MISS_THRESHOLD: u64 = 3;

    // ── Room status codes ──
    const ROOM_STATUS_PENDING: u8 = 0;
    const ROOM_STATUS_READY: u8   = 1;
    const ROOM_STATUS_ACTIVE: u8  = 2;
    const ROOM_STATUS_CLOSED: u8  = 3;

    // ── Heartbeat timeout (epochs) ──
    const DEFAULT_HEARTBEAT_TIMEOUT: u64 = 10;

    // ── Default miner values ──
    const DEFAULT_INITIAL_REPUTATION: u64 = 5_000;

    // ── Quality multiplier thresholds (basis points) ──
    const QUALITY_EXCELLENT_BPS: u64    = 10_000;  // 100% reward
    const QUALITY_GOOD_BPS: u64         =  8_000;  // 80% reward
    const QUALITY_ACCEPTABLE_BPS: u64   =  5_000;  // 50% reward
    const QUALITY_SLASH_BPS: u64        =      0;  // 0% reward, triggers slash

    // ── Packet loss thresholds (basis points; 100 bps = 1%) ──
    const LOSS_THRESHOLD_EXCELLENT: u64  =   200;  // <= 2%
    const LOSS_THRESHOLD_GOOD: u64       =   500;  // <= 5%
    const LOSS_THRESHOLD_ACCEPTABLE: u64 = 1_000;  // <= 10%

    // ── Slash parameters ──
    const SLASH_PERCENTAGE_BPS: u64 = 1_000;  // 10% of stake

    // ── Signaling economics ──
    const SIGNALING_SESSION_REWARD: u64 = 50;  // flat rate per session routed

    // ── Proof aggregation ──
    const MIN_PROOFS_FOR_DISTRIBUTION: u64 = 2;  // minimum validator proofs needed

    // ── CP-quorum cap-token threshold (REQ-ADM-008, D-B4) ──
    // Default M-of-N = 2-of-3 (BFT 67% minority tolerance). Configurable post-deploy
    // via cp_quorum_sig::update_threshold (AdminCap-gated Stage 1, CP-quorum gated post-F10/W3).
    const MIN_CP_QUORUM_FOR_TOKEN: u64 = 2;

    // ── Late-join admission window (REQ-ADM-014, D-OQ-2.3-1) ──
    // Minimum epochs that must remain before existing RoomCapability.expires_epoch
    // when admitting a late-join peer. Default 5 (≈5min mainnet / ~50min testnet).
    // FIXED value — not configurable per user choice (OQ-PHASE-2.3-1 locked S53).
    // Future migration: could become AdminCap-updatable post-thesis (see D-007-D).
    const MIN_REMAINING_EPOCHS: u64 = 5;

    // ── Scarcity reward clamping (basis points) ──
    const SCARCITY_FLOOR_BPS: u64   =   500;  // 5% minimum share per role
    const SCARCITY_CEILING_BPS: u64 = 8_000;  // 80% maximum share per role

    // ── PVR Scoring Weights (basis points, sum = 10_000) ──
    const PVR_W_RTT: u64      = 3_000;
    const PVR_W_LOAD: u64     = 2_500;
    const PVR_W_STAKE: u64    = 1_500;
    const PVR_W_LIVENESS: u64 = 1_000;
    const PVR_W_REGION: u64   = 1_000;
    const PVR_W_HISTORY: u64  = 1_000;

    // ── PVR Scoring Thresholds ──
    const PVR_MAX_RTT: u64           = 500;             // ms — above this, RTT score = 0
    const PVR_MAX_LOAD: u64          = 100;             // connections — above this, load score = 0
    const PVR_STAKE_CAP: u64         = 5_000_000_000;   // 5 SUI — diminishing returns above
    const PVR_HEARTBEAT_FRESH: u64   = 3;               // epochs — full liveness score
    const PVR_HEARTBEAT_STALE: u64   = 7;               // epochs — half liveness score
    const PVR_DEFAULT_HISTORY: u64   = 5_000;           // default for nodes with no session history

    // ── PVR Validator Scaling ──
    const PVR_VALIDATOR_RATIO: u64           = 3;       // 1 validator per N participants
    const PVR_MAX_VALIDATORS_PER_ROOM: u64   = 5;       // hard cap

    // ── PVR Proposer Reward ──
    const PVR_PROPOSER_REWARD: u64 = 100;               // flat reward units per winning proposal

    // ── PVR Consensus ──
    const PVR_DISPUTE_COOLDOWN: u64 = 2;              // epochs before creator can trigger dispute
    const PVR_CONSENSUS_THRESHOLD_BPS: u64 = 6_667;   // 2/3 of votes cast

    // ── Accessors ──

    public fun basis_points(): u64 { BASIS_POINTS }

    public fun role_user(): u8      { ROLE_USER }
    public fun role_validator(): u8 { ROLE_VALIDATOR }
    public fun role_relay(): u8     { ROLE_RELAY }
    public fun role_cp(): u8        { ROLE_CP }
    public fun role_signaling(): u8 { ROLE_SIGNALING }

    public fun relay_mode_sfu(): u8 { RELAY_MODE_SFU }
    public fun relay_mode_mcu(): u8 { RELAY_MODE_MCU }

    public fun default_cp_threshold(): u64        { DEFAULT_CP_THRESHOLD }
    public fun cp_threshold_step(): u64           { CP_THRESHOLD_STEP }
    public fun default_relay_threshold(): u64     { DEFAULT_RELAY_THRESHOLD }
    public fun default_validator_threshold(): u64 { DEFAULT_VALIDATOR_THRESHOLD }
    public fun default_signaling_threshold(): u64 { DEFAULT_SIGNALING_THRESHOLD }

    public fun default_w_reputation(): u64   { DEFAULT_W_REPUTATION }
    public fun default_w_rtt(): u64          { DEFAULT_W_RTT }
    public fun default_w_load(): u64         { DEFAULT_W_LOAD }
    public fun default_w_stake(): u64        { DEFAULT_W_STAKE }
    public fun default_w_region_match(): u64 { DEFAULT_W_REGION_MATCH }

    public fun default_ratio_relay(): u64         { DEFAULT_RATIO_RELAY }
    public fun default_ratio_validator(): u64     { DEFAULT_RATIO_VALIDATOR }
    public fun default_ratio_control_plane(): u64 { DEFAULT_RATIO_CONTROL_PLANE }

    public fun default_base_rate_per_mb(): u64           { DEFAULT_BASE_RATE_PER_MB }
    public fun default_min_validators_per_room(): u64    { DEFAULT_MIN_VALIDATORS_PER_ROOM }
    public fun quorum_threshold(): u64                   { QUORUM_THRESHOLD }
    public fun default_min_relays_per_room(): u64        { DEFAULT_MIN_RELAYS_PER_ROOM }
    public fun default_min_cps_per_room(): u64           { DEFAULT_MIN_CPS_PER_ROOM }
    public fun default_cp_consensus_threshold_bps(): u64 { DEFAULT_CP_CONSENSUS_THRESHOLD_BPS }
    public fun default_version(): u64                    { DEFAULT_VERSION }

    public fun heartbeat_miss_threshold(): u64 { HEARTBEAT_MISS_THRESHOLD }

    public fun default_initial_reputation(): u64 { DEFAULT_INITIAL_REPUTATION }

    public fun room_status_pending(): u8 { ROOM_STATUS_PENDING }
    public fun room_status_ready(): u8   { ROOM_STATUS_READY }
    public fun room_status_active(): u8  { ROOM_STATUS_ACTIVE }
    public fun room_status_closed(): u8  { ROOM_STATUS_CLOSED }

    public fun default_heartbeat_timeout(): u64 { DEFAULT_HEARTBEAT_TIMEOUT }

    public fun quality_excellent_bps(): u64    { QUALITY_EXCELLENT_BPS }
    public fun quality_good_bps(): u64         { QUALITY_GOOD_BPS }
    public fun quality_acceptable_bps(): u64   { QUALITY_ACCEPTABLE_BPS }
    public fun quality_slash_bps(): u64        { QUALITY_SLASH_BPS }

    public fun loss_threshold_excellent(): u64  { LOSS_THRESHOLD_EXCELLENT }
    public fun loss_threshold_good(): u64       { LOSS_THRESHOLD_GOOD }
    public fun loss_threshold_acceptable(): u64 { LOSS_THRESHOLD_ACCEPTABLE }

    public fun slash_percentage_bps(): u64 { SLASH_PERCENTAGE_BPS }

    public fun signaling_session_reward(): u64 { SIGNALING_SESSION_REWARD }

    public fun min_proofs_for_distribution(): u64 { MIN_PROOFS_FOR_DISTRIBUTION }

    public fun min_cp_quorum_for_token(): u64 { MIN_CP_QUORUM_FOR_TOKEN }

    /// Minimum epochs remaining on an existing RoomCapability before a late-join
    /// peer may be admitted. Guards against issuing tokens with negligible TTL.
    /// REQ-ADM-014 D-OQ-2.3-1: fixed at 5 (≈5min mainnet / ~50min testnet).
    public fun min_remaining_epochs(): u64 { MIN_REMAINING_EPOCHS }

    public fun scarcity_floor_bps(): u64   { SCARCITY_FLOOR_BPS }
    public fun scarcity_ceiling_bps(): u64 { SCARCITY_CEILING_BPS }

    // ── PVR Accessors ──
    public fun pvr_w_rtt(): u64      { PVR_W_RTT }
    public fun pvr_w_load(): u64     { PVR_W_LOAD }
    public fun pvr_w_stake(): u64    { PVR_W_STAKE }
    public fun pvr_w_liveness(): u64 { PVR_W_LIVENESS }
    public fun pvr_w_region(): u64   { PVR_W_REGION }
    public fun pvr_w_history(): u64  { PVR_W_HISTORY }

    public fun pvr_max_rtt(): u64           { PVR_MAX_RTT }
    public fun pvr_max_load(): u64          { PVR_MAX_LOAD }
    public fun pvr_stake_cap(): u64         { PVR_STAKE_CAP }
    public fun pvr_heartbeat_fresh(): u64   { PVR_HEARTBEAT_FRESH }
    public fun pvr_heartbeat_stale(): u64   { PVR_HEARTBEAT_STALE }
    public fun pvr_default_history(): u64   { PVR_DEFAULT_HISTORY }

    public fun pvr_validator_ratio(): u64         { PVR_VALIDATOR_RATIO }
    public fun pvr_max_validators_per_room(): u64 { PVR_MAX_VALIDATORS_PER_ROOM }

    public fun pvr_proposer_reward(): u64 { PVR_PROPOSER_REWARD }

    public fun pvr_dispute_cooldown(): u64 { PVR_DISPUTE_COOLDOWN }
    public fun pvr_consensus_threshold_bps(): u64 { PVR_CONSENSUS_THRESHOLD_BPS }
}
