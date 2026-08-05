from __future__ import annotations

from datetime import datetime

import flet as ft
import flet_charts as fc

from ...widgets import copyable_id, status_badge

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
    ("ROOM_HEALTH_ALERT_BOX_ID", "RoomHealthAlertBox", ft.Icons.MONITOR_HEART),
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
}
FREE_COLOR = ft.Colors.GREY_400
RETIRED_COLOR = ft.Colors.RED_300
IDLE_COLOR = ft.Colors.GREY_600

WALLET_FILTERS = ["All", "Free", "Retired"] + list(ROLE_COLORS.keys())


def _wallet_status_key(entry: dict) -> str:
    if entry.get("retired"):
        return "retired"
    if entry.get("registered_role"):
        return entry["registered_role"]
    return "free"


def _chart_status_key(entry: dict) -> str:
    """Role bucket for the two summary charts only (see _wallet_status_key
    for the wallet table/filter's role-pinned semantics, which intentionally
    keeps idle-but-role-pinned wallets under their role name).

    `registered_role` is permanent once set (see pool.py's checkout_wallet
    docstring) and survives release_wallet(), so a pool sized for a larger
    past scenario leaves plenty of role-pinned wallets sitting unassigned.
    Counting those under their role name here would make the charts look
    like that many workers are currently running, when they're just idle
    pool inventory -- so only a wallet with a live assigned_host counts
    toward its role; everything else idle (but not retired) buckets into
    "idle" instead.
    """
    if entry.get("retired"):
        return "retired"
    if entry.get("assigned_host"):
        return entry.get("registered_role") or "free"
    if entry.get("registered_role"):
        return "idle"
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


def _role_pie_chart(role_counts: dict[str, int]) -> ft.Control:
    if not role_counts:
        return ft.Text("No wallets to chart.", color=ft.Colors.OUTLINE)
    palette = {**ROLE_COLORS, "free": FREE_COLOR, "retired": RETIRED_COLOR, "unassigned": FREE_COLOR, "idle": IDLE_COLOR}
    total = sum(role_counts.values())
    # Largest slice first so small ones (e.g. a lone bot/prometheus
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
    palette = {**ROLE_COLORS, "free": FREE_COLOR, "retired": RETIRED_COLOR, "unassigned": FREE_COLOR, "idle": IDLE_COLOR}
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
