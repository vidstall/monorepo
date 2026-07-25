from __future__ import annotations

from datetime import datetime, timezone

import flet as ft

from .... import contract as contract_cli
from .... import wallet as wallet_cli
from ...dialogs import confirm, show_info
from ...widgets import copyable_id, status_badge
from .render import _render_move_fields


def _make_view_handler(runner, page: ft.Page, struct_name: str, object_id: str, status_text: ft.Text, trigger: ft.Control):
    """Fetches the object fresh on every click and pops up a detail dialog --
    used by both the card's own on_click and its 'View details' button, so
    'click into the object' and 'click the button' do the same thing."""

    def on_click(e: ft.ControlEvent | None) -> None:
        show_info(
            page,
            struct_name,
            ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2), ft.Text("Fetching current on-chain value…")], spacing=10),
            width=420,
        )

        def on_done(fields: object) -> None:
            page.pop_dialog()
            now_label = datetime.now(timezone.utc).strftime("%H:%M UTC")
            if fields is None:
                status_text.value = "(fetch failed)"
                status_text.italic = True
                page.update()
                show_info(
                    page,
                    struct_name,
                    ft.Text("Fetch failed -- see the Activity log for the sui CLI error.", color=ft.Colors.ERROR),
                    width=420,
                )
                return
            status_text.value = f"synced {now_label}"
            status_text.italic = False
            page.update()
            show_info(
                page,
                struct_name,
                ft.Column(
                    [copyable_id(object_id, page), ft.Divider(), _render_move_fields(fields, page)],
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                    spacing=8,
                ),
                width=560,
                height=520,
            )

        runner.run(f"fetch object {object_id}", contract_cli.fetch_object, object_id, trigger=trigger, on_done=on_done)

    return on_click


def _make_verify_handler(runner, page: ft.Page, address: str, env: str, target: ft.Container):
    def on_click(e: ft.ControlEvent) -> None:
        def on_done(found: object) -> None:
            if found:
                struct_name, object_id = found
                target.content = status_badge(f"{struct_name} ({object_id[:10]}…)", "success")
            else:
                target.content = status_badge("not registered", "warning")
            page.update()

        runner.run(f"verify {address}", wallet_cli.find_cap_id, address, env, trigger=e.control, on_done=on_done)

    return on_click


def build_actions_tile(
    page: ft.Page,
    runner,
    selected_env,
    refresh,
    env_dropdown: ft.Dropdown,
    gas_budget_field: ft.TextField,
    create_registry_checkbox: ft.Checkbox,
    force_checkbox: ft.Checkbox,
    wallet_search_field: ft.TextField,
    wallet_filter_dropdown: ft.Dropdown,
) -> ft.Control:
    """Builds and wires the collapsible actions bar (env picker, refresh,
    build/test/check/publish) -- kept as one factory since every button here
    shares the same `selected_env`/`refresh` closures and is only ever
    assembled together."""

    def do_publish(e: ft.ControlEvent) -> None:
        env = selected_env()

        def run_publish() -> None:
            gas_budget = (gas_budget_field.value or "").strip() or None
            runner.run(
                f"contract publish --env {env}",
                contract_cli.publish,
                env,
                False,
                True,
                gas_budget,
                create_registry_checkbox.value,
                force_checkbox.value,
                trigger=e.control,
                on_done=lambda _result: refresh(),
            )

        warning = " -- MAINNET, this costs real gas." if env == "mainnet" else ""
        confirm(
            page,
            f"Publish contract on {env}?",
            f"This runs a real sui client publish/upgrade against {env}{warning} "
            "and updates the frontend's .env with the new object IDs.",
            run_publish,
        )

    build_button = ft.OutlinedButton("Build", icon=ft.Icons.BUILD)
    test_button = ft.OutlinedButton("Test", icon=ft.Icons.SCIENCE)
    check_button = ft.OutlinedButton("Check", icon=ft.Icons.FACT_CHECK)
    publish_button = ft.FilledButton("Publish", icon=ft.Icons.ROCKET_LAUNCH, on_click=do_publish)

    build_button.on_click = lambda e: runner.run(
        f"contract build --env {selected_env()}", contract_cli.build, selected_env(), trigger=e.control
    )
    test_button.on_click = lambda e: runner.run(
        f"contract test --env {selected_env()}", contract_cli.test, selected_env(), trigger=e.control
    )
    check_button.on_click = lambda e: runner.run(
        f"contract check --env {selected_env()}", contract_cli.check, selected_env(), trigger=e.control
    )
    # flet 0.86's Dropdown fires on_select, not on_change (that field doesn't
    # exist on this control -- assigning .on_change is a silent no-op).
    env_dropdown.on_select = refresh
    wallet_search_field.on_change = refresh
    wallet_filter_dropdown.on_select = refresh
    refresh_button = ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=refresh)

    return ft.ExpansionTile(
        title=ft.Text("Contract actions", size=13),
        leading=ft.Icon(ft.Icons.TUNE, size=18),
        controls=[
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                content=ft.Column(
                    [
                        ft.Row(
                            [env_dropdown, refresh_button, build_button, test_button, check_button, publish_button],
                            wrap=True,
                        ),
                        ft.Row([gas_budget_field, create_registry_checkbox, force_checkbox], wrap=True),
                    ]
                ),
            )
        ],
        expanded=False,
        dense=True,
    )
