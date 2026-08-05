from __future__ import annotations

from datetime import datetime
from typing import Any

import flet as ft

from .... import bot_client
from .... import contract as contract_cli
from .... import observer as observer_cli
from .... import scenario as scenario_cli
from ....observer import metrics_room as metrics_room_cli
from ...dialogs import show_info
from ...widgets import copyable_id, status_badge
from ._shared import _no_scenario_overlay, _placeholder_card

# cli/contract/rooms.py's ROOM_STATUS_NAMES value -> status_badge() kind.
_ROOM_STATUS_KIND = {"pending": "neutral", "ready": "info", "active": "success", "closed": "neutral"}


def _fetch_rooms(env: str) -> list[dict[str, Any]] | None:
    """Runs off the UI thread (see refresh_room_tab()'s runner.run() call)
    -- both reads are real network calls (a `sui` CLI devInspect subprocess,
    and an HTTPS request to the observer host's Prometheus query route), not
    local file reads like the rest of this page's refresh() cycle. Returns
    None only when the on-chain read itself fails (no RoomManager
    configured, or devInspect couldn't run) -- a failed/unavailable
    Prometheus read degrades to "participants unknown" per room instead of
    failing the whole tab, since live counts are a nice-to-have on top of
    the authoritative on-chain room list.

    Uses room_occupancy_counts(), not room_participant_counts() -- the
    latter is signaling-only and never counts bots (they connect straight
    to the relay's WS, never touching signaling), which showed as a
    permanent "0 / N" here even with bots actually in the room. See
    query.py's room_occupancy_counts() docstring."""
    rooms = contract_cli.list_active_rooms(env)
    if rooms is None:
        return None
    participant_counts = observer_cli.room_occupancy_counts()
    for room in rooms:
        room_id = str(room.get("room_id", ""))
        room["participants"] = None if participant_counts is None else participant_counts.get(room_id, 0)
    return rooms


def _room_detail_row(label: str, value: ft.Control) -> ft.Row:
    return ft.Row(
        [ft.Container(ft.Text(label, size=12, color=ft.Colors.OUTLINE), width=100), value],
        spacing=8,
    )


