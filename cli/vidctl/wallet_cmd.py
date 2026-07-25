from __future__ import annotations

import argparse

from .. import wallet


def add_wallet_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("wallet", help="Inspect the operator-wallet pool (read-only; never prints secrets).")
    actions = parser.add_subparsers(dest="action", required=True)

    list_parser = actions.add_parser("list", help="List pooled wallets and free/assigned counts.")
    list_parser.add_argument(
        "--env",
        choices=["devnet", "testnet", "mainnet"],
        default=None,
        help="Restrict to one Sui env. Default: all envs with a pool file.",
    )
    list_parser.set_defaults(handler=lambda args: wallet.list_pool(args.env))

    gc_parser = actions.add_parser(
        "gc",
        help="Release wallets assigned to workers no longer present in the topology.",
    )
    gc_parser.set_defaults(handler=lambda _args: wallet.gc())

    retire_parser = actions.add_parser(
        "retire",
        help=(
            "Permanently exclude a pooled wallet from future checkouts (e.g. its "
            "miner_id has a permanent on-chain degraded/slashed history) and "
            "release it from whatever worker currently holds it."
        ),
    )
    retire_parser.add_argument("wallet", help="Wallet alias or address to retire.")
    retire_parser.add_argument(
        "--env",
        choices=["devnet", "testnet", "mainnet"],
        default="devnet",
        help="Sui env the wallet pool belongs to. Default: devnet.",
    )
    retire_parser.add_argument("--reason", default="", help="Optional note, e.g. 'NodeDegraded level=2'.")
    retire_parser.set_defaults(handler=lambda args: wallet.retire(args.wallet, args.env, args.reason))
