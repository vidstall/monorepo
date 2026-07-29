from __future__ import annotations

from typing import Any, Callable

import flet as ft

from . import theme


def _pulse_dot(kind: str = "signal", size: int = 10) -> ft.Control:
    """The page's one signature motion: a breathing opacity animation on a
    small filled circle. `kind` picks the color from theme.STATUS_COLORS
    -- signal/teal for healthy, alert/amber for unknown-or-stale,
    critical/red for a failed check."""
    color = theme.STATUS_COLORS.get(kind, theme.SIGNAL)
    dot = ft.Container(
        width=size,
        height=size,
        border_radius=size,
        bgcolor=color,
        opacity=1.0,
        animate_opacity=ft.Animation(900, ft.AnimationCurve.EASE_IN_OUT),
    )

    def start_pulse() -> None:
        dot.opacity = 0.35
        dot.update()

    # Flet controls fire this once mounted -- toggling opacity here (then
    # letting animate_opacity ping-pong on each subsequent page.update()
    # from the page's own 30s poll) is enough motion to read as "alive"
    # without a dedicated asyncio loop per dot.
    dot.on_animation_end = lambda e: None
    dot.did_mount = start_pulse
    return dot


def _panel(content: ft.Control, *, padding: int = 16) -> ft.Container:
    return ft.Container(
        padding=padding,
        bgcolor=theme.PANEL,
        border=ft.Border.all(1, theme.HAIRLINE),
        border_radius=10,
        content=content,
    )


def _label(text: str, *, size: int = 11) -> ft.Text:
    return ft.Text(text, size=size, color=theme.INK_MUTED, font_family=theme.DATA_FONT)


def _data_text(text: str, *, size: int = 13, color: str | None = None) -> ft.Text:
    return ft.Text(text, size=size, color=color or theme.INK, font_family=theme.DATA_FONT, selectable=True)


def _host_card(
    host: dict[str, Any],
    is_selected: bool,
    on_select: Callable[[str], None],
    on_manage: Callable[[str], None],
) -> ft.Control:
    name = str(host.get("name", ""))
    desired = str(host.get("desired_state", "running"))
    kind = "signal" if desired == "running" else "alert"
    return ft.Container(
        padding=10,
        border_radius=8,
        bgcolor=theme.HAIRLINE if is_selected else theme.PANEL,
        border=ft.Border.all(1, theme.HAIRLINE),
        on_click=lambda e: on_select(name),
        content=ft.Column(
            [
                ft.Row(
                    [
                        _pulse_dot(kind),
                        ft.Text(name, weight=ft.FontWeight.BOLD, color=theme.INK, font_family=theme.DISPLAY_FONT, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.SETTINGS_OUTLINED,
                            icon_color=theme.INK_MUTED,
                            icon_size=16,
                            tooltip="Manage host",
                            on_click=lambda e: on_manage(name),
                        ),
                    ]
                ),
                _label(str(host.get("address", ""))),
            ],
            spacing=4,
        ),
    )
