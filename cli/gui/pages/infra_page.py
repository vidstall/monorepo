from __future__ import annotations

import asyncio
from typing import Any, Callable

import flet as ft
import flet_charts as fc

from ... import infra as infra_cli
from ... import scenario as scenario_cli
from ..dialogs import confirm
from ..widgets import PROVIDER_COLORS, provider_icon, service_icon, status_badge, status_kind_for

# Only the providers actually in use right now -- infra_cli.PROVIDERS lists
# every backend the CLI knows how to provision, but showing all 10 in the
# GUI's provider list clutters it with permanently-zero entries.
GUI_PROVIDERS = ("azure", "akamai", "digitalocean")


def build_infra_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    chart_container = ft.Container()
    provider_list = ft.Column(spacing=6)
    instances_list = ft.Column(spacing=6)
    detail_column = ft.Column(spacing=8, expand=True)
    detail_column.controls = [ft.Text("Select an instance to see its workers.", color=ft.Colors.OUTLINE)]
    selected = {"provider": None}
    # Tracks whichever instance's worker list is currently open in the detail
    # panel, so the 30s poll can refresh it too, not just the provider/
    # instance lists on the left.
    current_detail = {"provider": None, "host": None}

    def load_topology() -> dict[str, Any]:
        try:
            return infra_cli.read_topology()
        except (OSError, ValueError):
            return {"workers": [], "providers": {}}

    def all_provider_counts() -> dict[str, int]:
        topology = load_topology()
        counts = {provider: 0 for provider in GUI_PROVIDERS}
        for worker in topology.get("workers", []):
            if worker.get("desired_state") == "deleted":
                continue
            provider = worker.get("provider")
            if provider in counts:
                counts[provider] += 1
        return counts

    def instances_for_provider(provider: str) -> dict[str, list[dict[str, Any]]]:
        topology = load_topology()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for worker in topology.get("workers", []):
            if worker.get("provider") != provider or worker.get("desired_state") == "deleted":
                continue
            grouped.setdefault(str(worker.get("host", "")), []).append(worker)
        return grouped

    def refresh_chart() -> None:
        chart_container.content = fleet_bar_chart(all_provider_counts())

    def refresh_provider_list() -> None:
        counts = all_provider_counts()
        provider_list.controls = [
            _provider_card(provider, counts.get(provider, 0), provider == selected["provider"], select_provider)
            for provider in GUI_PROVIDERS
        ]

    def refresh_instances() -> None:
        provider = selected["provider"]
        grouped = instances_for_provider(provider) if provider else {}
        if not grouped:
            instances_list.controls = [
                ft.Text(
                    "No instances on this provider." if provider else "Pick a provider.",
                    color=ft.Colors.OUTLINE,
                    size=12,
                )
            ]
        else:
            instances_list.controls = [
                _instance_card(host, workers, show_instance) for host, workers in sorted(grouped.items())
            ]

    def select_provider(provider: str) -> None:
        selected["provider"] = provider
        current_detail["provider"] = None
        current_detail["host"] = None
        refresh_provider_list()
        refresh_instances()
        detail_column.controls = [ft.Text("Select an instance to see its workers.", color=ft.Colors.OUTLINE)]
        page.update()

    def refresh_detail_for_host(provider: str, host: str) -> None:
        workers = instances_for_provider(provider).get(host, [])
        if workers:
            show_instance(provider, host, workers)
        else:
            current_detail["provider"] = None
            current_detail["host"] = None
            refresh_instances()
            detail_column.controls = [ft.Text("This host has no workers left.", color=ft.Colors.OUTLINE)]
        refresh_chart()
        page.update()

    def show_instance(provider: str, host: str, workers: list[dict[str, Any]]) -> None:
        current_detail["provider"] = provider
        current_detail["host"] = host
        address = infra_cli.host_address(host)
        user = infra_cli.host_ssh_user(host)

        def do_configure(e: ft.ControlEvent) -> None:
            runner.run(f"infra configure --host {host}", infra_cli.configure, host, trigger=e.control)

        rows: list[ft.Control] = [
            ft.Row([ft.Icon(ft.Icons.DNS), ft.Text(host, size=18, weight=ft.FontWeight.BOLD)]),
            ft.Text(f"Address: {address or 'unresolved'}    SSH user: {user}", size=12, color=ft.Colors.OUTLINE),
            ft.Row([ft.OutlinedButton("Configure this host", icon=ft.Icons.SETTINGS, on_click=do_configure)]),
            ft.Divider(),
            ft.Text("Workers", weight=ft.FontWeight.BOLD),
        ]
        if not workers:
            rows.append(ft.Text("No workers recorded on this host.", color=ft.Colors.OUTLINE))
        for worker in workers:
            rows.append(
                worker_card(runner, page, provider, host, worker, lambda: refresh_detail_for_host(provider, host))
            )
        detail_column.controls = rows
        page.update()

    def do_ping(e: ft.ControlEvent) -> None:
        runner.run("infra ping", infra_cli.ping, trigger=e.control)

    async def poll_forever() -> None:
        while True:
            await asyncio.sleep(30)
            refresh_chart()
            refresh_provider_list()
            refresh_instances()
            if current_detail["host"]:
                refresh_detail_for_host(current_detail["provider"], current_detail["host"])
            page.update()

    refresh_chart()
    select_provider(GUI_PROVIDERS[0])
    page.run_task(poll_forever)

    return ft.Row(
        [
            ft.Container(
                width=320,
                padding=12,
                content=ft.Column(
                    [
                        ft.Row([ft.FilledButton("Ping inventory", icon=ft.Icons.NETWORK_PING, on_click=do_ping)]),
                        ft.Text("Fleet by provider", size=13, weight=ft.FontWeight.BOLD),
                        chart_container,
                        ft.Divider(),
                        ft.Text("Providers", size=13, weight=ft.FontWeight.BOLD),
                        provider_list,
                        ft.Divider(),
                        ft.Text("Instances", size=13, weight=ft.FontWeight.BOLD),
                        instances_list,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            ft.VerticalDivider(width=1),
            ft.Container(content=detail_column, padding=20, expand=True),
        ],
        expand=True,
        spacing=0,
    )


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


def worker_card(
    runner,
    page: ft.Page,
    provider: str,
    host: str,
    worker: dict[str, Any],
    on_changed: Callable[[], None],
) -> ft.Control:
    service = str(worker.get("service", ""))
    worker_index = int(worker.get("worker_index", 1) or 1)
    label = service if worker_index == 1 else f"{service}-{worker_index}"
    desired = str(worker.get("desired_state", "-"))
    last_status = str(worker.get("last_status", "-"))
    last_error = worker.get("last_error", "")

    def action(action_name: str, icon: str, needs_confirm: bool = False) -> Callable[[ft.ControlEvent], None]:
        def fire(e: ft.ControlEvent) -> None:
            # Same guard cli/vidctl.py's run_lifecycle_action() applies before
            # any manual `vidctl infra start/pause/restart/kill` -- a scenario
            # owns the fleet declaratively while its lock is active/applying,
            # so manual per-worker control from the GUI must be refused too.
            guard_code = scenario_cli.guard_manual_infra(action_name)
            if guard_code is not None:
                runner.log(
                    f"Refused: a scenario currently owns infra (see Scenario tab). "
                    f"Run 'scenario destroy' before manual {action_name}."
                )
                return

            def run_it() -> None:
                runner.run(
                    f"infra {action_name} --host {host} --service {label} --provider {provider}",
                    infra_cli.control,
                    action_name,
                    host,
                    service,
                    provider,
                    True,
                    False,
                    False,
                    None,
                    worker_index,
                    trigger=e.control,
                    on_done=lambda _r: on_changed(),
                )

            if needs_confirm:
                confirm(
                    page,
                    f"{action_name.capitalize()} {label} on {host}?",
                    f"This runs infra.{action_name}() for real against {provider} -- it changes live cloud "
                    f"infrastructure{' and deletes this worker permanently' if action_name == 'kill' else ''}.",
                    run_it,
                )
            else:
                run_it()

        return fire

    return ft.Container(
        padding=10,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        content=ft.Column(
            [
                ft.Row(
                    [
                        service_icon(service),
                        ft.Text(label, weight=ft.FontWeight.BOLD, expand=True),
                        status_badge(f"desired: {desired}", status_kind_for(desired)),
                        status_badge(f"status: {last_status}", status_kind_for(last_status)),
                    ]
                ),
                ft.Text(f"error: {last_error}", size=12, color=ft.Colors.RED) if last_error else ft.Container(),
                ft.Row(
                    [
                        ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="Start", on_click=action("start", ft.Icons.PLAY_ARROW)),
                        ft.IconButton(icon=ft.Icons.PAUSE, tooltip="Pause", on_click=action("pause", ft.Icons.PAUSE)),
                        ft.IconButton(icon=ft.Icons.REPLAY, tooltip="Restart", on_click=action("restart", ft.Icons.REPLAY)),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Kill",
                            icon_color=ft.Colors.RED,
                            on_click=action("kill", ft.Icons.DELETE_OUTLINE, needs_confirm=True),
                        ),
                    ]
                ),
            ],
            spacing=4,
        ),
    )
