"""Manage local (non-fleet) apps/bot dev-server sessions -- `vidctl utils
bot start/stop/refresh/list`. Lets an operator run one or more bot
control-server processes on their own machine, each creating+streaming into
its own room against the currently-deployed devnet contract, without
hand-running `pnpm dev` + `curl` every time. Each session is addressed by a
small integer id (starting at 1) so several can run side by side.

State lives in runtime/local_bots.toml (gitignored, same as every other
runtime/*.toml file) -- one [[bots]] row per known id, past or present.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import tomllib
import urllib.error
import urllib.request

from . import bot_client, context, infra
from .wallet import chain_ops

BASE_PORT = 8095
# apps/bot also binds a second, independent port for its own Prometheus
# metrics server (BOT_METRICS_PORT, default 8096 -- see config.ts/index.ts)
# that isn't derived from PORT, so two local sessions on different PORTs
# still collide there unless it's allocated per-id too. Kept far from the
# BASE_PORT range so it never overlaps a control port even with many ids.
METRICS_BASE_PORT = 9095
BOT_APP_DIR = context.WORKER_DIR / "apps" / "bot"
HEALTHZ_TIMEOUT_SECONDS = 20.0
STOP_GRACE_SECONDS = 5.0
# Below this, auto-request faucet gas before spawning -- a local bot session
# submits several txs per run (register, escrow, room create/join), so this
# is deliberately higher than wallet/chain_ops.py's fleet-wallet MIN_GAS_MIST
# (2 SUI) to avoid re-fauceting on almost every session.
LOCAL_BOT_MIN_GAS_MIST = 9_000_000_000  # 9 SUI


@dataclass
class LocalBotSession:
    id: int
    pid: int
    port: int
    bot_id: str
    room_id: str
    join_url: str
    started_at: str
    log_path: str


def _port_for(bot_local_id: int) -> int:
    return BASE_PORT + (bot_local_id - 1)


def _metrics_port_for(bot_local_id: int) -> int:
    return METRICS_BASE_PORT + (bot_local_id - 1)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else -- still "alive" for
        # our purposes (we just can't necessarily signal it later).
        return True
    return True


def _terminate_process_tree(pid: int) -> None:
    """SIGTERM (then SIGKILL if still alive after the grace period) the
    WHOLE process group `pid` leads, not just `pid` itself.

    `_spawn_process` launches `pnpm --filter bot dev` via
    `context.run_detached(..., start_new_session=True)`, which makes that
    pnpm pid both the session leader AND the process group leader --
    `pnpm dev` -> `tsx watch` -> the actual `node src/index.ts` process all
    inherit that same group. Signaling only the tracked pid (a plain
    `os.kill`) leaves the tsx/node descendants running as orphans once pnpm
    exits -- confirmed live: a stopped/crashed session left its `tsx watch`
    and `node` children bound to the control port for hours. `os.killpg`
    reaches the whole tree in one shot."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# Matches the exact argv `_spawn_process` launches (`pnpm --filter bot dev`,
# cwd=WORKER_DIR) plus its `tsx watch`/`node src/index.ts` descendants under
# apps/bot -- broad enough to catch a session's process tree even when the
# top-level pnpm pid already died but a child outlived it (e.g. SIGTERM only
# reached pnpm, not the group -- see _terminate_process_tree's doc for why
# that used to happen).
_ORPHAN_BOT_PATTERN = re.compile(
    r"pnpm\s+--filter\s+bot\s+dev|apps/bot/.*tsx.*watch|apps/bot\b.*src/index\.ts"
)


