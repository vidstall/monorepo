from __future__ import annotations

from typing import Any, Callable

import flet as ft
import flet_charts as fc

from ...widgets import PROVIDER_COLORS, provider_icon, status_badge, status_kind_for


def fleet_bar_chart(counts: dict[str, int]) -> ft.Control:
    active = {provider: n for provider, n in counts.items() if n > 0}
    if not active:
        return ft.Text("No workers provisioned yet.", size=12, color=ft.Colors.OUTLINE)
    max_count = max(active.values())
    groups = [
        fc.BarChartGroup(
            x=index,
            rods=[
                fc.BarChartRod(
                    to_y=count,
                    width=18,
                    color=PROVIDER_COLORS.get(provider, ft.Colors.BLUE_GREY_400),
                    border_radius=4,
                    tooltip=f"{provider}: {count}",
                )
            ],
        )
        for index, (provider, count) in enumerate(sorted(active.items()))
    ]
    labels = [
        fc.ChartAxisLabel(value=index, label=ft.Text(provider[:4], size=9))
        for index, provider in enumerate(sorted(active.keys()))
    ]
    return fc.BarChart(
        groups=groups,
        max_y=max_count + 1,
        interactive=True,
        left_axis=fc.ChartAxis(label_size=24),
        bottom_axis=fc.ChartAxis(labels=labels, label_size=24),
        height=140,
    )


def _provider_card(provider: str, count: int, is_selected: bool, on_select: Callable[[str], None]) -> ft.Control:
    return ft.Container(
        padding=8,
        border_radius=6,
        bgcolor=ft.Colors.PRIMARY_CONTAINER if is_selected else None,
        on_click=lambda e: on_select(provider),
        content=ft.Row(
            [
                provider_icon(provider),
                ft.Text(provider, expand=True),
                ft.Container(
                    content=ft.Text(str(count), size=11, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    border_radius=999,
                ),
            ]
        ),
    )


def _instance_card(host: str, workers: list[dict[str, Any]], on_select: Callable[[str, str, list], None]) -> ft.Control:
    statuses = {str(w.get("last_status") or "unknown") for w in workers}
    kind = "success"
    if any(status_kind_for(s) == "error" for s in statuses):
        kind = "error"
    elif len(statuses) > 1 or any(status_kind_for(s) != "success" for s in statuses):
        kind = "warning"
    provider = str(workers[0].get("provider", "")) if workers else ""
    container = ft.Container(
        padding=10,
        border_radius=6,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.COMPUTER, size=16), ft.Text(host, weight=ft.FontWeight.BOLD, expand=True)]),
                status_badge(f"{len(workers)} worker(s)", kind),
            ],
            spacing=4,
        ),
    )
    container.on_click = lambda e: on_select(provider, host, workers)
    return container
