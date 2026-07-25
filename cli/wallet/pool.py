from __future__ import annotations

import random
import uuid
from typing import Any

from .chain_ops import faucet_if_needed, generate_sui_keypair, generate_x25519_secret, resolve_cap_id
from .storage import _all_pool_envs, _read_pool, _timestamp, _write_pool

_ALIAS_ADJECTIVES = [
    "affectionate", "amused", "brave", "calm", "clever", "cosmic", "curious",
    "daring", "eager", "elegant", "fearless", "fierce", "gentle", "golden",
    "graceful", "happy", "humble", "jolly", "keen", "lively", "lucky",
    "mellow", "merry", "mighty", "noble", "nimble", "patient", "playful",
    "proud", "quiet", "quick", "radiant", "serene", "sharp", "silent",
    "silver", "sincere", "spirited", "steady", "sunny", "swift", "tender",
    "tranquil", "vivid", "witty", "wise", "zealous", "bold", "bright", "cozy",
]
_ALIAS_NOUNS = [
    "jet", "falcon", "otter", "harbor", "meadow", "canyon", "comet", "delta",
    "ember", "fjord", "glacier", "grove", "horizon", "island", "lagoon",
    "lantern", "maple", "meridian", "nebula", "orbit", "orchid", "panther",
    "pebble", "phoenix", "prairie", "quartz", "raven", "reef", "ridge",
    "river", "sable", "sequoia", "shore", "sparrow", "summit", "tundra",
    "valley", "willow", "wren", "zephyr", "brook", "cedar", "cliff", "coral",
    "dune", "forest", "glade", "hollow", "isle", "marsh",
]


def checkout_wallet(
    host: str, service: str, provider: str, env_name: str, worker_index: int = 1
) -> tuple[dict[str, Any], bool]:
    """Assign a free pooled wallet to (host, service, provider, env_name, worker_index).

    `worker_index` (1-based) distinguishes multiple colocated workers of
    the SAME service on one --host (see vidctl.py's count-prefix --service
    syntax, e.g. `5cp-daemon`) -- each index gets its own independently
    checked-out wallet. It plays no part in the `registered_role` pin below:
    a replica is still fundamentally the same on-chain role as any other
    worker of that service.

    Idempotent: if this exact worker identity already holds an assignment
    (e.g. a `restart` on an already-running worker), that wallet is reused
    rather than checking out a second one.

    Otherwise, a free wallet is picked -- but ONLY from wallets whose
    `registered_role` is either unset (never checked out for anything yet)
    or already equal to `service`. On-chain registration is a one-time,
    permanent action per wallet (register() aborts if called again for a
    DIFFERENT role); `release_wallet()` frees a wallet for reassignment on
    the NEXT worker, but a wallet that already registered as (say) relay
    must only ever be reused as relay again, never reassigned to cp-daemon
    or any other service -- doing so previously caused
    `registration::E_ALREADY_REGISTERED` aborts when an worker was
    killed and recreated, since the wallet pool had no memory of which role
    a wallet had actually registered as on-chain.

    `registered_role` is set once, on this wallet's first-ever checkout, and
    is never cleared by `release_wallet()` -- it is permanent for the
    wallet's lifetime, unlike the assigned_* fields which just track the
    CURRENT holder. If the pool has no free wallet matching (or unpinned
    for) `service`, one is lazily generated and assigned. Returns (entry, created).
    """
    pool = _read_pool(env_name)
    wallets = pool.setdefault("wallets", [])

    for entry in wallets:
        if _matches(entry, host, service, provider, worker_index):
            if entry.get("retired"):
                # This worker's previously-bound wallet was flagged (see
                # retire_wallet()) since its last checkout -- e.g. its
                # miner_id picked up a permanent on-chain NodeDegraded(level=2)
                # history, which makes SelfShutdownWatcher self-terminate on
                # EVERY future boot (services/worker/packages/chain-event-listener/
                # src/self-shutdown-watcher.ts: a fresh subscriber with no local
                # cursor replays the module's full event history from genesis,
                # so this isn't fixable by clearing local state -- the wallet
                # itself must never be reused). Release the binding instead of
                # matching, so this call falls through to the free-wallet pick
                # below and this worker "logs out" of the bad wallet before
                # "logging in" with a clean one.
                entry["assigned_host"] = ""
                entry["assigned_service"] = ""
                entry["assigned_provider"] = ""
                entry["assigned_worker_index"] = 0
                entry["assigned_at"] = ""
                entry["released_at"] = _timestamp()
                break
            faucet_if_needed(entry, env_name)
            resolve_cap_id(entry, service, env_name)
            _write_pool(env_name, pool)
            return entry, False

    free = [
        entry
        for entry in wallets
        if not entry.get("assigned_host")
        and entry.get("registered_role", "") in ("", service)
        and not entry.get("role_mismatch")
        and not entry.get("retired")
    ]
    created = False
    if free:
        entry = random.choice(free)
    else:
        existing_aliases = {w.get("alias", "") for w in wallets if w.get("alias")}
        address, secret_key = generate_sui_keypair()
        entry = {
            "id": uuid.uuid4().hex,
            "alias": _generate_alias(existing_aliases),
            "address": address,
            "secret_key": secret_key,
            "x25519_secret": generate_x25519_secret(),
            "node_id": "",
            "created_at": _timestamp(),
            "last_balance_mist": 0,
            "last_faucet_at": "",
            "assigned_host": "",
            "assigned_service": "",
            "assigned_provider": "",
            "assigned_worker_index": 0,
            "assigned_at": "",
            "released_at": "",
            "registered_role": "",
            "cap_id": "",
            "cap_id_package": "",
            "retired": False,
            "retired_at": "",
            "retired_reason": "",
        }
        wallets.append(entry)
        created = True

    entry["assigned_host"] = host
    entry["assigned_service"] = service
    entry["assigned_provider"] = provider
    entry["assigned_worker_index"] = worker_index
    entry["assigned_at"] = _timestamp()
    if not entry.get("registered_role"):
        entry["registered_role"] = service

    faucet_if_needed(entry, env_name)
    resolve_cap_id(entry, service, env_name)
    _write_pool(env_name, pool)
    return entry, created


