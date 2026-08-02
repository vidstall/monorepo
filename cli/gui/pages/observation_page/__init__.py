from __future__ import annotations

import asyncio
from typing import Callable

import flet as ft

from .... import observer as observer_cli
from ...dialogs import confirm, show_info
from ...widgets import copyable_id, masked_secret
from . import theme
from .render import _panel, _data_text, _dashboard_tab, _label

# flet-webview is a separate add-on package (not bundled with flet core) --
# degrade to a plain "Open Grafana" launch button if it's ever missing,
# rather than the whole Observation page failing to import.
try:
    from flet_webview import WebView

    _WEBVIEW_SUPPORTED = True
except ImportError:
    WebView = None  # type: ignore[assignment, misc]
    _WEBVIEW_SUPPORTED = False

# The two static, never-Pulumi-managed, never-rebooted monitoring boxes this
# page watches -- bourbon and vermouth, two weak (1cpu/1gb) hosts dividing
# the observer stack between them instead of each running all 5 services
# colocated (see cli/observer/inventory.py's per-host `services` split).
# Hardcoded rather than exposed as an add/remove-able list in the UI, same
# reasoning as before this split existed: there are exactly 2 fixed hosts in
# practice, never added/removed through this page. Kept as module constants
# (not form defaults) since nothing here ever prompts for these values --
# see _ensure_hosts() below.
BOURBON_HOST = "bourbon"
BOURBON_ADDRESS = "161.118.232.63"
BOURBON_SSH_USER = "deploy"
BOURBON_SSH_KEY = "~/.ssh/rotexai/bourbon-deploy"
BOURBON_SERVICES = ["prometheus", "grafana", "pushgateway"]

VERMOUTH_HOST = "vermouth"
VERMOUTH_ADDRESS = "140.245.113.173"
VERMOUTH_SSH_USER = "deploy"
VERMOUTH_SSH_KEY = "~/.ssh/rotexai/vermouth-deploy"
VERMOUTH_SERVICES = ["tempo", "loki"]

# Grafana always lives on bourbon under the chosen split -- this alias is
# what the dashboard-embed path (current_address()/_grafana_url()) resolves
# against.
DEFAULT_HOST = BOURBON_HOST

# (dashboard uid, display name, description, icon) for every dashboard
# provisioned by grafana-dashboard-provider.yml.j2 -- see
# IaC/ansible/roles/docker_service/files/dashboards/*.json for the fixed
# uids (uid == filename stem == URL slug, by convention). Add a row here
# whenever a new dashboard file is provisioned; there's no dashboard-search
# API call to populate this dynamically.
DASHBOARDS = [
    (
        "overview",
        "Overview",
        "Pane of glass -- targets up, active sessions/rooms, chain-consensus rate, fleet-wide error logs",
        ft.Icons.DASHBOARD,
    ),
    (
        "contract-chain",
        "Contract & Chain",
        "Wallet pool, on-chain registration counts, contract/registry metadata",
        ft.Icons.ACCOUNT_BALANCE,
    ),
    (
        "infrastructure",
        "Infrastructure",
        "Per-droplet CPU/RAM/network/disk",
        ft.Icons.DNS,
    ),
    (
        "workers",
        "Workers",
        "Per-role CPU/RSS and delay -- RTT/jitter, chain-tx/vote latency",
        ft.Icons.MONITOR_HEART,
    ),
    (
        "rooms",
        "Rooms",
        "Per-room participants, duration, RTC quality",
        ft.Icons.MEETING_ROOM,
    ),
    (
        "bot",
        "Bot",
        "Join-phase breakdown, session counts/errors",
        ft.Icons.SMART_TOY,
    ),
]
DEFAULT_DASHBOARD_UID = "overview"


