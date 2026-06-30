from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping

from cli.config import TERRAFORM_ENV_DIR
from cli.process import run_command


def provider_terraform_root(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider


def terraform_args(
    testbed_name: str,
    worker_nodes: int,
    dist_nodes: int,
    vclient_nodes: int,
    coordinator_nodes: int,
    node_registry_contract_id: str | None,
) -> List[str]:
    args = [
        "-input=false",
        f"-var=testbed_name={testbed_name}",
        f"-var=worker_count={worker_nodes}",
        f"-var=dist_count={dist_nodes}",
        f"-var=vclient_count={vclient_nodes}",
        f"-var=coordinator_count={coordinator_nodes}",
    ]
    if node_registry_contract_id is not None:
        args.append(f"-var=node_registry_contract_id={node_registry_contract_id}")
    return args


def terraform_init(provider: str, env: Mapping[str, str]) -> None:
    run_command(["terraform", "init", "-input=false"], cwd=provider_terraform_root(provider), env=env)


def terraform_apply(provider: str, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    run_command(
        [
            "terraform",
            "apply",
            "-auto-approve",
            *terraform_args(
                testbed_name=args.testbed_name,
                worker_nodes=args.worker_nodes,
                dist_nodes=args.dist_nodes,
                vclient_nodes=getattr(args, "vclient_nodes", 0),
                coordinator_nodes=args.coordinator_nodes,
                node_registry_contract_id=args.node_registry_contract_id,
            ),
        ],
        cwd=root,
        env=env,
    )


def terraform_destroy(provider: str, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    run_command(
        [
            "terraform",
            "destroy",
            "-auto-approve",
            *terraform_args(
                testbed_name=args.testbed_name,
                worker_nodes=args.worker_nodes,
                dist_nodes=args.dist_nodes,
                vclient_nodes=getattr(args, "vclient_nodes", 0),
                coordinator_nodes=args.coordinator_nodes,
                node_registry_contract_id=args.node_registry_contract_id,
            ),
        ],
        cwd=root,
        env=env,
    )


def terraform_output(provider: str, env: Mapping[str, str]) -> Dict[str, object]:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    completed = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(root),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def terraform_value(outputs: Mapping[str, object], name: str) -> object:
    output = outputs.get(name)
    if not isinstance(output, dict) or "value" not in output:
        raise SystemExit(f"Terraform output did not include {name}")
    return output["value"]


def purge_terraform_state(root: Path) -> None:
    tf_dir = root / ".terraform"
    if tf_dir.exists():
        import shutil
        shutil.rmtree(tf_dir)
        print(f"  removed {tf_dir}")
    for pattern in ("*.tfstate", "*.tfstate.*", ".terraform.lock.hcl"):
        for f in root.glob(pattern):
            f.unlink()
            print(f"  removed {f}")
