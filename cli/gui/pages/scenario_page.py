from __future__ import annotations

import asyncio
from pathlib import Path

import flet as ft
import flet_charts as fc

from ... import bot_client
from ... import infra as infra_cli
from ... import scenario as scenario_cli
from ..dialogs import confirm, show_info
from ..widgets import copyable_id, provider_icon, section_card, status_badge, status_kind_for
from .infra_page import worker_card

LOCK_STATUS_KIND = {"active": "success", "applying": "info", "failed": "error"}
BOT_MEDIA_MODES = ("listen", "camera", "mic", "both")


def build_scenario_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    status_column = ft.Column(spacing=8)
    workers_column = ft.Column(spacing=8)
    state_chart = ft.Container()
    frontends_row = ft.Row(wrap=True, spacing=8)
    destroy_button = ft.OutlinedButton("Destroy active scenario", icon=ft.Icons.STOP_CIRCLE_OUTLINED)
    scenario_path_field = ft.TextField(
        label="Scenario TOML path",
        hint_text="scenario/example/example.toml",
        width=320,
    )
    # A wrapping Row (not GridView) so each card keeps its own natural height --
    # scenario cards vary a lot (1-4 provider chips, 1-2 line names), and
    # GridView's fixed cross-axis aspect ratio forces every cell to the same
    # height, clipping taller cards.
    gallery_column = ft.Row(wrap=True, spacing=12, run_spacing=12)
    status_tab_container = ft.Container(expand=True)
    bot_tab_container = ft.Container(expand=True)
    monitor_tab_container = ft.Container(expand=True)

    def refresh(_: ft.ControlEvent | None = None) -> None:
        lock = scenario_cli.read_lock()
        if lock is None:
            status_column.controls = [
                ft.Row([status_badge("No active scenario", "neutral")]),
                ft.Text("Apply a scenario file to provision a fleet.", color=ft.Colors.OUTLINE),
            ]
            workers_column.controls = []
            frontends_row.controls = []
            state_chart.content = None
            destroy_button.disabled = True
            refresh_status_tab(None)
            refresh_bot_tab(None)
            refresh_monitor_tab(None)
            page.update()
            return

        env = str(lock.get("env", ""))
        status_value = str(lock.get("status", ""))
        status_column.controls = [
            ft.Row(
                [
                    status_badge(status_value or "unknown", LOCK_STATUS_KIND.get(status_value, "neutral")),
                    ft.Text(str(lock.get("scenario_path")), weight=ft.FontWeight.BOLD, selectable=True, size=13),
                ]
            ),
            ft.Row(
                [
                    _stat("Env", env),
                    _stat("Hash", str(lock.get("scenario_hash", ""))[:18] + "…"),
                    _stat("Applied at", str(lock.get("applied_at", ""))),
                    _stat("Updated at", str(lock.get("updated_at", ""))),
                ],
                wrap=True,
            ),
        ]
        destroy_button.disabled = False

        workers = sorted(
            scenario_cli._active_workers_for_env(env),
            key=lambda r: (str(r.get("host")), str(r.get("service")), int(r.get("worker_index", 1) or 1)),
        )
        state_chart.content = _worker_state_pie(workers)

        if not workers:
            workers_column.controls = [ft.Text("No active workers for this scenario's env.", color=ft.Colors.OUTLINE)]
        else:
            by_host: dict[str, list] = {}
            for worker in workers:
                by_host.setdefault(str(worker.get("host")), []).append(worker)
            host_cards = []
            for host, host_workers in sorted(by_host.items()):
                provider = str(host_workers[0].get("provider", ""))
                host_cards.append(
                    ft.Container(
                        padding=10,
                        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=8,
                        content=ft.Column(
                            [ft.Text(f"{host} ({provider})", weight=ft.FontWeight.BOLD)]
                            + [
                                worker_card(runner, page, provider, host, worker, refresh)
                                for worker in host_workers
                            ],
                            spacing=6,
                        ),
                    )
                )
            workers_column.controls = host_cards

        try:
            scenario_data = scenario_cli.load_scenario(Path(str(lock.get("scenario_path", ""))))
            frontends = scenario_data.get("frontends", [])
        except (ValueError, OSError):
            frontends = []
        frontends_row.controls = (
            [
                ft.Chip(label=ft.Text(f"{fe.get('name')} @ {fe.get('provider')} ({fe.get('object', 'frontend')})"))
                for fe in frontends
            ]
            if frontends
            else [ft.Text("No frontends declared in this scenario.", color=ft.Colors.OUTLINE)]
        )
        refresh_status_tab(lock)
        refresh_bot_tab(lock)
        refresh_monitor_tab(lock)
        page.update()

    def do_destroy(e: ft.ControlEvent) -> None:
        confirm(
            page,
            "Destroy the active scenario?",
            "This kills every worker this scenario owns (real cloud infra teardown) and releases the "
            "scenario lock. Frontends are left untouched.",
            lambda: runner.run(
                "scenario destroy",
                scenario_cli.destroy,
                None,
                trigger=e.control,
                on_done=lambda _r: refresh(),
            ),
        )

    destroy_button.on_click = do_destroy

    def apply_path(path_str: str) -> None:
        path_str = (path_str or "").strip()
        if not path_str:
            runner.log("Enter a scenario TOML path first.")
            return

        def run_apply() -> None:
            runner.run(
                f"scenario apply {path_str}",
                scenario_cli.apply,
                path_str,
                True,
                on_done=lambda _r: refresh(),
            )

        confirm(
            page,
            f"Apply scenario {path_str}?",
            "This is a full declarative reconcile: publishes the contract, publishes frontends, builds/pushes "
            "every worker image, and kills any worker not listed in this file. Only one scenario can be "
            "active at a time.",
            run_apply,
        )

    def do_apply(_: ft.ControlEvent) -> None:
        apply_path(scenario_path_field.value)

    def use_gallery_scenario(path_str: str) -> None:
        scenario_path_field.value = path_str
        page.update()
        apply_path(path_str)

    apply_button = ft.FilledButton("Apply scenario", icon=ft.Icons.UPLOAD_FILE, on_click=do_apply)
    refresh_button = ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=refresh)

    def refresh_gallery(_: ft.ControlEvent | None = None) -> None:
        gallery_column.controls = _build_gallery_cards(use_gallery_scenario)
        page.update()

    gallery_refresh_button = ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Rescan scenario/ directory", on_click=refresh_gallery)

    def open_bot_dialog(worker: dict) -> None:
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

    def refresh_bot_tab(lock: dict | None) -> None:
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
                    [_bot_gallery_card(worker, open_bot_dialog) for worker in bot_workers],
                    wrap=True,
                    spacing=12,
                    run_spacing=12,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        )

    def refresh_status_tab(lock: dict | None) -> None:
        if lock is None:
            status_tab_container.content = _no_scenario_overlay(
                ft.Column(
                    [ft.Text("Active scenario", size=13, weight=ft.FontWeight.BOLD), _placeholder_card(height=110)],
                    spacing=16,
                )
            )
            return
        status_tab_container.content = ft.Column(
            [
                ft.Row([destroy_button, refresh_button]),
                section_card("Active scenario", ft.Icons.LAYERS, status_column),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        )

    def refresh_monitor_tab(lock: dict | None) -> None:
        if lock is None:
            monitor_tab_container.content = _no_scenario_overlay(
                ft.Column(
                    [
                        ft.Text("Workers", size=13, weight=ft.FontWeight.BOLD),
                        ft.Row([_placeholder_card(), _placeholder_card()], wrap=True, spacing=12, run_spacing=12),
                    ],
                    spacing=16,
                )
            )
            return
        monitor_tab_container.content = ft.Column(
            [
                section_card(
                    "Workers",
                    ft.Icons.DNS,
                    ft.Row(
                        [ft.Container(workers_column, expand=True), ft.Container(state_chart, width=220)],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ),
                section_card("Frontends", ft.Icons.WEB, frontends_row),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        )

    gallery_view = ft.Column(
        [
            ft.Row([scenario_path_field, apply_button], wrap=True),
            ft.Row(
                [ft.Text("Scenario gallery", size=13, weight=ft.FontWeight.BOLD), gallery_refresh_button],
            ),
            gallery_column,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=16,
    )

    body = ft.Container(content=status_tab_container, expand=True)
    view_state = {"active": "status"}

    def switch_view(name: str) -> None:
        view_state["active"] = name
        status_tab_button.style = _tab_button_style(name == "status")
        bot_tab_button.style = _tab_button_style(name == "bot")
        monitor_tab_button.style = _tab_button_style(name == "monitor")
        gallery_tab_button.style = _tab_button_style(name == "gallery")
        body.content = {
            "status": status_tab_container,
            "bot": bot_tab_container,
            "monitor": monitor_tab_container,
            "gallery": gallery_view,
        }[name]
        page.update()

    status_tab_button = ft.TextButton(
        "Status",
        icon=ft.Icons.LAYERS,
        on_click=lambda e: switch_view("status"),
        style=_tab_button_style(True),
    )
    bot_tab_button = ft.TextButton(
        "Bot",
        icon=ft.Icons.SMART_TOY,
        on_click=lambda e: switch_view("bot"),
        style=_tab_button_style(False),
    )
    monitor_tab_button = ft.TextButton(
        "Monitor",
        icon=ft.Icons.MONITOR_HEART,
        on_click=lambda e: switch_view("monitor"),
        style=_tab_button_style(False),
    )
    gallery_tab_button = ft.TextButton(
        "Gallery",
        icon=ft.Icons.GRID_VIEW,
        on_click=lambda e: switch_view("gallery"),
        style=_tab_button_style(False),
    )

    async def poll_forever() -> None:
        while True:
            await asyncio.sleep(30)
            refresh()

    page.run_task(poll_forever)

    refresh()
    refresh_gallery()

    return ft.Container(
        padding=20,
        content=ft.Column(
            [
                ft.Row(
                    [status_tab_button, bot_tab_button, monitor_tab_button, gallery_tab_button],
                    spacing=4,
                ),
                ft.Divider(height=1),
                body,
            ],
            expand=True,
            spacing=12,
        ),
    )


def _tab_button_style(is_active: bool) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=ft.Colors.PRIMARY_CONTAINER if is_active else None,
        color=ft.Colors.ON_PRIMARY_CONTAINER if is_active else ft.Colors.OUTLINE,
    )


def _build_gallery_cards(on_apply) -> list[ft.Control]:
    if not scenario_cli.SCENARIO_DIR.exists():
        return [ft.Text("No scenario/ directory found.", color=ft.Colors.OUTLINE)]
    paths = sorted(scenario_cli.SCENARIO_DIR.rglob("*.toml"))
    if not paths:
        return [ft.Text("No scenario TOML files found under scenario/.", color=ft.Colors.OUTLINE)]
    return [_scenario_gallery_card(path, on_apply) for path in paths]


def _scenario_gallery_card(path: Path, on_apply) -> ft.Control:
    try:
        rel = str(path.relative_to(scenario_cli.SCENARIO_DIR.parent))
    except ValueError:
        rel = str(path)

    try:
        data = scenario_cli.load_scenario(path)
    except (ValueError, OSError) as exc:
        return ft.Container(
            width=340,
            padding=12,
            border=ft.Border.all(1, ft.Colors.ERROR),
            border_radius=8,
            content=ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.ERROR), ft.Text(path.name, weight=ft.FontWeight.BOLD)]),
                    ft.Text(rel, size=11, color=ft.Colors.OUTLINE, selectable=True),
                    ft.Text(str(exc), size=12, color=ft.Colors.ERROR),
                ],
                spacing=4,
            ),
        )

    providers = sorted({w.get("provider", "") for w in data["workers"]} | {f.get("provider", "") for f in data["frontends"]})
    host_count = len({w.get("host", "") for w in data["workers"]})
    worker_count = len(data["workers"])
    frontend_count = len(data["frontends"])

    return ft.Container(
        width=340,
        padding=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LAYERS, size=18),
                        ft.Text(data["name"], weight=ft.FontWeight.BOLD, size=14, expand=True),
                        status_badge(data["env"], "info"),
                    ]
                ),
                ft.Text(rel, size=11, color=ft.Colors.OUTLINE, selectable=True),
                ft.Row([ft.Chip(label=ft.Text(p, size=11)) for p in providers if p], wrap=True, spacing=4),
                ft.Text(
                    f"{worker_count} worker(s) on {host_count} host(s) · {frontend_count} frontend(s)",
                    size=12,
                    color=ft.Colors.OUTLINE,
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use this scenario",
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=lambda e, p=rel: on_apply(p),
                        )
                    ]
                ),
            ],
            spacing=6,
        ),
    )


