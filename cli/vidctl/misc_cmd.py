from __future__ import annotations

import argparse

from .. import object as object_cmd
from .. import registry
from ..context import DOCKER_SERVICES


def add_gui_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    gui_parser = subparsers.add_parser(
        "gui", help="Launch the vidctl desktop GUI (Flet)."
    )
    gui_parser.add_argument(
        "--web",
        action="store_true",
        help="Serve the GUI in a browser tab instead of opening a native desktop window.",
    )
    gui_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to use with --web (default: pick any free port).",
    )

    def run_gui(args: argparse.Namespace) -> int:
        from ..gui.app import run as run_gui_app

        return run_gui_app(args)

    gui_parser.set_defaults(handler=run_gui)


def add_registry_selection(parser: argparse.ArgumentParser) -> None:
    service_group = parser.add_mutually_exclusive_group(required=True)
    service_group.add_argument(
        "--service", choices=sorted(DOCKER_SERVICES), help="Service image to manage."
    )
    service_group.add_argument(
        "--all", action="store_true", help="Manage every service image."
    )
    parser.add_argument(
        "--tag",
        help="Image tag. Default: current git short SHA, or dev outside git history.",
    )


def add_registry_provider(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default=registry.DEFAULT_PROVIDER,
        help="Registry provider env-file basename under secrets/registry. Default: alibaba.",
    )


def add_registry_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "registry", help="Manage Docker images and registry publishing."
    )
    actions = parser.add_subparsers(dest="action", required=True)

    login = actions.add_parser("login", help="Log in to a Docker registry provider.")
    add_registry_provider(login)
    login.set_defaults(handler=lambda args: registry.login(args.provider))

    for action, help_text, handler in (
        ("build", "Build Docker image(s).", registry.build),
        ("push", "Push Docker image(s).", registry.push),
    ):
        item = actions.add_parser(action, help=help_text)
        add_registry_selection(item)
        item.set_defaults(
            handler=lambda args, selected_handler=handler: selected_handler(
                args.service, args.all, args.tag
            )
        )

    publish = actions.add_parser("publish", help="Build and push Docker image(s).")
    add_registry_selection(publish)
    publish.set_defaults(
        handler=lambda args: registry.publish(args.service, args.all, args.tag)
    )


def add_object_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--name", required=True, help="Topology object name (e.g. bucket identity)."
    )
    parser.add_argument(
        "--object",
        required=True,
        choices=sorted(object_cmd.OBJECT_TYPES),
        help="Object type to publish.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(object_cmd.PROVIDERS),
        help="Object-storage provider.",
    )


def add_object_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "object", help="Publish static sites (e.g. the frontend) to object storage."
    )
    actions = parser.add_subparsers(dest="action", required=True)

    publish = actions.add_parser(
        "publish", help="Build and upload a static site to object storage."
    )
    add_object_selection(publish)
    publish.set_defaults(
        handler=lambda args: object_cmd.publish(args.name, args.object, args.provider)
    )

    refresh = actions.add_parser(
        "refresh",
        help="Reconcile Pulumi state with the real bucket contents, then re-apply (fixes objects missing after a partial publish).",
    )
    add_object_selection(refresh)
    refresh.set_defaults(
        handler=lambda args: object_cmd.refresh(args.name, args.object, args.provider)
    )

    clean = actions.add_parser(
        "clean",
        help=(
            "Detect and remove Pulumi state entries for resources that no longer exist remotely (e.g. a "
            "provider erroring 'not found' during refresh instead of dropping it from state itself), then "
            "finish with the normal refresh+publish flow -- no manual `pulumi state delete` needed."
        ),
    )
    add_object_selection(clean)
    clean.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which state entries would be removed without deleting anything or touching Pulumi further.",
    )
    clean.set_defaults(
        handler=lambda args: object_cmd.clean(
            args.name, args.object, args.provider, args.dry_run
        )
    )

    delete = actions.add_parser("delete", help="Delete an object-storage site.")
    add_object_selection(delete)
    delete.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive object-storage deletion.",
    )
    delete.set_defaults(
        handler=lambda args: object_cmd.delete(
            args.name, args.object, args.provider, args.yes
        )
    )
