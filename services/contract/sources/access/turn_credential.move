/// TURN credential issuance — ADR-0005 ("TURN credential distribution
/// without central server").
///
/// ## Design
///
/// Pure event-emission module. No shared state. CP daemons compute
/// HMAC-SHA1 credentials off-chain (matching coturn `use-auth-secret`
/// REST API spec) and emit a chain-anchored audit event per issuance.
/// Miners + verifiers reconstruct the credential validity window by
/// reading the event stream.
///
/// Per-miner credential anchor already exists upstream:
/// `miner_store::Endpoint.turn_credential_hash` (set at `register()` and
/// updatable via `update_endpoint()`). Daemons mirror the latest issued
/// credential's hash into that field when they want long-lived
/// anchoring; this module only carries the issuance audit trail.
///
/// ## Why pure events (vs. shared registry)
///
/// 1. **ADR-0005 spec alignment** — explicit "Sui event + encrypted
///    blob (no HTTPS endpoint)" provisioning model, plus the
///    project-wide "chain carries no media" invariant.
/// 2. **Single responsibility** — keeps `caps.move` to capability
///    definitions; credential issuance is a distinct concern.
/// 3. **Minimum storage** — no shared object, no per-miner table; the
///    audit trail lives on the event log permanently.
///
/// ## Kill-switch path (deferred to S30.B/C)
///
/// `RelaySlashed` events are emitted by `relay_registry`; the CP daemon
/// observes them and stops issuing new TURN credentials for the slashed
/// miner. On-chain enforcement is not required because credentials are
/// short-lived (TTL ≤ 30 min) and verification is daemon-side.
///
/// Error code namespace: 800-809.
module dvconf::turn_credential {
    use sui::event;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, ControlPlaneCap};

    // ── Errors (800-809) ──
    const E_PAUSED:                u64 = 800;
    const E_TTL_OUT_OF_BOUNDS:     u64 = 801;
    const E_EMPTY_CREDENTIAL_HASH: u64 = 802;
    const E_INVALID_ROTATION_REASON: u64 = 803;  // F8: reason outside enum {0,1,2}
    const E_SAME_SECRET_ID:          u64 = 804;  // F8: new_secret_id == old_secret_id (no-op)

    // ── TTL bounds (ADR-0005 § lock — TTL 20 min within 15-30 band) ──
    const TTL_MIN_SEC:     u64 =   900;  // 15 min
    const TTL_DEFAULT_SEC: u64 = 1_200;  // 20 min (ADR-0005 default)
    const TTL_MAX_SEC:     u64 = 1_800;  // 30 min

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    /// Audit anchor: a CP issued a TURN credential for a target miner.
    /// The actual credential string lives off-chain; the hash is what's
    /// verifiable on-chain. `secret_id` ties the credential to a specific
    /// `static-auth-secret` rotation epoch (see `TurnSecretProvisioned`).
    public struct TurnCredentialIssued has copy, drop {
        cp_miner_id:     ID,
        target_miner_id: ID,
        issued_at_epoch: u64,
        ttl_sec:         u64,
        credential_hash: vector<u8>,
        secret_id:       u64,
    }

    /// Audit anchor: a CP rotated coturn's `static-auth-secret`. After
    /// this event, any `TurnCredentialIssued` with the new `secret_id`
    /// is signed against the new secret; older `secret_id`s remain valid
    /// for their respective TTL windows so existing sessions don't break.
    public struct TurnSecretProvisioned has copy, drop {
        cp_miner_id:      ID,
        secret_id:        u64,
        rotated_at_epoch: u64,
    }

    /// Audit anchor: a relay's coturn `static-auth-secret` was EMERGENCY-rotated
    /// under leakage / key-compromise (F8). Distinct from `TurnSecretProvisioned`
    /// (routine CP-cap rotation): this is the AdminCap break-glass path and
    /// carries both the retired `old_secret_id` and `new_secret_id` plus a
    /// `reason`, so the cp-daemon can invalidate credentials computed under the
    /// old secret while honoring the 2-secret overlap window.
    ///
    /// NOTE (F8 vs D-009 `refresh_capability_token`): that primitive rotates a
    /// *room admission* RoomCapability — a different object. This event rotates
    /// the TURN *shared secret*. The two are orthogonal mechanisms.
    public struct SecretRotated has copy, drop {
        cp_miner_id:      ID,
        old_secret_id:    u64,
        new_secret_id:    u64,
        reason:           u8,   // 0 = leakage, 1 = compromise, 2 = admin
        rotated_at_epoch: u64,
    }

    // ══════════════════════════════════════════════════════════
    // ENTRIES
    // ══════════════════════════════════════════════════════════

    /// Issue a TURN credential for `target_miner_id`. CP-cap gated.
    /// `ttl_sec` must fall within [TTL_MIN_SEC, TTL_MAX_SEC].
    /// `credential_hash` must be non-empty (typically SHA-256 of the
    /// HMAC-SHA1(username, secret) that the daemon hands to coturn).
    public fun issue_turn_credential(
        net:             &NetworkRegistry,
        cap:             &ControlPlaneCap,
        target_miner_id: ID,
        ttl_sec:         u64,
        credential_hash: vector<u8>,
        secret_id:       u64,
        ctx:             &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net), E_PAUSED);
        assert!(ttl_sec >= TTL_MIN_SEC && ttl_sec <= TTL_MAX_SEC, E_TTL_OUT_OF_BOUNDS);
        assert!(credential_hash.length() > 0, E_EMPTY_CREDENTIAL_HASH);

        event::emit(TurnCredentialIssued {
            cp_miner_id: caps::cp_cap_miner_id(cap),
            target_miner_id,
            issued_at_epoch: ctx.epoch(),
            ttl_sec,
            credential_hash,
            secret_id,
        });
    }

    /// Signal that a CP has rotated coturn's `static-auth-secret`. The
    /// new `secret_id` is an opaque counter the CP daemon controls.
    /// CP-cap gated; the paused guard prevents rotation churn during an
    /// admin freeze.
    public fun provision_turn_secret(
        net:       &NetworkRegistry,
        cap:       &ControlPlaneCap,
        secret_id: u64,
        ctx:       &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net), E_PAUSED);

        event::emit(TurnSecretProvisioned {
            cp_miner_id: caps::cp_cap_miner_id(cap),
            secret_id,
            rotated_at_epoch: ctx.epoch(),
        });
    }

    /// EMERGENCY-rotate a relay's coturn `static-auth-secret` under leakage /
    /// key-compromise (F8, REQ-CRR-004). AdminCap-gated break-glass path: unlike
    /// `provision_turn_secret` (CP-cap, routine rotation), this is the route when
    /// the CP itself may be compromised and CP-quorum cannot be awaited. Emits
    /// `SecretRotated`; the cp-daemon observes it and invalidates credentials
    /// computed under `old_secret_id`, honoring the 2-secret overlap window for
    /// in-flight sessions.
    ///
    /// `cp_miner_id` is explicit because an AdminCap — unlike a ControlPlaneCap —
    /// carries no miner binding.
    ///
    /// Forward-compat (post-F10 AdminCap->CP-quorum migration): a parallel
    /// quorum-gated rotate entry can be added later without touching the
    /// `SecretRotated` event or the daemon handler. See ADR-0010 addendum.
    ///
    /// Aborts with:
    ///   E_PAUSED (800)                  — network circuit breaker (paused-flag invariant; SoT)
    ///   E_SAME_SECRET_ID (804)          — new_secret_id == old_secret_id (no-op rotation)
    ///   E_INVALID_ROTATION_REASON (803) — reason outside enum {0=leakage,1=compromise,2=admin}
    public fun emergency_rotate_relay_secret(
        _admin:        &AdminCap,
        net:           &NetworkRegistry,
        cp_miner_id:   ID,
        old_secret_id: u64,
        new_secret_id: u64,
        reason:        u8,
        ctx:           &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net), E_PAUSED);
        assert!(new_secret_id != old_secret_id, E_SAME_SECRET_ID);
        assert!(reason <= 2, E_INVALID_ROTATION_REASON);

        event::emit(SecretRotated {
            cp_miner_id,
            old_secret_id,
            new_secret_id,
            reason,
            rotated_at_epoch: ctx.epoch(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS (for daemons + tests)
    // ══════════════════════════════════════════════════════════

    public fun ttl_min_sec():     u64 { TTL_MIN_SEC     }
    public fun ttl_default_sec(): u64 { TTL_DEFAULT_SEC }
    public fun ttl_max_sec():     u64 { TTL_MAX_SEC     }
}
