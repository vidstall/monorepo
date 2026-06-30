from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from cli.scenario.context import ScenarioContext


class _WalletsMixin:

    def sleep(self: ScenarioContext, seconds: float, reason: str = "") -> None:
        label = f"wait {seconds}s" + (f" ({reason})" if reason else "")
        self.log(label)
        if not self.dry_run:
            time.sleep(seconds)

    def ensure_wallet(self: ScenarioContext, entity_id: str) -> tuple:
        if self.dry_run:
            return ("0x" + "00" * 32, True)

        scenario_key = f"{self.report.scenario_name}/{self.topology.contract_network}"
        memo = self._load_wallet_memo()
        existing = memo.get(scenario_key, {}).get(entity_id, "")
        if existing:
            self.log(f"wallet reused: {existing} ({entity_id})")
            return (existing, False)

        addr = self._create_new_wallet(entity_id)
        memo.setdefault(scenario_key, {})[entity_id] = addr
        self._save_wallet_memo()
        return (addr, True)

    def create_wallet(self: ScenarioContext, entity_id: str = "") -> str:
        if self.dry_run:
            return "0x" + "00" * 32

        if entity_id:
            addr, _ = self.ensure_wallet(entity_id)
            return addr

        return self._create_new_wallet(entity_id)

    def _create_new_wallet(self: ScenarioContext, entity_id: str = "") -> str:
        output = self.sui_cli(["client", "new-address", "ed25519", "--json"], capture=True)
        try:
            data = json.loads(output or "{}")
            addr = data.get("address") or data.get("suiAddress") or ""
            if addr:
                self.log(f"wallet created: {addr}" + (f" ({entity_id})" if entity_id else ""))
                return addr
        except Exception:
            pass
        raise SystemExit("Could not parse address from sui client new-address output")

    def fund_wallet(self: ScenarioContext, address: str, amount_mist: int) -> None:
        self.sui_cli([
            "client", "ptb",
            "--split-coins", "gas", f"[{amount_mist}]",
            "--assign", "fund_coin",
            "--transfer-objects", "[fund_coin.0]", f"@{address}",
            "--gas-budget", "10000000",
        ])

    def wallet_balance(self: ScenarioContext, address: str) -> int:
        if self.dry_run:
            return 0
        output = self.sui_cli(["client", "gas", "--json", address], capture=True)
        try:
            coins = json.loads(output or "[]")
        except json.JSONDecodeError:
            return 0
        return sum(int(coin.get("mistBalance", 0)) for coin in coins)

    def ensure_wallet_funded(
        self: ScenarioContext,
        address: str,
        min_balance_mist: int,
        top_up_mist: int,
        label: str = "",
    ) -> None:
        balance = self.wallet_balance(address)
        if balance >= min_balance_mist:
            suffix = f" ({label})" if label else ""
            self.log(f"wallet funded: {address[:12]}... balance={balance} MIST{suffix}")
            return

        amount = max(top_up_mist, min_balance_mist - balance)
        self.fund_wallet(address, amount)
        suffix = f" ({label})" if label else ""
        self.log(f"funded: {address[:12]}... +{amount} MIST{suffix}")

    def sui_cli(self: ScenarioContext, args: List[str], capture: bool = False, as_address: str = "") -> Optional[str]:
        import shlex

        from cli.env import build_contract_env

        if not self._env:
            self._env = build_contract_env(self.topology.contract_network)

        deployer = self._env.get("CONTRACT_DEPLOYER_ADDRESS", "")

        if as_address and not self.dry_run:
            self.log(f"$ sui client switch --address {as_address}")
            subprocess.run(
                ["sui", "client", "switch", "--address", as_address],
                env=self._env,
                check=True,
                capture_output=True,
                text=True,
            )

        cmd = ["sui"] + args
        self.log(f"$ {shlex.join(cmd)}")
        if self.dry_run:
            return None

        stdout: Optional[str] = None
        try:
            result = subprocess.run(
                cmd,
                env=self._env,
                capture_output=capture,
                text=True,
                check=True,
            )
            stdout = result.stdout if capture else None
        except subprocess.CalledProcessError as exc:
            if exc.stdout:
                print(exc.stdout, end="", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, end="", file=sys.stderr)
            raise
        finally:
            if as_address and deployer and not self.dry_run:
                subprocess.run(
                    ["sui", "client", "switch", "--address", deployer],
                    env=self._env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
        return stdout

    def contract_env(self: ScenarioContext) -> Dict[str, str]:
        if not self._env:
            from cli.env import build_contract_env
            self._env = build_contract_env(self.topology.contract_network)
        return dict(self._env)

    def _contract_package_id(self: ScenarioContext) -> str:
        return self.contract_env().get("CONTRACT_PACKAGE_ID", "0x0")

    def _contract_registry_id(self: ScenarioContext) -> str:
        return self.contract_env().get("CONTRACT_REGISTRY_OBJECT_ID", "0x0")
