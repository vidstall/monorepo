from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import flet as ft
import flet_charts as fc

from ... import contract as contract_cli
from ... import wallet as wallet_cli
from ..dialogs import confirm, show_info
from ..widgets import copyable_id, section_card, status_badge

ENVS = ("devnet", "testnet", "mainnet")

# (deployment .env key, Move struct name, icon) for every shared object
# created at publish time -- see cli/contract.py's REGISTRY_CREATE_SPECS +
# the module init()-created NetworkRegistry/MinerStore/RoleVoteBox/
# LivenessVoteBox.
SHARED_OBJECTS = [
    ("NETWORK_REGISTRY_ID", "NetworkRegistry", ft.Icons.HUB),
    ("MINER_STORE_ID", "MinerStore", ft.Icons.STORAGE),
    ("ROLE_VOTE_BOX_ID", "RoleVoteBox", ft.Icons.HOW_TO_VOTE),
    ("LIVENESS_VOTE_BOX_ID", "LivenessVoteBox", ft.Icons.FAVORITE_BORDER),
    ("CP_REGISTRY_ID", "ControlPlaneRegistry", ft.Icons.SETTINGS_ETHERNET),
    ("RELAY_REGISTRY_ID", "RelayRegistry", ft.Icons.SWAP_HORIZ),
    ("SIGNALING_REGISTRY_ID", "SignalingRegistry", ft.Icons.CELL_TOWER),
    ("VALIDATOR_REGISTRY_ID", "ValidatorRegistry", ft.Icons.VERIFIED_USER),
    ("USER_REGISTRY_ID", "UserRegistry", ft.Icons.PEOPLE_OUTLINE),
    ("ROOM_MANAGER_ID", "RoomManager", ft.Icons.MEETING_ROOM),
    ("QUORUM_CONFIG_ID", "QuorumConfigState", ft.Icons.BALANCE),
]

ROLE_COLORS = {
    "relay": ft.Colors.INDIGO,
    "signaling": ft.Colors.TEAL,
    "cp-daemon": ft.Colors.DEEP_ORANGE,
    "validator-daemon": ft.Colors.PURPLE,
    "bot": ft.Colors.PINK_600,
    "prometheus": ft.Colors.BROWN_400,
    "grafana": ft.Colors.CYAN_700,
}
FREE_COLOR = ft.Colors.GREY_400
RETIRED_COLOR = ft.Colors.RED_300

WALLET_FILTERS = ["All", "Free", "Retired"] + list(ROLE_COLORS.keys())


def _wallet_status_key(entry: dict) -> str:
    if entry.get("retired"):
        return "retired"
    if entry.get("registered_role"):
        return entry["registered_role"]
    return "free"


def _last_action(entry: dict) -> str:
    """Most recent of the timestamp fields wallet.py stamps on any pool
    mutation (assign/release/retire) -- falls back to created_at so a
    never-touched wallet still sorts by when it was created."""
    candidates = [entry.get("retired_at"), entry.get("released_at"), entry.get("assigned_at"), entry.get("created_at")]
    valid = [c for c in candidates if c]
    return max(valid) if valid else ""


def _format_ts(ts: str) -> str:
    if not ts:
        return "never"
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return ts


def _format_sui(mist: object) -> str:
    try:
        value = float(mist) / 1_000_000_000
    except (TypeError, ValueError):
        return "-"
    return f"{value:,.4f} SUI"


