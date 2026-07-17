/// Base capability-token events — REQ-ADM-005 (base events portion).
/// Phase 1.2 of room-admission-control milestone 1 (F62, Wave W1 P16).
///
/// ## Fork 6 — Additive-only event convention
///
/// These three structs are the shared base layer. Feature-specific wrappers in
/// Phase 2.x (room_capability.move) and future waves (F5 TURN cap revocation,
/// F8 relay secret rotation) MUST NOT modify the base struct field list. They
/// compose by wrapping: e.g. `RoomCapabilityIssued { base: CapabilityIssued, room_field: ... }`.
/// New base event types may be added additively in future phases; existing field
/// order is frozen at Phase 1.2 SHIP gate (S53 2026-05-25).
///
/// ## Cross-Wave consumers
///
/// | Consumer | Wave | Relationship |
/// |---|---|---|
/// | room_capability.move (F62) | W1 | Phase 2.1+ wraps these base events |
/// | cp-daemon (F62) | W1 | Phase 3.1 subscribes CapabilityIssued / CapabilityRevoked |
/// | TURN cap revocation (F5) | W2+ | Pending brainstorm; will wrap CapabilityRevoked |
/// | Relay secret rotation (F8) | W2+ | Pending brainstorm; will wrap CapabilityRefreshed |
/// | Cooldown updates (F47) | W1 lane B | Listens CapabilityRefreshed for role-change grace window |
///
/// ## BCS layout snapshot (frozen S53)
///
/// Field order determines off-chain deserialization in dvconf-daemons/apps/cp-daemon.
/// MUST NOT reorder fields without a BCS-breaking-change ADR and daemon update.
///
/// CapabilityIssued {
///   token_id:       ID              (32 bytes, UID object ID)
///   room_id:        ID              (32 bytes)
///   peer_pubkey:    vector<u8>      (variable; ed25519 = 32 bytes per D-OQ-ADM-3)
///   role:           u8              (1 byte; role enum: relay/signaling/CP/validator)
///   issuer_quorum:  vector<address> (variable; each address = 32 bytes)
///   expires_epoch:  u64             (8 bytes)
/// }
///
/// CapabilityRevoked {
///   token_id:        ID              (32 bytes)
///   room_id:         ID              (32 bytes)
///   revoker_quorum:  vector<address> (variable)
///   reason:          u8              (1 byte; enum: 0=normal 1=slash 2=admin)
/// }
///
/// CapabilityRefreshed {
///   token_id:          ID              (32 bytes)
///   room_id:           ID              (32 bytes)
///   peer_pubkey:       vector<u8>      (variable)
///   old_expires_epoch: u64             (8 bytes)
///   new_expires_epoch: u64             (8 bytes)
///   refresher_quorum:  vector<address> (variable)
/// }
///
/// ## Visibility
///
/// Emit helpers are `public(package)` per Source of Truth Rule "Cap constructors are
/// package-private". Emitting a fake audit event from an external package is prevented
/// at the Move type system level — only modules in the `dvconf` package can call these.
/// Feature wrappers in Phase 2.x live in the same package and invoke these helpers.
module dvconf::capability_events {
    use sui::event;

    // ── Event structs ────────────────────────────────────────────────────
    // `has copy, drop` (NOT store) — events are ephemeral Sui objects;
    // they are emitted then discarded. Mirrors Phase 1.1 QuorumVerified pattern.

    /// Emitted when a new capability token is issued to a peer.
    public struct CapabilityIssued has copy, drop {
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issuer_quorum: vector<address>,
        expires_epoch: u64,
    }

    /// Emitted when a capability token is revoked.
    ///
    /// `reason` encoding (informational u8, not enforced on-chain):
    ///   0 = normal  — voluntary / room closed
    ///   1 = slash   — triggered by relay/validator slash event
    ///   2 = admin   — AdminCap override (emergency)
    public struct CapabilityRevoked has copy, drop {
        token_id: ID,
        room_id: ID,
        revoker_quorum: vector<address>,
        reason: u8,
    }

    /// Emitted when a capability token's expiry is extended (role-change grace
    /// window per REQ-ADM-013, or routine 60s sliding TTL refresh per D-OQ-ADM-5).
    public struct CapabilityRefreshed has copy, drop {
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        old_expires_epoch: u64,
        new_expires_epoch: u64,
        refresher_quorum: vector<address>,
    }

    // ── Emit helpers ─────────────────────────────────────────────────────

    /// Emit a `CapabilityIssued` event. Called by Phase 2.x issue entry points.
    public(package) fun emit_capability_issued(
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issuer_quorum: vector<address>,
        expires_epoch: u64,
    ) {
        event::emit(CapabilityIssued {
            token_id,
            room_id,
            peer_pubkey,
            role,
            issuer_quorum,
            expires_epoch,
        });
    }

    /// Emit a `CapabilityRevoked` event. Called by Phase 2.x revoke entry points.
    public(package) fun emit_capability_revoked(
        token_id: ID,
        room_id: ID,
        revoker_quorum: vector<address>,
        reason: u8,
    ) {
        event::emit(CapabilityRevoked {
            token_id,
            room_id,
            revoker_quorum,
            reason,
        });
    }

    /// Emit a `CapabilityRefreshed` event. Called by Phase 2.x refresh entry points.
    public(package) fun emit_capability_refreshed(
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        old_expires_epoch: u64,
        new_expires_epoch: u64,
        refresher_quorum: vector<address>,
    ) {
        event::emit(CapabilityRefreshed {
            token_id,
            room_id,
            peer_pubkey,
            old_expires_epoch,
            new_expires_epoch,
            refresher_quorum,
        });
    }
}
