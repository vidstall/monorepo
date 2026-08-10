from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import infra


class InfraTopologyTestCase(unittest.TestCase):
    def setUp(self) -> None:
            import sys
            pulumi_dir = str(Path(__file__).resolve().parent.parent / "IaC" / "pulumi")
            if pulumi_dir not in sys.path:
                sys.path.insert(0, pulumi_dir)

            self.temp = tempfile.TemporaryDirectory()
            self.root = Path(self.temp.name)
            self.topology = self.root / "runtime" / "topology.toml"
            self.history = self.root / "runtime" / "history.toml"
            self.contract = self.root / "runtime" / "contract" / "devnet.env"
            self.contract.parent.mkdir(parents=True, exist_ok=True)
            self.contract.write_text(
                "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
                encoding="utf-8",
            )
            self.patches = [
                patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
                patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
                patch.object(infra, "contract_env_path", lambda _env: self.contract),
                # persist_vm_resolution shells out to `pulumi stack output` for
                # every provider now (generalized from alibaba-only); no test
                # here exercises its real behavior, so mock it out uniformly.
                patch.object(infra, "persist_vm_resolution", return_value=None),
                # Isolate from any real generated inventory left on disk by a
                # manual `vidctl` run -- without this, host_address()/
                # registry_status() can pick up a real stale IP and attempt a
                # real (slow, timing-out) SSH connection.
                patch.object(infra, "GENERATED_INVENTORY", self.root / "runtime" / "hosts.generated.yml"),
                # ensure_ssh_keypair()/control()'s kill path do real filesystem
                # I/O (ssh-keygen, shutil.rmtree) against SSH_KEY_ROOT -- several
                # tests here use worker host "node-1", which collides with a
                # real deployed worker host. Without this patch, running this
                # suite deletes/regenerates the REAL runtime/ssh_key/node-1
                # keypair, orphaning SSH access to an actually-running droplet.
                patch.object(infra, "SSH_KEY_ROOT", self.root / "runtime" / "ssh_key"),
            ]
            for item in self.patches:
                item.start()

    def tearDown(self) -> None:
            for item in reversed(self.patches):
                item.stop()
            self.temp.cleanup()

    def read_topology(self) -> dict:
            return tomllib.loads(self.topology.read_text(encoding="utf-8"))

    def read_history(self) -> dict:
            return tomllib.loads(self.history.read_text(encoding="utf-8"))