def _room_detail_content(room: dict[str, Any], page: ft.Page) -> ft.Control:
    room_id = str(room.get("room_id", ""))
    status_value = str(room.get("status", "unknown"))
    capacity = int(room.get("expected_participants", 0) or 0)
    participants = room.get("participants")
    fill_text = "? / " + str(capacity) if participants is None else f"{participants} / {capacity}"
    creator = str(room.get("creator", ""))
    created_at_ms = int(room.get("created_at", 0) or 0)
    created_at_text = datetime.fromtimestamp(created_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if created_at_ms else "-"

    return ft.Column(
        [
            _room_detail_row("Room ID", copyable_id(room_id, page)),
            _room_detail_row("Status", status_badge(status_value, _ROOM_STATUS_KIND.get(status_value, "neutral"))),
            _room_detail_row("Clients / capacity", ft.Text(fill_text, size=12)),
            _room_detail_row("Creator", copyable_id(creator, page)),
            _room_detail_row("Created at", ft.Text(created_at_text, size=12)),
        ],
        spacing=12,
        tight=True,
    )


def _fmt(value: float | None, unit: str = "", digits: int = 1) -> str:
    return "-" if value is None else f"{round(value, digits)}{unit}"


def _fetch_room_extra(env: str, room_id: str) -> dict[str, Any]:
    """Runs off the UI thread (see _open_room_dialog()'s runner.run() call).
    Fans out across every bot worker in this scenario's env to find which
    ones currently have a session in this room -- cli.bot_client.list_sessions()
    is per-host only, there's no fleet-wide "sessions by room" call, so this
    is the client-side filter+fan-out that's missing upstream."""
    peer_quality = metrics_room_cli.collect_room_peer_quality(room_id)
    identity = metrics_room_cli.collect_room_identity(room_id, env)
    bot_sessions: list[dict[str, Any]] = []
    for worker in scenario_cli._active_workers_for_env(env):
        if worker.get("service") != "bot":
            continue
        host = str(worker.get("host", ""))
        for session in bot_client.list_sessions(host) or []:
            if str(session.get("roomId", "")) == room_id:
                bot_sessions.append({**session, "host": host})
    return {"peer_quality": peer_quality, "identity": identity, "bot_sessions": bot_sessions}


def _relay_controls(extra: dict[str, Any], page: ft.Page) -> list[ft.Control]:
    identity = extra.get("identity") or {}
    peer_quality = (extra.get("peer_quality") or {}).get("peer_quality") or {}
    controls: list[ft.Control] = []

    if identity.get("error"):
        controls.append(ft.Text(f"Relay assignment unavailable: {identity['error']}", size=12, color=ft.Colors.ERROR))
    else:
        assigned_relays = [str(r) for r in (identity.get("assigned_relays") or [])]
        assigned_signaling = identity.get("assigned_signaling")
        if assigned_relays:
            controls.append(
                _room_detail_row(
                    "Assigned relays",
                    ft.Column([copyable_id(relay_id, page) for relay_id in assigned_relays], spacing=4, tight=True),
                )
            )
        else:
            controls.append(_room_detail_row("Assigned relays", ft.Text("not yet assigned", size=12, color=ft.Colors.OUTLINE)))
        controls.append(
            _room_detail_row(
                "Assigned signaling",
                copyable_id(str(assigned_signaling), page) if assigned_signaling else ft.Text("-", size=12),
            )
        )

    if any(v is not None for v in peer_quality.values()):
        controls.append(_room_detail_row("Avg latency", ft.Text(_fmt(peer_quality.get("avg_latency_ms"), " ms"), size=12)))
        controls.append(_room_detail_row("Avg packet loss", ft.Text(_fmt(peer_quality.get("avg_packet_loss")), size=12)))
        controls.append(_room_detail_row("Avg jitter", ft.Text(_fmt(peer_quality.get("avg_jitter_ms"), " ms"), size=12)))
        controls.append(
            _room_detail_row(
                "Bitrate up/down",
                ft.Text(
                    f"{_fmt(peer_quality.get('avg_bitrate_up_kbps'))} / {_fmt(peer_quality.get('avg_bitrate_down_kbps'))} kbps",
                    size=12,
                ),
            )
        )
        controls.append(_room_detail_row("ICE success rate", ft.Text(_fmt(peer_quality.get("ice_success_rate")), size=12)))
    else:
        controls.append(ft.Text("No live peer-quality metrics for this room right now.", size=12, color=ft.Colors.OUTLINE))

    return controls


def _bot_session_row(session: dict[str, Any]) -> ft.Control:
    host = str(session.get("host", ""))
    alias = str(session.get("alias", ""))
    media_mode = str(session.get("mediaMode", ""))
    uptime_ms = int(session.get("uptimeMs", 0) or 0)
    minutes, seconds = divmod(uptime_ms // 1000, 60)

    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=6,
        content=ft.Row(
            [
                ft.Container(ft.Text(alias or host, weight=ft.FontWeight.BOLD, size=12), width=110),
                ft.Text(host, size=11, color=ft.Colors.OUTLINE, expand=True),
                status_badge(media_mode, "info"),
                ft.Text(f"{minutes}m {seconds}s", size=11, color=ft.Colors.OUTLINE),
            ],
            wrap=True,
            spacing=8,
        ),
    )


def _bot_session_controls(sessions: list[dict[str, Any]]) -> list[ft.Control]:
    if not sessions:
        return [ft.Text("No bot sessions currently connected to this room.", size=12, color=ft.Colors.OUTLINE)]
    return [_bot_session_row(session) for session in sessions]


def _open_room_dialog(page: ft.Page, runner, env: str, room: dict[str, Any]) -> None:
    room_id = str(room.get("room_id", ""))
    short_id = room_id if len(room_id) <= 18 else f"{room_id[:8]}…{room_id[-6:]}"

    relay_section = ft.Column(
        [ft.Row([ft.ProgressRing(width=14, height=14, stroke_width=2), ft.Text("Loading relay info…", size=12)], spacing=8)],
        spacing=8,
        tight=True,
    )
    bots_section = ft.Column(
        [ft.Row([ft.ProgressRing(width=14, height=14, stroke_width=2), ft.Text("Loading bot sessions…", size=12)], spacing=8)],
        spacing=8,
        tight=True,
    )

    def render_extra(extra: dict[str, Any] | None) -> None:
        if extra is None:
            relay_section.controls = [ft.Text("Unable to fetch relay info -- see the Activity log.", color=ft.Colors.ERROR, size=12)]
            bots_section.controls = [
                ft.Text("Unable to fetch bot sessions -- see the Activity log.", color=ft.Colors.ERROR, size=12)
            ]
        else:
            relay_section.controls = _relay_controls(extra, page)
            bots_section.controls = _bot_session_controls(extra.get("bot_sessions") or [])
        page.update()

    show_info(
        page,
        f"Room {short_id}",
        ft.Column(
            [
                _room_detail_content(room, page),
                ft.Divider(),
                ft.Text("Relay", size=13, weight=ft.FontWeight.BOLD),
                relay_section,
                ft.Divider(),
                ft.Text("Bots in this room", size=13, weight=ft.FontWeight.BOLD),
                bots_section,
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            tight=True,
        ),
        width=480,
        height=520,
    )
    runner.run(f"room {short_id}: fetch relay/bot detail", _fetch_room_extra, env, room_id, on_done=render_extra)


def _room_card(room: dict[str, Any], page: ft.Page, env: str, runner) -> ft.Control:
    room_id = str(room.get("room_id", ""))
    status_value = str(room.get("status", "unknown"))
    capacity = int(room.get("expected_participants", 0) or 0)
    participants = room.get("participants")
    fill_text = "? / " + str(capacity) if participants is None else f"{participants} / {capacity}"
    over_capacity = isinstance(participants, int) and capacity > 0 and participants > capacity

    return ft.Container(
        width=280,
        padding=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        ink=True,
        on_click=lambda e, r=room: _open_room_dialog(page, runner, env, r),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.MEETING_ROOM, color=ft.Colors.OUTLINE, size=16),
                        ft.Text("Room", weight=ft.FontWeight.BOLD, expand=True),
                        status_badge(status_value, _ROOM_STATUS_KIND.get(status_value, "neutral")),
                    ]
                ),
                copyable_id(room_id, page),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.GROUPS, size=14, color=ft.Colors.ERROR if over_capacity else ft.Colors.OUTLINE),
                        ft.Text(
                            fill_text,
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.ERROR if over_capacity else None,
                        ),
                        ft.Text("clients / capacity", size=11, color=ft.Colors.OUTLINE),
                    ],
                    spacing=6,
                ),
            ],
            spacing=6,
        ),
    )


