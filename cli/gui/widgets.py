from __future__ import annotations

import flet as ft

BADGE_COLORS = {
    "success": (ft.Colors.GREEN_50, ft.Colors.GREEN_800),
    "warning": (ft.Colors.ORANGE_50, ft.Colors.ORANGE_800),
    "error": (ft.Colors.RED_50, ft.Colors.RED_800),
    "info": (ft.Colors.BLUE_50, ft.Colors.BLUE_800),
    "neutral": (ft.Colors.GREY_200, ft.Colors.GREY_800),
}

# Fixed, deterministic accent per provider/status so the same name always
# reads the same color across every page instead of an arbitrary hash.
PROVIDER_COLORS = {
    "aws": ft.Colors.ORANGE_700,
    "gcp": ft.Colors.BLUE_700,
    "azure": ft.Colors.CYAN_700,
    "alibaba": ft.Colors.DEEP_ORANGE_700,
    "digitalocean": ft.Colors.INDIGO_700,
    "upcloud": ft.Colors.PURPLE_700,
    "akamai": ft.Colors.TEAL_700,
    "tencent": ft.Colors.BLUE_GREY_700,
    "cloudflare": ft.Colors.AMBER_800,
    "oci": ft.Colors.RED_700,
}

SERVICE_ICONS = {
    "relay": ft.Icons.SWAP_HORIZ,
    "signaling": ft.Icons.CELL_TOWER,
    "cp-daemon": ft.Icons.SETTINGS_ETHERNET,
    "validator-daemon": ft.Icons.VERIFIED_USER,
    "bot": ft.Icons.SMART_TOY,
    "prometheus": ft.Icons.MONITOR_HEART,
}


def section_card(title: str, icon: str, content: ft.Control) -> ft.Card:
    return ft.Card(
        elevation=1,
        content=ft.Container(
            padding=16,
            content=ft.Column(
                [
                    ft.Row([ft.Icon(icon, size=18), ft.Text(title, size=16, weight=ft.FontWeight.BOLD)]),
                    ft.Divider(height=12),
                    content,
                ]
            ),
        ),
    )


def status_badge(text: str, kind: str = "neutral") -> ft.Container:
    bg, fg = BADGE_COLORS.get(kind, BADGE_COLORS["neutral"])
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.W_600, color=fg),
        bgcolor=bg,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=999,
    )


def stat_tile(label: str, value: str, icon: str, color: str | None = None) -> ft.Container:
    return ft.Container(
        padding=12,
        border_radius=8,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        content=ft.Column(
            [
                ft.Row([ft.Icon(icon, size=16, color=color), ft.Text(label, size=11, color=ft.Colors.OUTLINE)]),
                ft.Text(value, size=15, weight=ft.FontWeight.BOLD, selectable=True, color=color),
            ],
            spacing=2,
            tight=True,
        ),
        width=220,
    )


def copyable_id(value: str, page: ft.Page) -> ft.Row:
    if not value:
        return ft.Row([ft.Text("-", size=12)])
    short = value if len(value) <= 18 else f"{value[:8]}…{value[-6:]}"

    async def do_copy(_: ft.ControlEvent) -> None:
        await ft.Clipboard().set(value)
        page.show_dialog(ft.SnackBar(content=ft.Text("Copied to clipboard"), duration=1200))

    return ft.Row(
        [
            ft.Text(short, size=12, font_family="monospace", selectable=True, tooltip=value),
            ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_size=14, tooltip="Copy full value", on_click=do_copy),
        ],
        spacing=0,
        tight=True,
    )


def provider_icon(provider: str) -> ft.Icon:
    return ft.Icon(ft.Icons.CLOUD, color=PROVIDER_COLORS.get(provider, ft.Colors.BLUE_GREY_500))


def service_icon(service: str) -> ft.Icon:
    return ft.Icon(SERVICE_ICONS.get(service, ft.Icons.DNS), size=18)


def status_kind_for(text: str | None) -> str:
    """Best-effort mapping from a free-form status/desired_state string
    (whatever infra.control()/registry state happens to have recorded) to a
    badge kind -- these values are operator/CLI-authored strings, not an
    enum, so this is a heuristic, not an exhaustive switch."""
    value = (text or "").lower()
    if any(token in value for token in ("running", "started", "ok", "active", "published", "deployed")):
        return "success"
    if any(token in value for token in ("error", "failed", "fail")):
        return "error"
    if any(token in value for token in ("pause", "stopped", "applying")):
        return "warning"
    return "neutral"
