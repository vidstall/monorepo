from __future__ import annotations

import argparse

from .. import image_bake


def add_utils_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("utils", help="Operational utilities (golden-image baking, etc).")
    actions = parser.add_subparsers(dest="action", required=True)

    bake_parser = actions.add_parser(
        "image-bake",
        help="Bake a Docker-preinstalled golden image for one provider+region.",
    )
    bake_parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(image_bake.SUPPORTED_PROVIDERS),
        help="Cloud provider to bake an image for.",
    )
    bake_parser.add_argument(
        "--region",
        required=True,
        help="Provider region/zone to bake into (e.g. us-east-1, eastus, cn-hangzhou, nyc3).",
    )
    bake_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm provisioning a temporary VM and creating a billable cloud image.",
    )
    bake_parser.set_defaults(handler=lambda args: image_bake.bake(args.provider, args.region, args.yes))

    image_parser = actions.add_parser("image", help="Inspect baked golden images.")
    image_actions = image_parser.add_subparsers(dest="image_action", required=True)
    list_parser = image_actions.add_parser("list", help="List all baked images and their (provider, region).")
    list_parser.set_defaults(handler=lambda _args: image_bake.list_images())
