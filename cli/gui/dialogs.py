from __future__ import annotations

from typing import Callable

import flet as ft


def confirm(page: ft.Page, title: str, message: str, on_confirm: Callable[[], None]) -> None:
    """Modal yes/no dialog standing in for the CLI's --yes flag. Every
    destructive action (kill a worker, scenario destroy/apply, mainnet
    publish) routes through this instead of firing immediately."""

    def close(_: ft.ControlEvent | None = None) -> None:
        page.pop_dialog()

    def confirmed(_: ft.ControlEvent) -> None:
        close()
        on_confirm()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Text(message),
        actions=[
            ft.TextButton("Cancel", on_click=close),
            ft.FilledButton("Confirm", on_click=confirmed),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dialog)


def show_info(page: ft.Page, title: str, content: ft.Control, *, width: int | None = None, height: int | None = None) -> None:
    """Modal read-only detail popup -- a scrollable content pane with a
    single Close action. Used for e.g. a shared object's full fetched
    field data, which doesn't fit readably inside its on-page card."""

    def close(_: ft.ControlEvent | None = None) -> None:
        page.pop_dialog()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Container(content=content, width=width, height=height),
        actions=[ft.TextButton("Close", on_click=close)],
        actions_alignment=ft.MainAxisAlignment.END,
        scrollable=True,
    )
    page.show_dialog(dialog)
