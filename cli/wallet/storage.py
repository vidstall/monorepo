from __future__ import annotations

from typing import Any

from ..context import RUNTIME_WALLET_TOML, WALLET_SECRETS_DIR, wallet_secrets_path


def _read_pool(env_name: str) -> dict[str, Any]:
    """Read secrets/wallets/<env>.toml (private store, has secrets)."""
    import tomllib

    path = wallet_secrets_path(env_name)
    if not path.exists():
        return {"wallets": []}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data.setdefault("wallets", [])
    return data


def _write_pool(env_name: str, pool: dict[str, Any]) -> None:
    """Write secrets/wallets/<env>.toml, chmod 0o600, then refresh the public view."""
    from ..infra import toml_value

    path = wallet_secrets_path(env_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in pool.get("wallets", []):
        lines.append("[[wallets]]")
        for key, value in entry.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)
    _refresh_public_view()


def _all_pool_envs() -> list[str]:
    """Every env with a pool file on disk, e.g. for the public-view rebuild."""
    if not WALLET_SECRETS_DIR.exists():
        return []
    return sorted(path.stem for path in WALLET_SECRETS_DIR.glob("*.toml"))


def _refresh_public_view() -> None:
    """Rebuild runtime/wallet.toml (no secrets) from every secrets/wallets/*.toml."""
    from ..infra import toml_value

    lines: list[str] = []
    stats: dict[str, dict[str, int]] = {}
    for env_name in _all_pool_envs():
        entries = _read_pool(env_name).get("wallets", [])
        free = sum(1 for entry in entries if not entry.get("assigned_host"))
        stats[env_name] = {"total": len(entries), "free": free, "assigned": len(entries) - free}
        for entry in entries:
            lines.append("[[wallets]]")
            public_fields = {
                "id": entry.get("id", ""),
                "alias": entry.get("alias", ""),
                "env": env_name,
                "address": entry.get("address", ""),
                "assigned_host": entry.get("assigned_host", ""),
                "assigned_service": entry.get("assigned_service", ""),
                "assigned_provider": entry.get("assigned_provider", ""),
                "assigned_at": entry.get("assigned_at", ""),
                "last_balance_mist": entry.get("last_balance_mist", 0),
                "registered_role": entry.get("registered_role", ""),
            }
            for key, value in public_fields.items():
                lines.append(f"{key} = {toml_value(value)}")
            lines.append("")
    for env_name, env_stats in stats.items():
        lines.append(f"[stats.{env_name}]")
        for key, value in env_stats.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    RUNTIME_WALLET_TOML.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_WALLET_TOML.write_text("\n".join(lines), encoding="utf-8")


def _timestamp() -> str:
    from ..infra import timestamp

    return timestamp()