def _stat(label: str, value: str) -> ft.Container:
    return ft.Container(
        padding=8,
        border_radius=6,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        content=ft.Column([ft.Text(label, size=10, color=ft.Colors.OUTLINE), ft.Text(value, size=12)], spacing=2, tight=True),
        width=170,
    )


def _worker_state_pie(workers: list[dict]) -> ft.Control:
    if not workers:
        return ft.Container()
    counts: dict[str, int] = {}
    for worker in workers:
        kind = status_kind_for(str(worker.get("last_status") or worker.get("desired_state") or ""))
        counts[kind] = counts.get(kind, 0) + 1
    colors = {"success": ft.Colors.GREEN, "warning": ft.Colors.ORANGE, "error": ft.Colors.RED, "neutral": ft.Colors.GREY, "info": ft.Colors.BLUE}
    sections = [
        fc.PieChartSection(
            value=count,
            title=f"{kind}\n{count}",
            title_style=ft.TextStyle(size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            color=colors.get(kind, ft.Colors.GREY),
            radius=60,
        )
        for kind, count in sorted(counts.items())
    ]
    return ft.Column(
        [
            ft.Text("Worker state", size=12, weight=ft.FontWeight.BOLD),
            fc.PieChart(sections=sections, sections_space=1, center_space_radius=24, height=170),
        ]
    )


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


def _placeholder_card(width: int = 280, height: int = 90) -> ft.Control:
    return ft.Container(
        width=width,
        height=height,
        padding=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )


def _no_scenario_overlay(blurred_content: ft.Control) -> ft.Control:
    """Shared "no scenario running" gate for the Status/Bot/Monitor tabs --
    a dimmed/blurred placeholder backdrop with a centered alert on top."""
    return ft.Stack(
        [
            ft.Container(expand=True, blur=ft.Blur(18, 18), content=blurred_content),
            ft.Container(
                alignment=ft.Alignment.CENTER,
                expand=True,
                content=ft.Container(
                    padding=20,
                    border_radius=10,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.LOCK_OUTLINE, size=32, color=ft.Colors.OUTLINE),
                            ft.Text("No scenario running", size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Apply a scenario from the Gallery tab to manage its bots.",
                                size=12,
                                color=ft.Colors.OUTLINE,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                        tight=True,
                    ),
                ),
            ),
        ],
        expand=True,
    )
