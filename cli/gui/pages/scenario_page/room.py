from __future__ import annotations

from typing import Any

import flet as ft

from .... import contract as contract_cli
from .... import observer as observer_cli
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
    the authoritative on-chain room list."""
    rooms = contract_cli.list_active_rooms(env)
    if rooms is None:
        return None
    participant_counts = observer_cli.room_participant_counts()
    for room in rooms:
        room_id = str(room.get("room_id", ""))
        room["participants"] = None if participant_counts is None else participant_counts.get(room_id, 0)
    return rooms


def _room_card(room: dict[str, Any], page: ft.Page) -> ft.Control:
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
                        [_room_card(room, page) for room in rooms],
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