def _tile(label: str, content: ft.Control) -> ft.Container:
    return ft.Container(
        padding=12,
        border_radius=8,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        width=230,
        content=ft.Column([ft.Text(label, size=11, color=ft.Colors.OUTLINE), content], spacing=4, tight=True),
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
    # drive the 30s live poll of on-chain reads (object values, wallet caps)
    # against whatever rows are currently on screen.
    object_targets: list[tuple[str, ft.Text]] = []
    wallet_targets: list[tuple[str, ft.Container]] = []

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
            status_key = _wallet_status_key(entry)
            role_counts[status_key] = role_counts.get(status_key, 0) + 1
            role_balances[status_key] = role_balances.get(status_key, 0.0) + float(entry.get("last_balance_mist", 0) or 0) / 1_000_000_000
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
            if address:
                wallet_targets.append((address, status_text))
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
                            ft.Container(ft.Text(_format_sui(entry.get("last_balance_mist", 0)), size=12), width=120),
                            ft.Container(ft.Text(_format_ts(_last_action(entry)), size=11, color=ft.Colors.OUTLINE), width=160),
                            status_text,
                            verify_button,
                        ]
                    ),
                )
            )
        wallets_column.controls = wallet_rows or [ft.Text("No wallets match this filter.", color=ft.Colors.OUTLINE)]

        page.update()

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

    async def sync_chain_data() -> None:
        """Live on-chain half of the 30s poll: re-fetches every shared
        object's current fields and re-verifies every wallet's cap,
        against whatever rows refresh() last put on screen. Sequential
        (not gathered) so a poll tick makes at most one Sui CLI call at a
        time instead of firing a dozen+ subprocesses at once."""
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
        for address, status_container in list(wallet_targets):
            try:
                found = await asyncio.to_thread(wallet_cli.find_cap_id, address, env)
            except Exception:  # noqa: BLE001 - a poll tick must never crash the app
                found = None
            if found:
                struct_name, object_id = found
                status_container.content = status_badge(f"{struct_name} ({object_id[:10]}…)", "success")
            else:
                status_container.content = status_badge("not registered", "warning")
        page.update()

    async def poll_forever() -> None:
        while True:
            refresh()
            await sync_chain_data()
            await asyncio.sleep(30)

    page.run_task(poll_forever)

    refresh()

    actions_tile = ft.ExpansionTile(
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


def _role_pie_chart(role_counts: dict[str, int]) -> ft.Control:
    if not role_counts:
        return ft.Text("No wallets to chart.", color=ft.Colors.OUTLINE)
    palette = {**ROLE_COLORS, "free": FREE_COLOR, "retired": RETIRED_COLOR, "unassigned": FREE_COLOR}
    total = sum(role_counts.values())
    # Largest slice first so small ones (e.g. a lone bot/prometheus/grafana
    # wallet) end up adjacent rather than scattered between big ones.
    items = sorted(role_counts.items(), key=lambda kv: kv[1], reverse=True)
    sections = [
        fc.PieChartSection(
            value=count,
            # In-slice labels only for slices with room to show one --
            # below ~8% of the pie, "role\ncount" text from two adjacent
            # thin wedges collides and becomes unreadable (see the legend
            # below for the full breakdown instead).
            title=f"{count}" if count / total >= 0.08 else None,
            title_style=ft.TextStyle(size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            color=palette.get(role, ft.Colors.BLUE_GREY_300),
            radius=70,
        )
        for role, count in items
    ]
    legend = ft.Column(
        [
            ft.Row(
                [
                    ft.Container(width=10, height=10, bgcolor=palette.get(role, ft.Colors.BLUE_GREY_300), border_radius=2),
                    ft.Text(role, size=12, expand=True),
                    ft.Text(str(count), size=12, weight=ft.FontWeight.BOLD),
                ],
                spacing=6,
            )
            for role, count in items
        ],
        spacing=4,
    )
    return ft.Column(
        [
            ft.Text("Wallet role distribution", size=13, weight=ft.FontWeight.BOLD),
            fc.PieChart(sections=sections, sections_space=1, center_space_radius=30, height=200),
            legend,
            ft.Text(f"{total} wallet(s) total", size=11, color=ft.Colors.OUTLINE),
        ]
    )


def _role_balance_bar_chart(role_balances: dict[str, float]) -> ft.Control:
    palette = {**ROLE_COLORS, "free": FREE_COLOR, "retired": RETIRED_COLOR, "unassigned": FREE_COLOR}
    active = {role: balance for role, balance in role_balances.items() if balance > 0}
    if not active:
        return ft.Text("No balance to chart.", color=ft.Colors.OUTLINE)
    items = sorted(active.items(), key=lambda kv: kv[1], reverse=True)
    max_value = max(value for _, value in items)
    groups = [
        fc.BarChartGroup(
            x=index,
            rods=[
                fc.BarChartRod(
                    to_y=value,
                    width=18,
                    color=palette.get(role, ft.Colors.BLUE_GREY_300),
                    border_radius=4,
                    tooltip=f"{role}: {value:,.2f} SUI",
                )
            ],
        )
        for index, (role, value) in enumerate(items)
    ]
    labels = [
        fc.ChartAxisLabel(value=index, label=ft.Text(role[:8], size=9)) for index, (role, _) in enumerate(items)
    ]
    return ft.Column(
        [
            ft.Text("Total balance by role (SUI)", size=13, weight=ft.FontWeight.BOLD),
            fc.BarChart(
                groups=groups,
                max_y=max_value * 1.15,
                interactive=True,
                left_axis=fc.ChartAxis(label_size=36),
                bottom_axis=fc.ChartAxis(labels=labels, label_size=24),
                height=200,
            ),
        ]
    )


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


def _render_move_fields(fields: dict, page: ft.Page) -> ft.Control:
    return ft.Column([_render_field_row(key, value, page) for key, value in fields.items()], spacing=8, tight=True)


def _render_field_row(key: str, value: object, page: ft.Page) -> ft.Control:
    return ft.Row(
        [
            ft.Container(ft.Text(key, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.OUTLINE), width=190),
            ft.Container(_render_move_value(value, page), expand=True),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def _render_move_value(value: object, page: ft.Page) -> ft.Control:
    """Generic Move-JSON-to-widget renderer -- works for any shared object's
    fetched `fields` dict without hardcoding each of the 11 structs' shapes.
    Table<K, V>/VecSet contents live in separate on-chain dynamic-field
    objects and aren't inlined by `sui client object`, so a Table shows its
    entry count rather than a fabricated list of entries."""
    if value is None:
        return ft.Text("null", italic=True, size=12, color=ft.Colors.OUTLINE)
    if isinstance(value, bool):
        return status_badge("true" if value else "false", "success" if value else "neutral")
    if isinstance(value, (int, float)):
        return ft.Text(f"{value:,}", size=12, selectable=True)
    if isinstance(value, str):
        if value.startswith("0x") and len(value) > 20:
            return copyable_id(value, page)
        if value.isdigit() and len(value) > 3:
            return ft.Text(f"{int(value):,}", size=12, selectable=True)
        return ft.Text(value or "-", size=12, selectable=True)
    if isinstance(value, dict):
        if "fields" in value and isinstance(value["fields"], dict):
            inner = value["fields"]
            if "size" in inner and "id" in inner:
                return ft.Text(
                    f"Table -- {inner.get('size')} entrie(s) (stored as on-chain dynamic fields, not expanded here)",
                    size=12,
                    italic=True,
                    color=ft.Colors.OUTLINE,
                )
            return ft.Container(
                padding=ft.Padding.only(left=10),
                border=ft.Border.only(left=ft.BorderSide(2, ft.Colors.OUTLINE_VARIANT)),
                content=_render_move_fields(inner, page),
            )
        return ft.Container(
            padding=ft.Padding.only(left=10),
            border=ft.Border.only(left=ft.BorderSide(2, ft.Colors.OUTLINE_VARIANT)),
            content=_render_move_fields(value, page),
        )
    if isinstance(value, list):
        if not value:
            return ft.Text("(empty)", italic=True, size=12, color=ft.Colors.OUTLINE)
        if all(isinstance(item, (str, int, float, bool)) for item in value):
            shown = value[:20]
            chips: list[ft.Control] = [ft.Chip(label=ft.Text(str(item)[:24], size=11)) for item in shown]
            if len(value) > len(shown):
                chips.append(ft.Text(f"+{len(value) - len(shown)} more", size=11, color=ft.Colors.OUTLINE))
            return ft.Row(chips, wrap=True, spacing=4)
        return ft.Column([_render_move_value(item, page) for item in value[:20]], spacing=6, tight=True)
    return ft.Text(str(value), size=12, selectable=True)


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
