/// Node Health — a faithful 3-level (0/1/2) self-degradation signal spanning all
/// four daemon types (validator / relay / cp / signaling).
///
/// A node reports its OWN health level via an operator-gated entry, emitting a
/// single canonical `NodeDegraded` event that off-chain reactors (F60 relay
/// self-shutdown, the viz panels, the chain-event-listener) self-filter by
/// `miner_id` — exactly as they already self-filter `economic_layer::RelaySlashed`.
///
/// Supersedes the relay-only / level-less / permissionless / test-only
/// `relay_registry::report_degradation` + `RelayPerformanceDegraded` pair, which
/// stay compiled but legacy-inert (no new producer wired) so the frozen
/// forensic-cli mirror is not perturbed.
///
/// Authority model (wired in P2): the node OWNS its cap, so there is no
/// cross-party owned-object footgun. The cap's role byte IS the node_type proof
/// — a relay cap can only report `node_type = 2` — so a daemon cannot forge a
/// foreign node_type. The module takes no registry object and performs no
/// existence check: `NodeDegraded` is emit-only and advisory, and every consumer
/// self-filters by its OWN `miner_id`, so a foreign emit cannot drive anyone
/// else's failover.
///
/// REQ-DOH-013/014/015/016/017/018. M2a Move SHIP gate at P12.
module dvconf::node_health {
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::constants;
    use sui::event;

    // ══════════════════════════════════════════════════════════
    // ERRORS — NEW 670-679 block (verified FREE at HEAD: economic_layer ends at
    // 665; role_voting / pairing_score start at 700). Wired into the asserts in
    // report_node_degradation below (P2).
    // ══════════════════════════════════════════════════════════
    const E_INVALID_LEVEL: u64     = 670; // level > 2
    const E_INVALID_NODE_TYPE: u64 = 671; // MinerCap role not in {1=validator, 2=relay, 4=signaling}
    const E_PAUSED: u64            = 672; // network paused (!is_paused backstop)
    const E_NOT_OPERATOR: u64      = 673; // operator != ctx.sender()

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    /// FROZEN at the M2a Move SHIP gate — field names + types + ORDER are
    /// load-bearing. The single-owner `NodeDegraded` TS interface in
    /// `@dvconf/shared` events.ts (P5) byte-mirrors this struct. Decoded
    /// off-chain by parsedJson KEY (NOT positional BCS): `ID` / `address` /
    /// `u64` serialize as strings, `u8` as a number (SecretRotated precedent).
    public struct NodeDegraded has copy, drop {
        miner_id:  ID,      // reporting node's miner id (from the cap)
        node_type: u8,      // 1=validator, 2=relay, 3=cp, 4=signaling (constants.move:13-17)
        level:     u8,      // 0=healthy, 1=degraded, 2=unhealthy
        operator:  address, // == ctx.sender()
        epoch:     u64,
    }

    // ══════════════════════════════════════════════════════════
    // ENTRIES  (P1 skeleton — signature FROZEN here; asserts + emit land in P2)
    // ══════════════════════════════════════════════════════════

    /// Generic operator-gated degradation report — relay / validator / signaling
    /// (the `MinerCap` role byte = the node_type proof). A PTB-callable
    /// `public fun` (mirrors the shipped `relay_heartbeat` shape), NOT `entry`,
    /// to stay composable. P2 wires the body:
    ///   - `!network_registry::is_paused(net_reg)` [E_PAUSED]
    ///   - `operator == ctx.sender()`              [E_NOT_OPERATOR]
    ///   - `caps::miner_cap_role(cap) in {1,2,4}`  [E_INVALID_NODE_TYPE]
    ///   - `level <= 2`                            [E_INVALID_LEVEL]
    ///   - emit `NodeDegraded { miner_id: caps::miner_cap_miner_id(cap),
    ///       node_type: caps::miner_cap_role(cap), level, operator,
    ///       epoch: ctx.epoch() }`
    public fun report_node_degradation(
        net_reg:  &NetworkRegistry,
        cap:      &MinerCap,
        operator: address,
        level:    u8,
        ctx:      &TxContext,
    ) {
        // Asserts in FROZEN order (DESIGN §1 / docstring above) — each P2 abort
        // test violates exactly one, in this order.
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(operator == ctx.sender(), E_NOT_OPERATOR);
        // node_type proof = the cap's role byte; relay caps can only report 2,
        // validator 1, signaling 4 — CP (3) must use report_cp_degradation (P3).
        let role = caps::miner_cap_role(cap);
        assert!(
            role == constants::role_validator()
                || role == constants::role_relay()
                || role == constants::role_signaling(),
            E_INVALID_NODE_TYPE,
        );
        assert!(level <= 2, E_INVALID_LEVEL);

        event::emit(NodeDegraded {
            miner_id:  caps::miner_cap_miner_id(cap),
            node_type: role,                 // derived from the cap role, never an arg
            level,
            operator,
            epoch:     ctx.epoch(),
        });
    }

    /// CP-specific operator-gated degradation report. A `ControlPlaneCap` carries
    /// NO role byte to derive from, so `node_type` is HARDCODED to
    /// `constants::role_cp() = 3` — the cap TYPE itself is the CP authority proof
    /// (only a CP operator holds a `ControlPlaneCap`), so there is NO role gate
    /// and therefore NO `E_INVALID_NODE_TYPE` (671) path. The remaining three
    /// asserts run in the same FROZEN order as `report_node_degradation`
    /// (PAUSED → NOT_OPERATOR → INVALID_LEVEL) and the emitted `NodeDegraded`
    /// shape is IDENTICAL — consumers cannot tell which entry produced it.
    public fun report_cp_degradation(
        net_reg:  &NetworkRegistry,
        cap:      &ControlPlaneCap,
        operator: address,
        level:    u8,
        ctx:      &TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(operator == ctx.sender(), E_NOT_OPERATOR);
        assert!(level <= 2, E_INVALID_LEVEL);

        event::emit(NodeDegraded {
            miner_id:  caps::cp_cap_miner_id(cap),
            node_type: constants::role_cp(),  // hardcoded 3; the cap type IS the CP proof
            level,
            operator,
            epoch:     ctx.epoch(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // TEST-ONLY (stripped from the published bytecode; ZERO production-path /
    // wire-contract change) — P4 (REQ-DOH-014).
    //
    // A named-field constructor so node_health_tests can materialize a
    // `NodeDegraded` with a chosen miner_id, in order to (i) LOCK the frozen BCS
    // wire layout the P5 single-owner TS mirror byte-mirrors, and (ii) prove the
    // off-chain self-filter drops a FOREIGN miner_id (DESIGN-CRITIQUE #8a). The
    // PRODUCTION emit ALWAYS derives miner_id from the cap (never an arg); this
    // constructor exists ONLY to read the field the Move test VM cannot decode off
    // a live-emitted event. Mirrors `registration::new_role_transitioned_for_testing`.
    // ══════════════════════════════════════════════════════════
    #[test_only]
    public fun new_node_degraded_for_testing(
        miner_id:  ID,
        node_type: u8,
        level:     u8,
        operator:  address,
        epoch:     u64,
    ): NodeDegraded {
        NodeDegraded { miner_id, node_type, level, operator, epoch }
    }
}
