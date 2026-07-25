from __future__ import annotations

import flet as ft
import flet_charts as fc

from ...widgets import status_kind_for

LOCK_STATUS_KIND = {"active": "success", "applying": "info", "failed": "error"}


def _tab_button_style(is_active: bool) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=ft.Colors.PRIMARY_CONTAINER if is_active else None,
        color=ft.Colors.ON_PRIMARY_CONTAINER if is_active else ft.Colors.OUTLINE,
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