def _ensure_hosts() -> tuple[dict, dict]:
    """Register both hardcoded observer hosts if they aren't already in
    runtime/observer.toml -- idempotent (add_host() updates in place by
    name), so this is safe to call on every page build. bourbon gets
    prometheus+grafana+pushgateway, vermouth gets tempo+loki -- the
    confirmed split dividing the monitoring stack across the two weak
    static hosts."""
    bourbon = observer_cli.find_host(BOURBON_HOST) or observer_cli.add_host(
        BOURBON_HOST, BOURBON_ADDRESS, BOURBON_SSH_USER, BOURBON_SSH_KEY, services=BOURBON_SERVICES
    )
    vermouth = observer_cli.find_host(VERMOUTH_HOST) or observer_cli.add_host(
        VERMOUTH_HOST, VERMOUTH_ADDRESS, VERMOUTH_SSH_USER, VERMOUTH_SSH_KEY, services=VERMOUTH_SERVICES
    )
    return bourbon, vermouth


def _grafana_embed_url(address: str, dashboard_uid: str) -> str:
    # ?kiosk hides Grafana's own nav chrome -- correct for the in-app
    # WebView embed only, where this app's own chrome replaces it. theme=light
    # forces Grafana's OWN UI into light mode -- Grafana defaults to dark
    # regardless of this app's page.theme_mode (a separate app entirely,
    # embedded via webview), and this page is deliberately light (see
    # theme.py) -- without this the embed clashes.
    return f"https://grafana.{address.replace('.', '-')}.sslip.io/d/{dashboard_uid}/{dashboard_uid}?kiosk&theme=light"


def _grafana_url(address: str, dashboard_uid: str) -> str:
    # No ?kiosk: this URL is opened in a real external browser (or copied out
    # by the user) rather than embedded, so Grafana's own toolbar -- template
    # variable dropdowns, time-range picker -- should stay visible.
    return f"https://grafana.{address.replace('.', '-')}.sslip.io/d/{dashboard_uid}/{dashboard_uid}?theme=light"


def _tempo_ingest_url(address: str) -> str:
    return f"https://tempo.{address.replace('.', '-')}.sslip.io/v1/traces"


def _loki_ingest_url(address: str) -> str:
    return f"https://loki.{address.replace('.', '-')}.sslip.io/loki/api/v1/push"