def _find_bot_process_pids() -> set[int]:
    """Every currently-running process (any host user session, not just ones
    `runtime/local_bots.toml` happens to still be tracking) whose command
    line matches a local bot dev-server -- see `_ORPHAN_BOT_PATTERN`. Used by
    `stop_all()` to sweep up sessions that predate a contract redeploy (their
    baked-in env is stale -- see the local-bot-vs-scenario-destroy
    investigation this accompanies) or that `stop()` failed to fully reap
    before the group-kill fix above existed."""
    try:
        proc = subprocess.run(
            ["ps", "-Ao", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, command = line.partition(" ")
        if not _ORPHAN_BOT_PATTERN.search(command):
            continue
        try:
            pids.add(int(pid_str))
        except ValueError:
            continue
    return pids


def read_sessions() -> dict[int, LocalBotSession]:
    if not context.RUNTIME_LOCAL_BOTS_TOML.exists():
        return {}
    try:
        data = tomllib.loads(context.RUNTIME_LOCAL_BOTS_TOML.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    result: dict[int, LocalBotSession] = {}
    for row in data.get("bots", []):
        if not isinstance(row, dict) or "id" not in row:
            continue
        try:
            bot_local_id = int(row["id"])
        except (TypeError, ValueError):
            continue
        result[bot_local_id] = LocalBotSession(
            id=bot_local_id,
            pid=int(row.get("pid", 0)),
            port=int(row.get("port", 0)),
            bot_id=str(row.get("bot_id", "")),
            room_id=str(row.get("room_id", "")),
            join_url=str(row.get("join_url", "")),
            started_at=str(row.get("started_at", "")),
            log_path=str(row.get("log_path", "")),
        )
    return result


def _write_sessions(sessions: dict[int, LocalBotSession]) -> None:
    context.RUNTIME_LOCAL_BOTS_TOML.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# generated by vidctl utils bot", ""]
    for bot_local_id in sorted(sessions):
        session = sessions[bot_local_id]
        lines.append("[[bots]]")
        lines.append(f"id = {session.id}")
        lines.append(f"pid = {session.pid}")
        lines.append(f"port = {session.port}")
        lines.append(f"bot_id = {infra.toml_value(session.bot_id)}")
        lines.append(f"room_id = {infra.toml_value(session.room_id)}")
        lines.append(f"join_url = {infra.toml_value(session.join_url)}")
        lines.append(f"started_at = {infra.toml_value(session.started_at)}")
        lines.append(f"log_path = {infra.toml_value(session.log_path)}")
        lines.append("")
    context.RUNTIME_LOCAL_BOTS_TOML.write_text("\n".join(lines), encoding="utf-8")


def _wait_for_healthz(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    return False


def _ensure_gas_funded(session_env: dict[str, str]) -> None:
    """Best-effort auto-faucet for the bot's own .env-configured wallet: a
    session submits several on-chain txs (register, escrow, room create/join)
    right after the healthz check passes, and each one fails outright with
    "No valid gas coins found for the transaction" if the wallet runs dry --
    confirmed live, this surfaces as a 502 from POST /bots well after the
    process already reports healthy, so there's no earlier natural check
    point than right before spawn. Only devnet/testnet have a faucet (mirrors
    wallet/chain_ops.py's FAUCET_NETWORKS); mainnet/localnet/custom-RPC
    SUI_NETWORK values are left alone. Any lookup/request failure is
    non-fatal -- the session still starts and fails with the original
    gas-coins error if it turns out to actually be needed."""
    private_key = session_env.get("PRIVATE_KEY", "")
    network = session_env.get("SUI_NETWORK", "")
    if not private_key or network not in chain_ops.FAUCET_NETWORKS:
        return
    try:
        address = chain_ops.sui_address_from_private_key(private_key)
        balance = chain_ops.current_balance_mist(address)
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"Warning: could not check wallet balance for the bot's PRIVATE_KEY: {exc}")
        return
    if balance >= LOCAL_BOT_MIN_GAS_MIST:
        return

    from . import contract

    code = contract.ensure_active_sui_env(network)
    if code != 0:
        print(f"Warning: could not switch sui client to {network}; skipping faucet request.")
        return
    print(
        f"Wallet {address} balance {balance / 1_000_000_000:.2f} SUI is below the "
        f"{LOCAL_BOT_MIN_GAS_MIST / 1_000_000_000:.0f} SUI threshold -- requesting faucet gas..."
    )
    if context.run(["sui", "client", "faucet", "--address", address]) != 0:
        print(f"Warning: faucet request failed for {address}.")


def _spawn_process(bot_local_id: int) -> tuple[int, int, Path]:
    """Spawn a fresh apps/bot dev-server process for this id. Returns
    (pid, port, log_path) -- caller waits on /healthz and records the
    session; shared by start() (which then creates a brand-new room) and
    refresh() (which rejoins a previously-recorded one instead)."""
    port = _port_for(bot_local_id)
    session_env = dict(os.environ)
    session_env.update(context.read_env_file(BOT_APP_DIR / ".env"))
    session_env["PORT"] = str(port)
    session_env["BOT_METRICS_PORT"] = str(_metrics_port_for(bot_local_id))

    _ensure_gas_funded(session_env)

    log_path = context.RUNTIME_LOCAL_BOTS_LOG_DIR / f"{bot_local_id}.log"
    # cwd=WORKER_DIR (pnpm workspace root), not apps/bot -- `pnpm --filter
    # bot dev` needs the full workspace to resolve @dvconf/shared etc.,
    # same convention DOCKER_SERVICES/apps' build context already uses
    # (see context.py's WORKER_DIR comment).
    pid = context.run_detached(
        ["pnpm", "--filter", "bot", "dev"], cwd=context.WORKER_DIR, env=session_env, log_path=log_path
    )
    return pid, port, log_path


def start(bot_local_id: int) -> int:
    sessions = read_sessions()
    existing = sessions.get(bot_local_id)
    if existing is not None and _pid_alive(existing.pid):
        print(
            f"bot {bot_local_id}: already running (pid {existing.pid}, port {existing.port}) "
            "-- stop it first."
        )
        return 1

    env_path = BOT_APP_DIR / ".env"
    if not env_path.exists():
        print(
            f"bot {bot_local_id}: {env_path} does not exist -- "
            "`cp .env.example .env` in services/worker/apps/bot and fill it in first "
            "(PRIVATE_KEY, contract object IDs, CLIENT_URL)."
        )
        return 1

    pid, port, log_path = _spawn_process(bot_local_id)

    print(f"bot {bot_local_id}: started pid {pid} on port {port}, waiting for healthz...")
    if not _wait_for_healthz(port, HEALTHZ_TIMEOUT_SECONDS):
        print(
            f"bot {bot_local_id}: did not become healthy within {HEALTHZ_TIMEOUT_SECONDS:.0f}s "
            f"-- check {log_path}"
        )
        # Record the pid even on failure -- otherwise a hung (not crashed)
        # process leaks untracked, with no `vidctl utils bot stop <id>` able
        # to find and kill it (see the room-creation-failure branch below,
        # same reasoning).
        sessions[bot_local_id] = LocalBotSession(
            id=bot_local_id,
            pid=pid,
            port=port,
            bot_id="",
            room_id="",
            join_url="",
            started_at=infra.timestamp(),
            log_path=str(log_path),
        )
        _write_sessions(sessions)
        return 1

    result = bot_client.create_room_local(port, media_mode="both")
    if result is None:
        print(
            f"bot {bot_local_id}: process is up (pid {pid}, port {port}) but room creation "
            f"failed -- check {log_path}. Run `vidctl utils bot stop {bot_local_id}` to clean up."
        )
        sessions[bot_local_id] = LocalBotSession(
            id=bot_local_id,
            pid=pid,
            port=port,
            bot_id="",
            room_id="",
            join_url="",
            started_at=infra.timestamp(),
            log_path=str(log_path),
        )
        _write_sessions(sessions)
        return 1

    session = LocalBotSession(
        id=bot_local_id,
        pid=pid,
        port=port,
        bot_id=str(result.get("botId", "")),
        room_id=str(result.get("roomId", "")),
        join_url=str(result.get("joinUrl", "")),
        started_at=infra.timestamp(),
        log_path=str(log_path),
    )
    sessions[bot_local_id] = session
    _write_sessions(sessions)

    print(f"bot {bot_local_id}: room {session.room_id}")
    print(f"bot {bot_local_id}: join at {session.join_url}")
    return 0


def refresh(bot_local_id: int) -> int:
    """Revive a crashed local bot session: spawn a fresh apps/bot process
    for this id (like start()), but REJOIN the room_id it already had
    instead of creating a brand-new one -- avoids a fresh escrow/room
    creation tx for a room that's still open on-chain.

    Only meaningful when this id's session record still exists with a
    known room_id but its pid is no longer alive -- i.e. the dev-server
    process crashed or the machine restarted without a clean `vidctl
    utils bot stop <id>` first (stop() deletes the session record,
    including its room_id, so there is nothing left to rejoin once that
    happens)."""
    sessions = read_sessions()
    existing = sessions.get(bot_local_id)
    if existing is None:
        print(
            f"bot {bot_local_id}: no known session -- nothing to refresh. "
            f"Run `vidctl utils bot start {bot_local_id}` instead."
        )
        return 1
    if _pid_alive(existing.pid):
        print(
            f"bot {bot_local_id}: already running (pid {existing.pid}, port {existing.port}) "
            "-- nothing to refresh."
        )
        return 1
    if not existing.room_id:
        print(
            f"bot {bot_local_id}: no room recorded for this session (its last start/refresh "
            f"never got past room join) -- run `vidctl utils bot start {bot_local_id}` instead."
        )
        return 1

    env_path = BOT_APP_DIR / ".env"
    if not env_path.exists():
        print(
            f"bot {bot_local_id}: {env_path} does not exist -- "
            "`cp .env.example .env` in services/worker/apps/bot and fill it in first "
            "(PRIVATE_KEY, contract object IDs, CLIENT_URL)."
        )
        return 1

    pid, port, log_path = _spawn_process(bot_local_id)

    print(f"bot {bot_local_id}: restarted pid {pid} on port {port}, waiting for healthz...")
    if not _wait_for_healthz(port, HEALTHZ_TIMEOUT_SECONDS):
        print(
            f"bot {bot_local_id}: did not become healthy within {HEALTHZ_TIMEOUT_SECONDS:.0f}s "
            f"-- check {log_path}"
        )
        # Keep the OLD room_id/join_url on record even though this attempt
        # failed -- otherwise a later `refresh` has nothing left to rejoin
        # (same "don't leak the one thing that made refresh useful" reasoning
        # as the room-join-failure branch below).
        sessions[bot_local_id] = LocalBotSession(
            id=bot_local_id,
            pid=pid,
            port=port,
            bot_id="",
            room_id=existing.room_id,
            join_url=existing.join_url,
            started_at=infra.timestamp(),
            log_path=str(log_path),
        )
        _write_sessions(sessions)
        return 1

    result = bot_client.join_room_local(port, existing.room_id, media_mode="both")
    if result is None:
        print(
            f"bot {bot_local_id}: process is up (pid {pid}, port {port}) but rejoining room "
            f"{existing.room_id} failed -- check {log_path}. Run `vidctl utils bot stop {bot_local_id}` "
            "to clean up, or `refresh` again."
        )
        sessions[bot_local_id] = LocalBotSession(
            id=bot_local_id,
            pid=pid,
            port=port,
            bot_id="",
            room_id=existing.room_id,
            join_url=existing.join_url,
            started_at=infra.timestamp(),
            log_path=str(log_path),
        )
        _write_sessions(sessions)
        return 1

    session = LocalBotSession(
        id=bot_local_id,
        pid=pid,
        port=port,
        bot_id=str(result.get("botId", "")),
        room_id=str(result.get("roomId", existing.room_id)),
        join_url=str(result.get("joinUrl", existing.join_url)),
        started_at=infra.timestamp(),
        log_path=str(log_path),
    )
    sessions[bot_local_id] = session
    _write_sessions(sessions)

    print(f"bot {bot_local_id}: rejoined room {session.room_id}")
    print(f"bot {bot_local_id}: join at {session.join_url}")
    return 0


def stop(bot_local_id: int) -> int:
    sessions = read_sessions()
    session = sessions.get(bot_local_id)
    if session is None:
        print(f"bot {bot_local_id}: no known session.")
        return 1

    if session.bot_id:
        result = bot_client.delete_room_local(session.port, session.bot_id)
        if result is None:
            print(f"bot {bot_local_id}: DELETE /bots/{session.bot_id} failed (continuing anyway).")

    if _pid_alive(session.pid):
        _terminate_process_tree(session.pid)

    del sessions[bot_local_id]
    _write_sessions(sessions)
    print(f"bot {bot_local_id}: stopped.")
    return 0


def stop_all() -> int:
    """Stop every local bot session -- tracked (`runtime/local_bots.toml`)
    AND untracked/orphaned (see `_find_bot_process_pids`). Used by `vidctl
    scenario destroy` so a redeploy never leaves a bot process running
    against contract addresses the destroyed scenario just tore down (a
    long-lived `tsx watch` process never reloads `.env` on its own -- see
    the local-bot-vs-scenario-destroy investigation this accompanies)."""
    sessions = read_sessions()
    stopped_ids: list[int] = []
    for bot_local_id in sorted(sessions):
        if stop(bot_local_id) == 0:
            stopped_ids.append(bot_local_id)

    # A second, pid-based sweep -- catches sessions `runtime/local_bots.toml`
    # never recorded (e.g. a hand-started `pnpm --filter bot dev`) and any
    # process the tracked-session pass above didn't fully reap.
    orphan_pids = _find_bot_process_pids()
    reaped_orphans = 0
    for pid in sorted(orphan_pids):
        if not _pid_alive(pid):
            continue
        _terminate_process_tree(pid)
        reaped_orphans += 1

    if not stopped_ids and reaped_orphans == 0:
        print("No local bot sessions (tracked or orphaned) found.")
    else:
        print(
            f"Stopped {len(stopped_ids)} tracked bot session(s)"
            + (f" ({', '.join(str(i) for i in stopped_ids)})" if stopped_ids else "")
            + f" and {reaped_orphans} orphaned bot process(es)."
        )
    return 0


def _tail_lines(path: Path, lines: int) -> list[str]:
    """Last `lines` lines of `path`, read in fixed-size chunks from the end
    so an arbitrarily large log file is never fully loaded into memory."""
    chunk_size = 8192
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        remaining = f.tell()
        blocks: list[bytes] = []
        newline_count = 0
        while remaining > 0 and newline_count <= lines:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            block = f.read(read_size)
            newline_count += block.count(b"\n")
            blocks.append(block)
    text = b"".join(reversed(blocks)).decode("utf-8", errors="replace")
    return text.splitlines()[-lines:]


def log(bot_local_id: int, lines: int = 100, follow: bool = False) -> int:
    sessions = read_sessions()
    session = sessions.get(bot_local_id)
    if session is None:
        print(f"bot {bot_local_id}: no known session.")
        return 1

    log_path = Path(session.log_path) if session.log_path else None
    if log_path is None or not log_path.exists():
        print(f"bot {bot_local_id}: no log file found (expected {log_path or '<unset>'}).")
        return 1

    if follow:
        # Shell out to `tail -f` -- blocks until the caller Ctrl-C's, same UX
        # as `docker logs -f`. Prints the same trailing window first via `-n`
        # so `--follow` doesn't start from a blank screen.
        try:
            return subprocess.call(["tail", "-n", str(lines), "-f", str(log_path)])
        except KeyboardInterrupt:
            return 0

    for line in _tail_lines(log_path, lines):
        print(line)
    return 0


def list_bots() -> int:
    sessions = read_sessions()
    if not sessions:
        print("No local bot sessions.")
        return 0

    print(f"{'ID':<4}{'STATUS':<10}{'PORT':<7}{'ROOM ID':<22}{'JOIN URL'}")
    for bot_local_id in sorted(sessions):
        session = sessions[bot_local_id]
        status = "running" if _pid_alive(session.pid) else "dead"
        room_display = (session.room_id[:18] + "..") if len(session.room_id) > 20 else session.room_id
        print(
            f"{session.id:<4}{status:<10}{session.port:<7}{room_display:<22}{session.join_url}"
        )
    return 0