def release_wallet(
    host: str, service: str, provider: str, env_name: str, worker_index: int = 1
) -> dict[str, Any] | None:
    """Return the wallet assigned to (host, service, provider, env_name,
    worker_index) to the free pool. Clears assignment fields only; the
    wallet record (address, secret_key, x25519_secret) AND its permanent
    `registered_role` pin are kept for future reuse. Does not perform any
    on-chain registry cleanup. Returns the released entry, or None if no
    wallet was assigned to this worker."""
    pool = _read_pool(env_name)
    for entry in pool.get("wallets", []):
        if _matches(entry, host, service, provider, worker_index):
            entry["assigned_host"] = ""
            entry["assigned_service"] = ""
            entry["assigned_provider"] = ""
            entry["assigned_worker_index"] = 0
            entry["assigned_at"] = ""
            entry["released_at"] = _timestamp()
            _write_pool(env_name, pool)
            return entry
    return None


def retire_wallet(identifier: str, env_name: str, reason: str = "") -> dict[str, Any] | None:
    """Permanently exclude a pooled wallet from future checkouts (by alias or
    address). Registration on-chain is one-time and permanent, and a wallet
    whose miner_id has picked up a permanent NodeDegraded(level=2)/RelaySlashed
    history will re-trigger SelfShutdownWatcher on every future boot no matter
    which worker it's assigned to (a fresh subscriber replays that module's
    full on-chain event history from genesis when it has no local cursor --
    see self-shutdown-watcher.ts -- so there is no local fix). Retiring is the
    only real remedy: the wallet record is kept (never deleted, matching
    release_wallet()'s "never on-chain cleanup" contract) but permanently
    skipped by checkout_wallet()'s free-wallet filter, and any worker
    currently bound to it is released so its next checkout draws a
    different (or freshly minted) wallet instead. Returns the retired entry,
    or None if no wallet matched `identifier`."""
    pool = _read_pool(env_name)
    for entry in pool.get("wallets", []):
        if identifier in (entry.get("alias"), entry.get("address")):
            entry["retired"] = True
            entry["retired_at"] = _timestamp()
            entry["retired_reason"] = reason
            entry["assigned_host"] = ""
            entry["assigned_service"] = ""
            entry["assigned_provider"] = ""
            entry["assigned_worker_index"] = 0
            entry["assigned_at"] = ""
            entry["released_at"] = _timestamp()
            _write_pool(env_name, pool)
            return entry
    return None


def pool_status(env_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read-only listing for `vidctl wallet list`, secret fields stripped."""
    envs = [env_name] if env_name else _all_pool_envs()
    result: dict[str, list[dict[str, Any]]] = {}
    for env in envs:
        entries = _read_pool(env).get("wallets", [])
        result[env] = [{k: v for k, v in entry.items() if k not in ("secret_key", "x25519_secret")} for entry in entries]
    return result


def gc_orphaned_assignments(topology: dict[str, Any]) -> list[dict[str, Any]]:
    """Release wallets assigned to (host, service, provider, env) tuples that
    no longer exist in the live topology. Returns the list of released
    entries."""
    live = {
        (i.get("host"), i.get("service"), i.get("provider"), i.get("env"), i.get("worker_index", 1))
        for i in topology.get("workers", [])
    }
    released: list[dict[str, Any]] = []
    for env_name in _all_pool_envs():
        pool = _read_pool(env_name)
        changed = False
        for entry in pool.get("wallets", []):
            if not entry.get("assigned_host"):
                continue
            key = (
                entry["assigned_host"],
                entry["assigned_service"],
                entry["assigned_provider"],
                env_name,
                entry.get("assigned_worker_index", 1),
            )
            if key not in live:
                entry["assigned_host"] = ""
                entry["assigned_service"] = ""
                entry["assigned_provider"] = ""
                entry["assigned_worker_index"] = 0
                entry["assigned_at"] = ""
                entry["released_at"] = _timestamp()
                changed = True
                released.append(entry)
        if changed:
            _write_pool(env_name, pool)
    return released


def _generate_alias(existing_aliases: set[str]) -> str:
    """Adjective-noun alias, e.g. 'affectionate-jet', unique within existing_aliases."""
    for _ in range(200):
        candidate = f"{random.choice(_ALIAS_ADJECTIVES)}-{random.choice(_ALIAS_NOUNS)}"
        if candidate not in existing_aliases:
            return candidate
    # Combinatorial space exhausted (very large pool) -- fall back to a
    # suffixed variant, still guaranteed unique.
    base = f"{random.choice(_ALIAS_ADJECTIVES)}-{random.choice(_ALIAS_NOUNS)}"
    suffix = 2
    candidate = f"{base}-{suffix}"
    while candidate in existing_aliases:
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _matches(entry: dict[str, Any], host: str, service: str, provider: str, worker_index: int = 1) -> bool:
    return (
        entry.get("assigned_host") == host
        and entry.get("assigned_service") == service
        and entry.get("assigned_provider") == provider
        and entry.get("assigned_worker_index", 1) == worker_index
    )
