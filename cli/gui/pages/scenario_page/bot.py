from __future__ import annotations

import flet as ft

from .... import bot_client
from .... import infra as infra_cli
from .... import scenario as scenario_cli
from ...dialogs import confirm, show_info
from ...widgets import copyable_id, provider_icon, status_badge, status_kind_for
from ._shared import _no_scenario_overlay, _placeholder_card

BOT_MEDIA_MODES = ("listen", "camera", "mic", "both")


def _bot_gallery_card(worker: dict, on_click) -> ft.Control:
    host = str(worker.get("host", ""))
    provider = str(worker.get("provider", ""))
    worker_index = int(worker.get("worker_index", 1) or 1)
    label = "bot" if worker_index == 1 else f"bot-{worker_index}"
    status_value = str(worker.get("last_status") or worker.get("desired_state") or "unknown")
    address_resolved = bool(infra_cli.host_address(host))

    return ft.Container(
        width=280,
        padding=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        ink=address_resolved,
        on_click=(lambda e, w=worker: on_click(w)) if address_resolved else None,
        content=ft.Column(
            [
                ft.Row(
                    [
                        provider_icon(provider),
                        ft.Text(label, weight=ft.FontWeight.BOLD, expand=True),
                        status_badge(status_value, status_kind_for(status_value)),
                    ]
                ),
                ft.Text(host, size=12, color=ft.Colors.OUTLINE, selectable=True),
                ft.Text(
                    "Click to manage sessions" if address_resolved else "Host address unresolved -- run infra inventory first.",
                    size=11,
                    color=ft.Colors.OUTLINE if address_resolved else ft.Colors.ERROR,
                ),
            ],
            spacing=6,
        ),
    )


def _session_row(session: dict, page: ft.Page) -> ft.Control:
    alias = str(session.get("alias", ""))
    room_id = str(session.get("roomId", ""))
    media_mode = str(session.get("mediaMode", ""))
    uptime_ms = int(session.get("uptimeMs", 0) or 0)
    minutes, seconds = divmod(uptime_ms // 1000, 60)

    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=6,
        content=ft.Row(
            [
                ft.Container(ft.Text(alias, weight=ft.FontWeight.BOLD, size=12), width=110),
                ft.Container(copyable_id(room_id, page), width=170),
                status_badge(media_mode, "info"),
                ft.Text(f"{minutes}m {seconds}s", size=11, color=ft.Colors.OUTLINE),
            ],
            wrap=True,
            spacing=8,
        ),
    )


def open_bot_dialog(page: ft.Page, runner, worker: dict) -> None:
    host = str(worker.get("host", ""))
    room_id_field = ft.TextField(label="Room ID", width=260)
    media_mode_dropdown = ft.Dropdown(
        label="Media mode",
        value="listen",
        width=160,
        options=[ft.dropdown.Option(mode) for mode in BOT_MEDIA_MODES],
    )
    sessions_column = ft.Column(spacing=8, tight=True)

    def render_sessions(sessions: object) -> None:
        if sessions is None:
            sessions_column.controls = [
                ft.Text("Unable to reach this bot's control API -- see the Activity log.", color=ft.Colors.ERROR, size=12)
            ]
        elif not sessions:
            sessions_column.controls = [ft.Text("No active sessions.", color=ft.Colors.OUTLINE, size=12)]
        else:
            sessions_column.controls = [_session_row(session, page) for session in sessions]
        page.update()

    def do_refresh_sessions() -> None:
        runner.run(f"bot {host}: list sessions", bot_client.list_sessions, host, on_done=render_sessions)

    def do_join(e: ft.ControlEvent) -> None:
        room_id = (room_id_field.value or "").strip()
        if not room_id:
            runner.log("Enter a room ID first.")
            return
        media_mode = media_mode_dropdown.value or "listen"

        def run_join() -> None:
            def on_done(result: object) -> None:
                if result is None:
                    runner.log(f"bot {host}: join room {room_id} failed -- see the Activity log.")
                else:
                    room_id_field.value = ""
                do_refresh_sessions()

            runner.run(
                f"bot {host}: join room {room_id}",
                bot_client.join_room,
                host,
                room_id,
                media_mode,
                trigger=e.control,
                on_done=on_done,
            )

        confirm(
            page,
            f"Join room {room_id}?",
            f"This makes the bot on {host} join a real room -- it spends real gas and starts a real "
            "ffmpeg/mediasoup session on that worker. If it's already in this room, this starts an "
            "additional session (that's expected -- a bot can be in the same room twice).",
            run_join,
        )

    join_button = ft.FilledButton("Join room", icon=ft.Icons.LOGIN, on_click=do_join)

    show_info(
        page,
        f"Bot @ {host}",
        ft.Column(
            [
                ft.Text("Active sessions", size=13, weight=ft.FontWeight.BOLD),
                sessions_column,
                ft.Divider(),
                ft.Text("Join a room", size=13, weight=ft.FontWeight.BOLD),
                ft.Row([room_id_field, media_mode_dropdown], wrap=True),
                ft.Row([join_button]),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            tight=True,
        ),
        width=520,
        height=480,
    )
    sessions_column.controls = [
        ft.Row([ft.ProgressRing(width=14, height=14, stroke_width=2), ft.Text("Loading sessions…", size=12)], spacing=8)
    ]
    do_refresh_sessions()


def refresh_bot_tab(bot_tab_container: ft.Container, lock: dict | None, page: ft.Page, runner) -> None:
    if lock is None:
        bot_tab_container.content = _no_scenario_overlay(
            ft.Column(
                [
                    ft.Text("Bot workers", size=13, weight=ft.FontWeight.BOLD),
                    ft.Row([_placeholder_card(), _placeholder_card()], wrap=True, spacing=12, run_spacing=12),
                ],
                spacing=16,
            )
        )
        return
    env = str(lock.get("env", ""))
    bot_workers = sorted(
        (w for w in scenario_cli._active_workers_for_env(env) if w.get("service") == "bot"),
        key=lambda r: (str(r.get("host")), int(r.get("worker_index", 1) or 1)),
    )
    if not bot_workers:
        bot_tab_container.content = ft.Column(
            [ft.Text("This scenario has no bot workers.", color=ft.Colors.OUTLINE)],
            expand=True,
        )
        return
    bot_tab_container.content = ft.Column(
        [
            ft.Text("Bot workers", size=13, weight=ft.FontWeight.BOLD),
            ft.Row(
                [_bot_gallery_card(worker, lambda w: open_bot_dialog(page, runner, w)) for worker in bot_workers],
                wrap=True,
                spacing=12,
                run_spacing=12,
            ),
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=16,
    )
