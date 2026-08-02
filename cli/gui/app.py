from __future__ import annotations

import argparse
import sys
import threading

import flet as ft

from .. import infra, observer
from .pages.contract_page import build_contract_page
from .pages.infra_page import build_infra_page
from .pages.observation_page import build_observation_page
from .pages.scenario_page import build_scenario_page
from .runner import ActionRunner

ENVS = ("devnet", "testnet", "mainnet")

NAV_DESTINATIONS = (
    ("Contract", ft.Icons.DESCRIPTION_OUTLINED, ft.Icons.DESCRIPTION),
    ("Infra", ft.Icons.DNS_OUTLINED, ft.Icons.DNS),
    ("Scenario", ft.Icons.LAYERS_OUTLINED, ft.Icons.LAYERS),
    ("Observation", ft.Icons.MONITOR_HEART_OUTLINED, ft.Icons.MONITOR_HEART),
)


class AppState:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.log_view = ft.ListView(spacing=2, auto_scroll=True, expand=True)
        self.runner = ActionRunner(page, self.log_view)


def default_env() -> str:
    try:
        topology = infra.read_topology()
        active = topology.get("active_env")
        if active in ENVS:
            return active
    except (OSError, ValueError):
        pass
    return "devnet"


def main(page: ft.Page) -> None:
    page.title = "vidctl"
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO, use_material3=True)
    page.theme_mode = ft.ThemeMode.LIGHT
    # Registered globally (Flet has no per-page font scope), but only the
    # Observation page's own Text controls ever reference these family
    # names -- Contract/Infra/Scenario are unaffected. See
    # pages/observation_page/theme.py for where/why.
    page.fonts = {
        "Chakra Petch": "https://raw.githubusercontent.com/google/fonts/main/ofl/chakrapetch/ChakraPetch-SemiBold.ttf",
        "IBM Plex Mono": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    }
    page.padding = 0
    page.window.width = 1280
    page.window.height = 860
    page.bgcolor = ft.Colors.SURFACE

    state = AppState(page)

    pages = [
        build_contract_page(state),
        build_infra_page(state),
        build_scenario_page(state),
        build_observation_page(state),
    ]
    body = ft.Container(content=pages[0], expand=True, padding=0)

    def on_nav_change(e: ft.ControlEvent) -> None:
        body.content = pages[e.control.selected_index]
        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=90,
        min_extended_width=160,
        bgcolor=ft.Colors.SURFACE,
        destinations=[
            ft.NavigationRailDestination(icon=icon, selected_icon=selected, label=label)
            for label, icon, selected in NAV_DESTINATIONS
        ],
        on_change=on_nav_change,
    )

    log_visible = {"value": False}

    def toggle_log(_: ft.ControlEvent) -> None:
        log_visible["value"] = not log_visible["value"]
        log_container.height = 220 if log_visible["value"] else 0
        toggle_button.icon = ft.Icons.EXPAND_LESS if log_visible["value"] else ft.Icons.EXPAND_MORE
        page.update()

    toggle_button = ft.IconButton(icon=ft.Icons.EXPAND_MORE, tooltip="Show/hide log", on_click=toggle_log)

    log_container = ft.Container(
        height=0,
        bgcolor=ft.Colors.BLACK87,
        padding=10,
        animate=ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT),
        content=ft.Column(
            [ft.Text("Log", size=12, color=ft.Colors.WHITE54, weight=ft.FontWeight.BOLD), state.log_view],
            expand=True,
        ),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    log_bar = ft.Container(
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        padding=ft.Padding.symmetric(horizontal=12, vertical=4),
        content=ft.Row(
            [ft.Icon(ft.Icons.TERMINAL, size=14), ft.Text("Activity log", size=12), toggle_button],
            alignment=ft.MainAxisAlignment.START,
        ),
    )

    page.appbar = ft.AppBar(
        title=ft.Text("vidctl"),
        center_title=False,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )

    page.add(
        ft.Column(
            [
                ft.Row([rail, ft.VerticalDivider(width=1), body], expand=True, spacing=0),
                log_bar,
                log_container,
            ],
            expand=True,
            spacing=0,
        )
    )


def _start_contract_state_watch(interval: int) -> None:
    """Background twin of `vidctl observer export-contract-state --watch`,
    started from `--watch` on `vidctl gui` so the Contract & Chain dashboard
    stays fresh for the length of the GUI session without a second terminal.
    Picks the same target host `cli/scenario/apply.py`'s
    `_push_contract_state()` does (the registered observer host running
    pushgateway) and the same active env `default_env()` feeds the Contract
    page. Daemon thread: it dies with the process, no explicit shutdown
    needed when the GUI window closes."""
    try:
        hosts = observer.read_hosts()
    except (OSError, ValueError) as exc:
        print(f"Warning: could not read observer hosts, --watch will not push contract state: {exc}", file=sys.stderr)
        return
    host_entry = next((h for h in hosts if "pushgateway" in (h.get("services") or observer.ALL_SERVICE_NAMES)), None)
    if host_entry is None:
        print("Warning: no registered observer host runs pushgateway; --watch will not push contract state.", file=sys.stderr)
        return

    env = default_env()
    host_name = str(host_entry.get("name", ""))
    thread = threading.Thread(
        target=observer.export_contract_state,
        args=(env, host_name),
        kwargs={"watch": True, "interval": interval},
        daemon=True,
    )
    thread.start()


def run(args: argparse.Namespace) -> int:
    if getattr(args, "watch", False):
        _start_contract_state_watch(getattr(args, "interval", 60) or 60)
    view = ft.AppView.WEB_BROWSER if getattr(args, "web", False) else ft.AppView.FLET_APP
    port = getattr(args, "port", None) or 0
    ft.run(main, view=view, port=port)
    return 0
