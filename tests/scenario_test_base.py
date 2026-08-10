from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import contract, context, image_bake, infra, observer, registry, scenario
from cli import object as object_cmd
from cli.registry import RegistryState
from cli.scenario import system_log

FAKE_WALLET = {"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SCENARIO_TOML = """
name = "baseline-devnet"
env = "devnet"

[[workers]]
host = "001"
service = "cp-daemon"
provider = "digitalocean"
size = "s-1vcpu-1gb"

[[workers]]
host = "001"
service = "relay"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""

SCENARIO_TOML_ONE_INSTANCE = """
name = "baseline-devnet-small"
env = "devnet"

[[workers]]
host = "001"
service = "cp-daemon"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""


class ScenarioTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topology = self.root / "runtime" / "topology.toml"
        self.history = self.root / "runtime" / "history.toml"
        self.lock = self.root / "runtime" / "scenario.lock"
        self.contract_env = self.root / "runtime" / "contract" / "devnet.env"
        _write(
            self.contract_env,
            "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
        )
        self.scenario_dir = self.root / "scenario"
        self.scenario_dir.mkdir(parents=True, exist_ok=True)

        self.patches = [
            patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
            patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
            patch.object(infra, "contract_env_path", lambda _env: self.contract_env),
            patch.object(scenario, "contract_env_path", lambda _env: self.contract_env),
            patch.object(scenario, "RUNTIME_SCENARIO_LOCK", self.lock),
            patch.object(infra, "command_env", return_value={"DIGITALOCEAN_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=0),
            patch.object(infra, "persist_vm_resolution", return_value=None),
            patch.object(infra, "GENERATED_INVENTORY", self.root / "runtime" / "hosts.generated.yml"),
            # No observer host registered by default -- apply()/destroy()'s
            # best-effort observer refresh/cleanup should be a silent no-op
            # for every test in this file unless a test explicitly registers
            # one. Isolated from the real repo's runtime/observer.toml so
            # these tests never depend on (or corrupt) real operator state.
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            # set_vm_defaults()'s ensure_ssh_keypair() does real ssh-keygen
            # file I/O against SSH_KEY_ROOT regardless of the pulumi_up/
            # inventory/configure mocks above -- these scenarios use worker
            # host "node-1", which collides with a real deployed worker
            # host. Without this, running this suite regenerates the REAL
            # runtime/ssh_key/node-1 keypair, orphaning SSH access to an
            # actually-running droplet.
            patch.object(infra, "SSH_KEY_ROOT", self.root / "runtime" / "ssh_key"),
            patch.object(image_bake, "ensure_image", return_value=(True, "")),
            # Best-effort contract-state push to whichever observer host runs
            # pushgateway (see apply()'s _push_contract_state()) -- stubbed
            # for every test in this file by default, same rationale as the
            # observer-deploy stub above: no registered host means it's never
            # actually called, and tests that DO register one shouldn't pay
            # for a real wallet-pool/on-chain read against this fake env.
            patch.object(observer, "export_contract_state", return_value=0),
            # Best-effort browser-env sync (see apply()'s
            # _sync_client_observability_env()) -- stubbed for every test in
            # this file by default, same rationale as the export_contract_state
            # stub above: no registered host means it's never actually called,
            # and tests that DO register one shouldn't write real secrets/
            # services/client/client/.env files as a side effect.
            patch.object(observer, "sync_client_observability_env", return_value=0),
            # Isolated from the real repo's logs/ dir so `scenario.run()`
            # tests never write files outside this test's tempdir; the
            # snapshot itself is stubbed too since capture_system_snapshot()
            # would otherwise make real SSH/HTTP/on-chain calls against this
            # fake env on every action -- tests exercising the real snapshot
            # behavior patch this back per-test.
            patch.object(context, "LOGS_ROOT", self.root / "logs"),
            patch.object(system_log, "capture_system_snapshot", return_value={"stub": True}),
            patch("cli.wallet.checkout_wallet", return_value=(dict(FAKE_WALLET), False)),
            patch("cli.wallet.release_wallet", return_value=None),
            patch.object(contract, "publish", return_value=0),
            patch.object(registry, "publish", return_value=0),
            patch.object(registry, "login", return_value=0),
            patch.object(object_cmd, "publish", return_value=0),
            patch.object(
                registry,
                "read_runtime_registry",
                return_value=RegistryState(
                    provider="digitalocean",
                    host="registry.digitalocean.com",
                    prefix="registry.digitalocean.com/xaisen",
                    images={s: f"registry.digitalocean.com/xaisen/{s}" for s in infra.DOCKER_SERVICES},
                    deployed={s: "abc1234" for s in infra.DOCKER_SERVICES},
                    digests={},
                ),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def read_topology(self) -> dict:
        return infra.read_topology()

    def write_scenario(self, name: str, content: str) -> Path:
        path = self.scenario_dir / name
        _write(path, content)
        return path
