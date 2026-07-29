from __future__ import annotations

import asyncio
from typing import Callable

import flet as ft

from .... import observer as observer_cli
from ...dialogs import confirm, prompt_form, show_info
from ...widgets import copyable_id, masked_secret
from . import theme
from .render import _panel, _data_text, _host_card, _label

# flet-webview is a separate add-on package (not bundled with flet core) --
# degrade to a plain "Open Grafana" launch button if it's ever missing,
# rather than the whole Observation page failing to import.
try:
    from flet_webview import WebView

    _WEBVIEW_SUPPORTED = True
except ImportError:
    WebView = None  # type: ignore[assignment, misc]
    _WEBVIEW_SUPPORTED = False

DEFAULT_HOST = "bourbon"
# The operator's one real static monitoring box (see cli/observer's whole
# design rationale: a static, never-Pulumi-managed, never-rebooted host).
# Prefilled here purely as a form convenience -- still fully editable, and
# add_host() is idempotent by name so resubmitting with the same name just
# updates the existing entry rather than creating a duplicate.
DEFAULT_ADDRESS = "161.118.232.63"
DEFAULT_SSH_USER = "deploy"
DEFAULT_SSH_KEY = "~/.ssh/rotexai/bourbon-deploy"


def _grafana_url(address: str) -> str:
    # /d/xaisen-fleet/xaisen-fleet -- the "Xaisen Fleet" dashboard
    # provisioned by grafana-dashboard-provider.yml.j2 +
    # xaisen-fleet-dashboard.json.j2 (fixed uid "xaisen-fleet"), not
    # Grafana's bare landing page. ?kiosk hides Grafana's own nav chrome.
    # theme=light forces Grafana's OWN UI into light mode -- Grafana
    # defaults to dark regardless of this app's page.theme_mode (a
    # separate app entirely, embedded via webview), and this page is
    # deliberately light (see theme.py) -- without this the embed clashes.
    return f"https://grafana.{address.replace('.', '-')}.sslip.io/d/xaisen-fleet/xaisen-fleet?kiosk&theme=light"


def _tempo_ingest_url(address: str) -> str:
    return f"https://tempo.{address.replace('.', '-')}.sslip.io/v1/traces"


def _grafana_hero_panel(address: str, page: ft.Page) -> ft.Control:
    """The page's dominant element -- a live embedded Grafana view of the
    provisioned "Xaisen Fleet" dashboard when flet-webview is available,
    degrading to a big launch button otherwise. Panels show "No data"
    until the fleet is actually deployed and scraping -- an honest
    first-run state, not something to fake around."""
    if not address:
        return _panel(ft.Text("No address on file.", color=theme.INK_MUTED))
    if _WEBVIEW_SUPPORTED:
        panel = _panel(ft.Container(content=WebView(url=_grafana_url(address), expand=True), expand=True), padding=0)
        panel.expand = True
        return panel
    return _panel(
        ft.Column(
            [
                ft.Text("Live embed unavailable in this environment (flet-webview not installed).", color=theme.INK_MUTED),
                ft.FilledButton("Open Grafana", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e: page.launch_url(_grafana_url(address))),
            ],
            spacing=10,
        )
    )


