from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import flet as ft

from .... import contract as contract_cli
from .... import wallet as wallet_cli
from ...widgets import copyable_id, section_card, status_badge
from .handlers import _make_verify_handler, _make_view_handler, build_actions_tile
from .render import (
    ENVS,
    ROLE_COLORS,
    SHARED_OBJECTS,
    WALLET_FILTERS,
    _chart_status_key,
    _format_sui,
    _format_ts,
    _last_action,
    _role_balance_bar_chart,
    _role_pie_chart,
    _tile,
    _wallet_status_key,
)


def build_contract_page(state) -> ft.Control:
    page = state.page
    runner = state.runner

    env_dropdown = ft.Dropdown(
        label="Env",
        value="devnet",
        width=160,
        options=[ft.dropdown.Option(env) for env in ENVS],
    )
    gas_budget_field = ft.TextField(label="Gas budget (MIST, optional)", width=220)
    create_registry_checkbox = ft.Checkbox(label="Create missing registries")
    force_checkbox = ft.Checkbox(label="Force republish (--force)")

    header_row = ft.Row(wrap=True, spacing=12)
    objects_grid = ft.GridView(expand=False, runs_count=2, max_extent=420, child_aspect_ratio=3.4, spacing=10, run_spacing=10)
    wallets_column = ft.Column(spacing=6)
    role_chart = ft.Container()
    balance_chart = ft.Container()
    wallet_search_field = ft.TextField(label="Search alias / address", width=240, dense=True)
    wallet_filter_dropdown = ft.Dropdown(
        label="Filter",
        value="All",
        width=180,
        options=[ft.dropdown.Option(name) for name in WALLET_FILTERS],
    )
    # Repopulated by every refresh(); walked by sync_chain_data() below to
    # drive the 30s live poll of on-chain reads (object values, wallet caps,
    # wallet balances) against whatever rows are currently on screen.
    object_targets: list[tuple[str, ft.Text]] = []
    wallet_targets: list[tuple[str, str, ft.Container, ft.Text]] = []
    # address -> live on-chain balance (mist), populated by sync_chain_data()'s
    # 30s poll and persisted across ticks so a transient fetch failure doesn't
    # blank a wallet's balance back to zero. Falls back to wallet.toml's
    # last_balance_mist (a stale, pre-faucet snapshot -- see chain_ops.
    # faucet_if_needed) only until the first successful live fetch lands.
    live_balances: dict[str, int] = {}

    def selected_env() -> str:
        return env_dropdown.value or "devnet"

    def refresh(_: ft.ControlEvent | None = None) -> None:
        env = selected_env()
        deployment = contract_cli.load_deployment(env)
        published = bool(deployment.get("CONTRACT_PACKAGE_ID"))

        header_row.controls = [
            _tile("Status", status_badge("Published" if published else "Not published", "success" if published else "warning")),
            _tile("Package ID", copyable_id(deployment.get("CONTRACT_PACKAGE_ID", ""), page)),
            _tile("Chain ID", copyable_id(deployment.get("CONTRACT_CHAIN_ID", ""), page)),
            _tile("Upgrade cap", copyable_id(deployment.get("CONTRACT_UPGRADE_CAP_ID", ""), page)),
            _tile("Publish tx", copyable_id(deployment.get("CONTRACT_PUBLISH_TX_DIGEST", ""), page)),
            _tile("Admin cap (owned)", copyable_id(deployment.get("CONTRACT_ADMIN_CAP_ID", ""), page)),
        ]

        object_cards: list[ft.Control] = []
        object_targets.clear()
        for key, struct_name, icon in SHARED_OBJECTS:
            object_id = deployment.get(key, "")
            value_text = ft.Text("(not fetched)" if object_id else "-", selectable=True, size=11, italic=True)
            view_button = ft.TextButton("View details", icon=ft.Icons.VISIBILITY, disabled=not object_id)
            view_handler = _make_view_handler(runner, page, struct_name, object_id, value_text, view_button) if object_id else None
            view_button.on_click = view_handler
            if object_id:
                object_targets.append((object_id, value_text))
            card = ft.Container(
                padding=10,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
                ink=bool(object_id),
                on_click=(lambda e, h=view_handler: h(e)) if view_handler else None,
                content=ft.Column(
                    [
                        ft.Row([ft.Icon(icon, size=16), ft.Text(struct_name, weight=ft.FontWeight.BOLD, size=13)]),
                        copyable_id(object_id, page) if object_id else ft.Text("not created", size=11, color=ft.Colors.OUTLINE),
                        value_text,
                        ft.Row([view_button]),
                    ],
                    spacing=2,
                    tight=True,
                ),
            )
            object_cards.append(card)
        objects_grid.controls = object_cards

        wallets = wallet_cli.pool_status(env).get(env, [])
        role_counts: dict[str, int] = {}
        role_balances: dict[str, float] = {}
        for entry in wallets:
            chart_key = _chart_status_key(entry)
            role_counts[chart_key] = role_counts.get(chart_key, 0) + 1
            mist = live_balances.get(entry.get("address", ""), entry.get("last_balance_mist", 0) or 0)
            role_balances[chart_key] = role_balances.get(chart_key, 0.0) + float(mist) / 1_000_000_000
        role_chart.content = _role_pie_chart(role_counts)
        balance_chart.content = _role_balance_bar_chart(role_balances)

        search_term = (wallet_search_field.value or "").strip().lower()
        filter_value = wallet_filter_dropdown.value or "All"
        visible = []
        for entry in wallets:
            status_key = _wallet_status_key(entry)
            if filter_value == "Free" and status_key != "free":
                continue
            if filter_value == "Retired" and status_key != "retired":
                continue
            if filter_value not in ("All", "Free", "Retired") and status_key != filter_value:
                continue
            if search_term and search_term not in entry.get("alias", "").lower() and search_term not in entry.get("address", "").lower():
                continue
            visible.append((entry, status_key))
        # Latest last-action first; wallets with no timestamp at all sort last.
        visible.sort(key=lambda pair: _last_action(pair[0]), reverse=True)

        wallet_rows: list[ft.Control] = []
        wallet_targets.clear()
        for entry, status_key in visible:
            address = entry.get("address", "")
            role = entry.get("registered_role", "") or "unassigned"
            status_text = ft.Container(content=status_badge("unverified", "neutral"))
            verify_button = ft.TextButton("Verify on-chain", icon=ft.Icons.FACT_CHECK)
            verify_button.on_click = _make_verify_handler(runner, page, address, env, status_text)
            balance_text = ft.Text(
                _format_sui(live_balances.get(address, entry.get("last_balance_mist", 0))), size=12
            )
            if address:
                wallet_targets.append((address, _chart_status_key(entry), status_text, balance_text))
            wallet_rows.append(
                ft.Container(
                    padding=8,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                    content=ft.Row(
                        [
                            ft.Container(ft.Text(entry.get("alias", ""), weight=ft.FontWeight.BOLD), width=140),
                            ft.Container(copyable_id(address, page), width=200),
                            ft.Container(status_badge(role, "info" if role in ROLE_COLORS else "neutral"), width=150),
                            ft.Container(balance_text, width=120),
                            ft.Container(ft.Text(_format_ts(_last_action(entry)), size=11, color=ft.Colors.OUTLINE), width=160),
                            status_text,
                            verify_button,
                        ]
                    ),
                )
            )
        wallets_column.controls = wallet_rows or [ft.Text("No wallets match this filter.", color=ft.Colors.OUTLINE)]

        page.update()

    actions_tile = build_actions_tile(
        page,
        runner,
        selected_env,
        refresh,
        env_dropdown,
        gas_budget_field,
        create_registry_checkbox,
        force_checkbox,
        wallet_search_field,
        wallet_filter_dropdown,
    )

    async def sync_chain_data() -> None:
        """Live on-chain half of the 30s poll: re-fetches every shared
        object's current fields, re-verifies every wallet's cap, and
        re-fetches every wallet's real SUI balance, against whatever rows
        refresh() last put on screen. Sequential (not gathered) so a poll
        tick makes at most one Sui CLI call at a time instead of firing a
        dozen+ subprocesses at once."""
        now_label = datetime.now(timezone.utc).strftime("%H:%M UTC")
        for object_id, value_text in list(object_targets):
            try:
                fields = await asyncio.to_thread(contract_cli.fetch_object, object_id)
            except Exception:  # noqa: BLE001 - a poll tick must never crash the app
                fields = None
            # Just a status line -- the full field dump only shows up in the
            # "View details" popup (_make_view_handler), not on the card.
            value_text.value = f"synced {now_label}" if fields is not None else "(fetch failed)"
            value_text.italic = fields is None
        env = selected_env()
        role_balances: dict[str, float] = {}
        for address, chart_key, status_container, balance_text in list(wallet_targets):
            try:
                found = await asyncio.to_thread(wallet_cli.find_cap_id, address, env)
            except Exception:  # noqa: BLE001 - a poll tick must never crash the app
                found = None
            if found:
                struct_name, object_id = found
                status_container.content = status_badge(f"{struct_name} ({object_id[:10]}…)", "success")
            else:
                status_container.content = status_badge("not registered", "warning")
            try:
                mist = await asyncio.to_thread(wallet_cli.current_balance_mist, address)
                live_balances[address] = mist
            except Exception:  # noqa: BLE001 - a poll tick must never crash the app
                pass  # keep whatever live_balances already has (or the stale fallback)
            balance_text.value = _format_sui(live_balances.get(address, 0))
            role_balances[chart_key] = role_balances.get(chart_key, 0.0) + live_balances.get(address, 0) / 1_000_000_000
        if wallet_targets:
            balance_chart.content = _role_balance_bar_chart(role_balances)
        page.update()

    async def poll_forever() -> None:
        while True:
            refresh()
            await sync_chain_data()
            await asyncio.sleep(30)

    page.run_task(poll_forever)

    refresh()

    return ft.Container(
        padding=20,
        content=ft.Column(
            [
                actions_tile,
                section_card("Deployment", ft.Icons.DESCRIPTION, header_row),
                section_card(
                    "Wallet charts",
                    ft.Icons.INSIGHTS,
                    ft.Row(
                        [ft.Container(role_chart, width=280), ft.Container(balance_chart, expand=True)],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ),
                section_card("Shared objects", ft.Icons.SCHEMA, objects_grid),
                section_card(
                    "Wallets on this contract",
                    ft.Icons.ACCOUNT_BALANCE_WALLET,
                    ft.Column(
                        [
                            ft.Row([wallet_search_field, wallet_filter_dropdown], wrap=True),
                            wallets_column,
                        ],
                        spacing=10,
                    ),
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        ),
    )
