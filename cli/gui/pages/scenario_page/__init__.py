from __future__ import annotations

import asyncio
from pathlib import Path

import flet as ft

from .... import scenario as scenario_cli
from ...dialogs import confirm
from ...widgets import section_card, status_badge
from ..infra_page.worker_card import worker_card
from ._shared import LOCK_STATUS_KIND, _no_scenario_overlay, _placeholder_card, _stat, _tab_button_style, _worker_state_pie
from .bot import refresh_bot_tab
from .gallery import build_gallery_tab


def build_scenario_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    status_column = ft.Column(spacing=8)
    workers_column = ft.Column(spacing=8)
    state_chart = ft.Container()
    frontends_row = ft.Row(wrap=True, spacing=8)
    destroy_button = ft.OutlinedButton("Destroy active scenario", icon=ft.Icons.STOP_CIRCLE_OUTLINED)
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
            refresh_bot_tab(bot_tab_container, None, page, runner)
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
        refresh_bot_tab(bot_tab_container, lock, page, runner)
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

    refresh_button = ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=refresh)
    gallery_view, refresh_gallery = build_gallery_tab(page, runner, refresh)

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
