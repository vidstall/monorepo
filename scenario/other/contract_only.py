"""Contract-only scenario: verify on-chain flows without provisioning any infrastructure."""
from cli.scenario import Topology, ScenarioContext

NAME = "contract-only"
DESCRIPTION = "Register workers and order rooms via Sui CLI only — no infra provisioning required."
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type=None,
    worker_nodes=0,
    dist_nodes=0,
    vclient_nodes=0,
    coordinator_nodes=0,
    contract_network="devnet",
    deploy_contract=False,
    teardown=False,
    session_duration_secs=0,
    benchmark_targets={
        "register_worker": 3000,
        "order_room": 5000,
    },
)


def run(ctx: ScenarioContext) -> None:
    ctx.step("Register a worker on-chain")
    ctx.add_worker("worker-1", address="0xW1")
    ctx.register_worker("worker-1", stake=1000, price_per_rental=500)

    ctx.step("Order a room on-chain")
    ctx.add_client("client-1", address="0xC1")
    ctx.order_room("client-1", room_name="contract-room", capacity=3, payment=500)

    ctx.step("Vote to assign worker")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)

    ctx.step("Complete rental on-chain")
    ctx.complete_rental("client-1", rental_id=1)

    ctx.step("Cleanup: deactivate and unregister worker")
    ctx.deactivate_worker("worker-1")
    ctx.unregister_worker("worker-1")
