from __future__ import annotations

from typing import Callable

import flet as ft

from . import theme


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


def _dashboard_tab(
    uid: str,
    name: str,
    description: str,
    icon: str,
    is_selected: bool,
    on_select: Callable[[str], None],
) -> ft.Control:
    """A horizontal tab-strip item -- underline indicator, description
    dropped to a hover tooltip since a horizontal strip has no room for it
    inline."""
    accent = theme.SIGNAL if is_selected else theme.INK_MUTED
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        border=ft.Border(bottom=ft.BorderSide(2, theme.SIGNAL if is_selected else "transparent")),
        tooltip=description,
        on_click=lambda e: on_select(uid),
        content=ft.Row(
            [
                ft.Icon(icon, color=accent, size=16),
                ft.Text(
                    name,
                    weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.NORMAL,
                    color=accent,
                    font_family=theme.DISPLAY_FONT,
                ),
            ],
            spacing=6,
            tight=True,
        ),
    )