def build_observation_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    dashboard_tabs = ft.Row(spacing=4, scroll=ft.ScrollMode.AUTO)
    selected = {"uid": DEFAULT_DASHBOARD_UID}

    def current_address() -> str:
        host = observer_cli.find_host(BOURBON_HOST)
        return str(host.get("address", "")) if host else ""

    def vermouth_address() -> str:
        host = observer_cli.find_host(VERMOUTH_HOST)
        return str(host.get("address", "")) if host else ""

    def refresh_dashboard_tabs() -> None:
        dashboard_tabs.controls = [
            _dashboard_tab(uid, name, description, icon, uid == selected["uid"], show_dashboard)
            for uid, name, description, icon in DASHBOARDS
        ]

    # The Grafana embed is a native platform view (flet-webview). Two prior
    # fix attempts both failed on the real native desktop app (confirmed by
    # the user, not just theory):
    #   1. Recreating a WebView control on every switch -- Flet's patcher
    #      diffs by tree position, not Python object identity, so a "new"
    #      control at the same position is indistinguishable on the wire
    #      from a plain property patch.
    #   2. Reassigning the existing control's `.url` and calling
    #      `.update()` -- still just a property patch; the mounted native
    #      WKWebView apparently never reacts to it.
    # Both were passive (property-patch) approaches. `WebView.load_request()`
    # is flet-webview's IMPERATIVE navigation method -- it invokes a runtime
    # method on the client's already-mounted WebView instance directly
    # (native platform channel call), which is the actual supported way to
    # navigate a webview after initial mount; a passive property patch was
    # never going to do it. Only supported on Android/iOS/macOS (raises on
    # Flet Web), which matches this GUI's real target -- the native desktop
    # app. One persistent WebView control (never recreated) built once, up
    # front, off the address available at page-build time -- this page only
    # ever watches the hardcoded BOURBON_HOST (grafana's home under the
    # chosen split), whose address doesn't change without a full page
    # rebuild anyway.
    _ensure_hosts()
    address = current_address()
    webview_control: WebView | None = None

    def _is_mounted(control: ft.Control) -> bool:
        # control.page doesn't return None for an unmounted control -- it
        # raises RuntimeError (walks the .parent chain looking for a Page
        # instance and gives up loudly). Only meaningful during the very
        # first show_dashboard() call, made before build_observation_page()
        # returns and its tree is actually attached to the page.
        try:
            return control.page is not None
        except RuntimeError:
            return False

    if address and _WEBVIEW_SUPPORTED:
        webview_control = WebView(url=_grafana_embed_url(address, selected["uid"]), expand=True)
        detail_content: ft.Control = _panel(ft.Container(content=webview_control, expand=True), padding=0)
        detail_content.expand = True
    elif address:
        detail_content = _panel(
            ft.Column(
                [
                    ft.Text(
                        "Live embed unavailable in this environment (flet-webview not installed).",
                        color=theme.INK_MUTED,
                    ),
                    ft.FilledButton(
                        "Open Grafana",
                        icon=ft.Icons.OPEN_IN_NEW,
                        on_click=lambda e: page.launch_url(_grafana_url(current_address(), selected["uid"])),
                    ),
                ],
                spacing=10,
            )
        )
    else:
        detail_content = _panel(ft.Text("No address on file.", color=theme.INK_MUTED))

    detail_column = ft.Column([detail_content], spacing=12, expand=True)
    detail_wrapper = ft.Container(content=detail_column, padding=20, expand=True)

    def show_dashboard(uid: str) -> None:
        selected["uid"] = uid
        refresh_dashboard_tabs()
        if webview_control is not None:
            new_url = _grafana_embed_url(current_address(), uid)
            if webview_control.url != new_url:
                webview_control.url = new_url
                if _is_mounted(webview_control):
                    # load_request() is async (a runtime method call to the
                    # client) -- schedule it rather than await, since
                    # show_dashboard() itself is a synchronous on_click
                    # handler.
                    page.run_task(webview_control.load_request, new_url)
        page.update()

    def open_manage_dialog(_: ft.ControlEvent) -> None:
        """Everything that isn't "watch a dashboard" -- secrets and
        lifecycle actions for the two hardcoded observer hosts (bourbon and
        vermouth, dividing the stack between them) -- lives behind this
        settings button instead of on the main page, which is the live
        monitoring view first and a control panel only on request."""
        bourbon_address = current_address()
        vermouth_addr = vermouth_address()

        def action(host_name: str, action_name: str, fn, needs_confirm: bool = False, confirm_message: str = "") -> Callable[[ft.ControlEvent], None]:
            def run_it(e: ft.ControlEvent) -> None:
                runner.run(
                    f"observer {action_name} --host {host_name}",
                    fn,
                    host_name,
                    trigger=e.control,
                    on_done=lambda _r: page.update(),
                )

            def fire(e: ft.ControlEvent) -> None:
                if needs_confirm:
                    confirm(page, f"{action_name.capitalize()} {host_name}?", confirm_message, lambda: run_it(e))
                else:
                    run_it(e)

            return fire

        def lifecycle_rows(host_name: str, destroy_message: str, clean_message: str) -> list[ft.Control]:
            return [
                ft.Row(
                    [
                        ft.FilledButton("Deploy", icon=ft.Icons.ROCKET_LAUNCH, on_click=action(host_name, "deploy", observer_cli.deploy)),
                        ft.OutlinedButton("Status", icon=ft.Icons.NETWORK_PING, on_click=action(host_name, "status", observer_cli.status)),
                        ft.OutlinedButton("Start", icon=ft.Icons.PLAY_ARROW, on_click=action(host_name, "start", observer_cli.start)),
                        ft.OutlinedButton("Stop", icon=ft.Icons.STOP, on_click=action(host_name, "stop", observer_cli.stop)),
                        ft.OutlinedButton("Restart", icon=ft.Icons.REPLAY, on_click=action(host_name, "restart", observer_cli.restart)),
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
                                host_name,
                                "destroy",
                                observer_cli.destroy,
                                needs_confirm=True,
                                confirm_message=destroy_message,
                            ),
                        ),
                        ft.OutlinedButton(
                            "Clean",
                            icon=ft.Icons.DELETE_FOREVER,
                            icon_color=theme.CRITICAL,
                            on_click=action(
                                host_name,
                                "clean",
                                observer_cli.clean,
                                needs_confirm=True,
                                confirm_message=clean_message,
                            ),
                        ),
                    ],
                    wrap=True,
                ),
            ]

        manage_body = ft.Column(
            [
                ft.Text("bourbon — prometheus, grafana, pushgateway", size=12, color=theme.INK_MUTED, weight=ft.FontWeight.BOLD),
                _panel(
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.DASHBOARD, color=theme.INK_MUTED, size=16), _label("GRAFANA")]),
                            copyable_id(_grafana_url(bourbon_address, selected["uid"]), page) if bourbon_address else _data_text("-"),
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
                *lifecycle_rows(
                    BOURBON_HOST,
                    destroy_message="Removes the prometheus/grafana/pushgateway containers, but keeps their "
                    "stored data on disk -- a later deploy/start recreates them with history intact.",
                    clean_message="Removes the containers AND wipes Prometheus's stored history permanently "
                    "(Grafana's dashboards/login are kept). This cannot be undone.",
                ),
                ft.Divider(height=1, color=theme.HAIRLINE),
                ft.Text("vermouth — tempo, loki", size=12, color=theme.INK_MUTED, weight=ft.FontWeight.BOLD),
                _panel(
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.TIMELINE, color=theme.INK_MUTED, size=16), _label("TEMPO TRACE INGEST")]),
                            copyable_id(_tempo_ingest_url(vermouth_addr), page) if vermouth_addr else _data_text("-"),
                            ft.Text("Authorization: Bearer <token>", size=11, color=theme.INK_MUTED),
                            masked_secret(observer_cli.tempo_auth_token(), page),
                        ],
                        spacing=6,
                    )
                ),
                _panel(
                    ft.Column(
                        [
                            ft.Row([ft.Icon(ft.Icons.ARTICLE, color=theme.INK_MUTED, size=16), _label("LOKI LOG INGEST")]),
                            copyable_id(_loki_ingest_url(vermouth_addr), page) if vermouth_addr else _data_text("-"),
                            ft.Text("Authorization: Basic base64('xaisen:<token>')", size=11, color=theme.INK_MUTED),
                            masked_secret(observer_cli.loki_auth_token(), page),
                        ],
                        spacing=6,
                    )
                ),
                *lifecycle_rows(
                    VERMOUTH_HOST,
                    destroy_message="Removes the tempo/loki containers, but keeps their stored data on disk -- "
                    "a later deploy/start recreates them with history intact.",
                    clean_message="Removes the containers AND wipes Tempo/Loki's stored history permanently. "
                    "This cannot be undone.",
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
        show_info(page, "Manage observer hosts", manage_body, width=460, height=640)

    async def poll_forever() -> None:
        while True:
            await asyncio.sleep(30)
            show_dashboard(selected["uid"])

    refresh_dashboard_tabs()
    show_dashboard(selected["uid"])
    page.run_task(poll_forever)

    header = ft.Container(
        padding=ft.Padding.only(left=12, right=8),
        content=ft.Row(
            [
                ft.Container(content=dashboard_tabs, expand=True),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    icon_color=theme.INK_MUTED,
                    icon_size=18,
                    tooltip="Manage observer host",
                    on_click=open_manage_dialog,
                ),
            ],
            spacing=0,
        ),
    )

    return ft.Container(
        bgcolor=theme.VOID,
        expand=True,
        content=ft.Column(
            [
                header,
                ft.Divider(height=1, color=theme.HAIRLINE),
                detail_wrapper,
            ],
            expand=True,
            spacing=0,
        ),
    )
