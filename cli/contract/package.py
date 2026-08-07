from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..context import CONTRACT_CORE_DIR, CONTRACT_ROLE_VOTING_DIR


@dataclass(frozen=True)
class ContractPackage:
    """Describes one of the two published Move packages so the publish/deploy
    tooling (deployment.py/publish_ops.py/publish.py) can be parameterized
    over "which package" instead of hardcoding services/contract everywhere.

    slug: short identifier used in runtime pubfile names (Pub.<env>.<slug>.toml)
    dir: the package's directory (contains Move.toml/sources/tests)
    env_prefix: prefix for this package's keys in runtime/contract/<env>.env
        (e.g. CONTRACT_PACKAGE_ID vs CONTRACT_B_PACKAGE_ID)
    """

    slug: str
    dir: Path
    env_prefix: str


CONTRACT_A = ContractPackage(slug="contract", dir=CONTRACT_CORE_DIR, env_prefix="CONTRACT")
CONTRACT_B = ContractPackage(slug="role-voting", dir=CONTRACT_ROLE_VOTING_DIR, env_prefix="CONTRACT_B")

# Local Move.toml `{ local = ... }` dependencies, keyed by dependent package.
# Used to resolve each dependency's already-published on-chain address into an
# ephemeral pubfile before a devnet publish/upgrade (see deployment.py's
# write_dependency_pubfile/write_runtime_pubfile dependency_packages param) --
# devnet publishes go through `sui client test-publish`/`test-upgrade`, which
# never populates Move.lock's normal [environments] resolution path.
LOCAL_DEPENDENCIES: dict[ContractPackage, tuple[ContractPackage, ...]] = {
    CONTRACT_B: (CONTRACT_A,),
}
