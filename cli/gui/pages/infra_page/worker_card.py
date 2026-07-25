from __future__ import annotations

from typing import Any, Callable

import flet as ft

from .... import infra as infra_cli
from .... import scenario as scenario_cli
from ...dialogs import confirm
from ...widgets import service_icon, status_badge, status_kind_for


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
