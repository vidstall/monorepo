from __future__ import annotations

from pathlib import Path

import flet as ft

from .... import scenario as scenario_cli
from ...dialogs import confirm
from ...widgets import status_badge


def _build_gallery_cards(on_apply) -> list[ft.Control]:
    if not scenario_cli.SCENARIO_DIR.exists():
        return [ft.Text("No scenario/ directory found.", color=ft.Colors.OUTLINE)]
    paths = sorted(scenario_cli.SCENARIO_DIR.rglob("*.toml"))
    if not paths:
        return [ft.Text("No scenario TOML files found under scenario/.", color=ft.Colors.OUTLINE)]
    return [_scenario_gallery_card(path, on_apply) for path in paths]


def _scenario_gallery_card(path: Path, on_apply) -> ft.Control:
    try:
        rel = str(path.relative_to(scenario_cli.SCENARIO_DIR.parent))
    except ValueError:
        rel = str(path)

    try:
        data = scenario_cli.load_scenario(path)
    except (ValueError, OSError) as exc:
        return ft.Container(
            width=340,
            padding=12,
            border=ft.Border.all(1, ft.Colors.ERROR),
            border_radius=8,
            content=ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.ERROR), ft.Text(path.name, weight=ft.FontWeight.BOLD)]),
                    ft.Text(rel, size=11, color=ft.Colors.OUTLINE, selectable=True),
                    ft.Text(str(exc), size=12, color=ft.Colors.ERROR),
                ],
                spacing=4,
            ),
        )

    providers = sorted({w.get("provider", "") for w in data["workers"]} | {f.get("provider", "") for f in data["frontends"]})
    host_count = len({w.get("host", "") for w in data["workers"]})
    worker_count = len(data["workers"])
    frontend_count = len(data["frontends"])

    return ft.Container(
        width=340,
        padding=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LAYERS, size=18),
                        ft.Text(data["name"], weight=ft.FontWeight.BOLD, size=14, expand=True),
                        status_badge(data["env"], "info"),
                    ]
                ),
                ft.Text(rel, size=11, color=ft.Colors.OUTLINE, selectable=True),
                ft.Row([ft.Chip(label=ft.Text(p, size=11)) for p in providers if p], wrap=True, spacing=4),
                ft.Text(
                    f"{worker_count} worker(s) on {host_count} host(s) · {frontend_count} frontend(s)",
                    size=12,
                    color=ft.Colors.OUTLINE,
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use this scenario",
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=lambda e, p=rel: on_apply(p),
                        )
                    ]
                ),
            ],
            spacing=6,
        ),
    )


def build_gallery_tab(page: ft.Page, runner, on_applied) -> tuple[ft.Control, callable]:
    """Assembles the Gallery tab (scenario-file picker + apply form + the
    scanned scenario/ card grid) as one unit, since apply_path/do_apply/
    use_gallery_scenario/refresh_gallery are only ever used together here.
    `on_applied` is called after a scenario apply completes (success or
    failure) so the caller can refresh the other tabs. Returns
    (gallery_view, refresh_gallery) -- the caller is responsible for calling
    refresh_gallery() once at page init."""
    scenario_path_field = ft.TextField(
        label="Scenario TOML path",
        hint_text="scenario/example/example.toml",
        width=320,
    )
    # A wrapping Row (not GridView) so each card keeps its own natural height --
    # scenario cards vary a lot (1-4 provider chips, 1-2 line names), and
    # GridView's fixed cross-axis aspect ratio forces every cell to the same
    # height, clipping taller cards.
    gallery_column = ft.Row(wrap=True, spacing=12, run_spacing=12)

    def apply_path(path_str: str) -> None:
        path_str = (path_str or "").strip()
        if not path_str:
            runner.log("Enter a scenario TOML path first.")
            return

        def run_apply() -> None:
            runner.run(
                f"scenario apply {path_str}",
                scenario_cli.apply,
                path_str,
                True,
                on_done=lambda _r: on_applied(),
            )

        confirm(
            page,
            f"Apply scenario {path_str}?",
            "This is a full declarative reconcile: publishes the contract, publishes frontends, builds/pushes "
            "every worker image, and kills any worker not listed in this file. Only one scenario can be "
            "active at a time.",
            run_apply,
        )

    def do_apply(_: ft.ControlEvent) -> None:
        apply_path(scenario_path_field.value)

    def use_gallery_scenario(path_str: str) -> None:
        scenario_path_field.value = path_str
        page.update()
        apply_path(path_str)

    apply_button = ft.FilledButton("Apply scenario", icon=ft.Icons.UPLOAD_FILE, on_click=do_apply)

    def refresh_gallery(_: ft.ControlEvent | None = None) -> None:
        gallery_column.controls = _build_gallery_cards(use_gallery_scenario)
        page.update()

    gallery_refresh_button = ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Rescan scenario/ directory", on_click=refresh_gallery)

    gallery_view = ft.Column(
        [
            ft.Row([scenario_path_field, apply_button], wrap=True),
            ft.Row(
                [ft.Text("Scenario gallery", size=13, weight=ft.FontWeight.BOLD), gallery_refresh_button],
            ),
            gallery_column,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=16,
    )

    return gallery_view, refresh_gallery