def build_observation_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    hosts_list = ft.Column(spacing=6)
    # No scroll here: the Grafana hero panel below uses expand=True to fill
    # all remaining vertical space, which Flet (Flutter underneath) can't
    # combine with a scrollable parent -- an expand child inside a
    # scrolling container has no bounded height to expand into. Detail
    # content is short now that "Manage host" lives in its own dialog, so
    # there's nothing else here that would ever need to overflow/scroll.
    detail_column = ft.Column(spacing=12, expand=True)
    detail_column.controls = [
        ft.Text("Select a host to watch its dashboards.", color=theme.INK_MUTED, font_family=theme.DATA_FONT)
    ]
    selected = {"name": None}

    def refresh_hosts_list() -> None:
        hosts = observer_cli.read_hosts()
        if not hosts:
            hosts_list.controls = [ft.Text("No observer hosts registered yet.", color=theme.INK_MUTED, size=12)]
        else:
            hosts_list.controls = [
                _host_card(host, host.get("name") == selected["name"], show_host, open_manage_dialog) for host in hosts
            ]

    def show_host(name: str) -> None:
        selected["name"] = name
        refresh_hosts_list()
        host = observer_cli.find_host(name)
        if host is None:
            detail_column.controls = [ft.Text("This host is no longer registered.", color=theme.INK_MUTED)]
            page.update()
            return

        address = str(host.get("address", ""))

        # No header/status-strip here on purpose -- this view's whole job is
        # the live dashboard, so it gets the entire page. Name/address/pulse
        # live on the sidebar card, and the settings gear there opens
        # open_manage_dialog() -- nothing here needs that surfaced twice.
        detail_column.controls = [_grafana_hero_panel(address, page)]
        page.update()

    def open_manage_dialog(name: str) -> None:
        """Everything that isn't "watch the dashboard" -- secrets and
        lifecycle actions -- lives behind this settings button/gear
        instead of on the main page, which is the live monitoring view
        first and a control panel only on request."""
        host = observer_cli.find_host(name)
        if host is None:
            runner.log(f"{name!r} is no longer registered.")
            return
        address = str(host.get("address", ""))

        def action(action_name: str, fn, needs_confirm: bool = False, confirm_message: str = "") -> Callable[[ft.ControlEvent], None]:
            def run_it(e: ft.ControlEvent) -> None:
                runner.run(
                    f"observer {action_name} --host {name}",
                    fn,
                    name,
                    trigger=e.control,
                    on_done=lambda _r: show_host(name) if selected["name"] == name else None,
                )

            def fire(e: ft.ControlEvent) -> None:
                if needs_confirm:
                    confirm(page, f"{action_name.capitalize()} {name}?", confirm_message, lambda: run_it(e))
                else:
                    run_it(e)

            return fire

        def do_remove(e: ft.ControlEvent) -> None:
            def run_it() -> None:
                observer_cli.remove_host(name)
                if selected["name"] == name:
                    selected["name"] = None
                    detail_column.controls = [ft.Text("Select a host to watch its dashboards.", color=theme.INK_MUTED)]
                refresh_hosts_list()
                page.pop_dialog()
                page.update()

            confirm(
                page,
                f"Remove {name}?",
                "Removes this host from vidctl's local registry only -- no SSH connection is made, "
                "nothing on the remote host itself is touched (still running whatever it was running).",
                run_it,
            )

        manage_body = ft.Column(
            [
                _panel(
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.DASHBOARD, color=theme.INK_MUTED, size=16), _label("GRAFANA")]),
                            copyable_id(_grafana_url(address), page) if address else _data_text("-"),
                            ft.Text(
                                "Anonymous viewers see dashboards read-only -- this password is for editing:",
                                size=11,
                                color=theme.INK_MUTED,
                            ),
                            masked_secret(observer_cli.grafana_admin_password(), page),
                        ],
                        spacing=6,
                    )
                ),
                _panel(
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.TIMELINE, color=theme.INK_MUTED, size=16), _label("TEMPO TRACE INGEST")]),
                            copyable_id(_tempo_ingest_url(address), page) if address else _data_text("-"),
                            ft.Text("Authorization: Bearer <token>", size=11, color=theme.INK_MUTED),
                            masked_secret(observer_cli.tempo_auth_token(), page),
                        ],
                        spacing=6,
                    )
                ),
                ft.Row(
                    [
                        ft.FilledButton("Deploy", icon=ft.Icons.ROCKET_LAUNCH, on_click=action("deploy", observer_cli.deploy)),
                        ft.OutlinedButton("Status", icon=ft.Icons.NETWORK_PING, on_click=action("status", observer_cli.status)),
                        ft.OutlinedButton("Start", icon=ft.Icons.PLAY_ARROW, on_click=action("start", observer_cli.start)),
                        ft.OutlinedButton("Stop", icon=ft.Icons.STOP, on_click=action("stop", observer_cli.stop)),
                        ft.OutlinedButton("Restart", icon=ft.Icons.REPLAY, on_click=action("restart", observer_cli.restart)),
                    ],
                    wrap=True,
                ),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Destroy",
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_color=theme.CRITICAL,
                            on_click=action(
                                "destroy",
                                observer_cli.destroy,
                                needs_confirm=True,
                                confirm_message="Removes the prometheus/tempo/grafana containers, but keeps their "
                                "stored data on disk -- a later deploy/start recreates them with history intact.",
                            ),
                        ),
                        ft.OutlinedButton(
                            "Clean",
                            icon=ft.Icons.DELETE_FOREVER,
                            icon_color=theme.CRITICAL,
                            on_click=action(
                                "clean",
                                observer_cli.clean,
                                needs_confirm=True,
                                confirm_message="Removes the containers AND wipes Prometheus/Tempo's stored history "
                                "permanently (Grafana's dashboards/login are kept). This cannot be undone.",
                            ),
                        ),
                        ft.TextButton("Remove host", icon=ft.Icons.PLAYLIST_REMOVE, on_click=do_remove),
                    ],
                    wrap=True,
                ),
            ],
            spacing=10,
        )
        show_info(page, f"Manage {name}", manage_body, width=460, height=520)

    def do_add_host(_: ft.ControlEvent) -> None:
        def submitted(values: dict[str, str]) -> None:
            name = values.get("name", "").strip() or DEFAULT_HOST
            address = values.get("address", "").strip()
            ssh_user = values.get("ssh_user", "").strip()
            ssh_key = values.get("ssh_key", "").strip()
            port_raw = values.get("port", "").strip()
            if not address or not ssh_user or not ssh_key:
                runner.log("Add host: address, ssh user, and ssh key are all required.")
                return
            port = int(port_raw) if port_raw else None
            observer_cli.add_host(name, address, ssh_user, ssh_key, port=port)
            refresh_hosts_list()
            show_host(name)

        prompt_form(
            page,
            "Add observer host",
            [
                ("name", "Host name", DEFAULT_HOST),
                ("address", "Address (IP)", DEFAULT_ADDRESS),
                ("ssh_user", "SSH user", DEFAULT_SSH_USER),
                ("ssh_key", "SSH key path", DEFAULT_SSH_KEY),
                ("port", "Published port", str(observer_cli.DEFAULT_HOST_PORT)),
            ],
            submitted,
        )

    async def poll_forever() -> None:
        while True:
            await asyncio.sleep(30)
            refresh_hosts_list()
            if selected["name"]:
                show_host(selected["name"])
            page.update()

    refresh_hosts_list()
    page.run_task(poll_forever)

    sidebar_visible = {"value": True}

    sidebar = ft.Container(
        width=300,
        padding=12,
        content=ft.Column(
            [
                ft.Row([ft.FilledButton("Add host", icon=ft.Icons.ADD, on_click=do_add_host)]),
                ft.Text("OBSERVER HOSTS", size=11, color=theme.INK_MUTED, font_family=theme.DISPLAY_FONT),
                hosts_list,
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
    )
    sidebar_divider = ft.VerticalDivider(width=1, color=theme.HAIRLINE)

    def toggle_sidebar(e: ft.ControlEvent) -> None:
        sidebar_visible["value"] = not sidebar_visible["value"]
        sidebar.visible = sidebar_visible["value"]
        sidebar_divider.visible = sidebar_visible["value"]
        e.control.icon = ft.Icons.CHEVRON_RIGHT if not sidebar_visible["value"] else ft.Icons.CHEVRON_LEFT
        e.control.tooltip = "Show observer hosts" if not sidebar_visible["value"] else "Hide observer hosts, show only this dashboard"
        page.update()

    # A persistent narrow rail (never itself hidden) so the toggle stays
    # reachable even with the host list collapsed -- the whole point is
    # freeing up width for the Grafana embed while watching it.
    rail = ft.Container(
        width=32,
        alignment=ft.Alignment.TOP_CENTER,
        padding=ft.Padding.only(top=8),
        content=ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            icon_color=theme.INK_MUTED,
            tooltip="Hide observer hosts, show only this dashboard",
            on_click=toggle_sidebar,
        ),
    )

    return ft.Container(
        bgcolor=theme.VOID,
        expand=True,
        content=ft.Row(
            [
                rail,
                sidebar,
                sidebar_divider,
                ft.Container(content=detail_column, padding=20, expand=True),
            ],
            expand=True,
            spacing=0,
        ),
    )
