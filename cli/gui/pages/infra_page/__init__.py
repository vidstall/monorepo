from __future__ import annotations

import asyncio
from typing import Any

import flet as ft

from .... import infra as infra_cli
from .render import _instance_card, _provider_card, fleet_bar_chart
from .worker_card import worker_card

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
    detail_column = ft.Column(spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)
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