def refresh_room_tab(room_tab_container: ft.Container, lock: dict | None, page: ft.Page, runner) -> None:
    if lock is None:
        room_tab_container.content = _no_scenario_overlay(
            ft.Column(
                [
                    ft.Text("Rooms", size=13, weight=ft.FontWeight.BOLD),
                    ft.Row([_placeholder_card(), _placeholder_card()], wrap=True, spacing=12, run_spacing=12),
                ],
                spacing=16,
            )
        )
        return

    env = str(lock.get("env", ""))

    room_tab_container.content = ft.Column(
        [
            ft.Row([ft.ProgressRing(width=14, height=14, stroke_width=2), ft.Text("Loading rooms…", size=12)], spacing=8),
        ],
        expand=True,
    )
    page.update()

    def render(rooms: list[dict[str, Any]] | None) -> None:
        if rooms is None:
            room_tab_container.content = ft.Column(
                [
                    ft.Text(
                        "Unable to read rooms from chain -- see the Activity log "
                        "(no RoomManager configured for this env, or `sui` couldn't reach the network).",
                        color=ft.Colors.ERROR,
                    ),
                ],
                expand=True,
            )
        elif not rooms:
            room_tab_container.content = ft.Column(
                [ft.Text("No active rooms right now.", color=ft.Colors.OUTLINE)],
                expand=True,
            )
        else:
            room_tab_container.content = ft.Column(
                [
                    ft.Text("Rooms", size=13, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [_room_card(room, page, env, runner) for room in rooms],
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                spacing=16,
            )
        page.update()

    runner.run(f"room: list active rooms ({env})", _fetch_rooms, env, on_done=render)
