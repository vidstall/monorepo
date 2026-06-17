"""Infrastructure role assignment via worker voting."""
from cli.scenario import Topology, ScenarioContext

NAME = "role-voting"
DESCRIPTION = "4 workers vote to assign SFU, Coordinator, and Router roles, then serve a room"
TOPOLOGY = Topology(worker_nodes=4, client_nodes=1, coordinator_nodes=1, contract_network="testnet")

ROLE_SFU = 0
ROLE_COORDINATOR = 1
ROLE_ROUTER = 2


def run(ctx: ScenarioContext) -> None:
    # --- setup ---
    for i in range(1, 5):
        ctx.add_worker(f"worker-{i}", address=f"0xW{i}")
    ctx.add_client("client-1", address="0xC1")

    # --- step 1: all workers register ---
    ctx.step("Workers A-D register on-chain")
    for i in range(1, 5):
        ctx.register_worker(f"worker-{i}")

    # --- step 2: propose Worker A as SFU ---
    ctx.step("Worker A proposes: Worker A → SFU role")
    ctx.benchmark(
        "propose_role",
        lambda: ctx.sui_cli([
            "client", "call",
            "--package", ctx._contract_package_id(),
            "--module", "node_registry",
            "--function", "propose_role",
            "--type-args", "0x2::sui::SUI",
            "--args",
            ctx._contract_registry_id(),
            "1", "1", str(ROLE_SFU), "0x6",
            "--gas-budget", "100000000",
        ]),
        entity_id="worker-1",
        role="SFU",
        nominee="worker-1",
    )

    # --- step 3: Workers B and C vote (quorum) ---
    ctx.step("Workers B and C vote for SFU proposal (quorum)")
    ctx.worker_vote_role("worker-2", voter_node_id=2, proposal_id=1)
    ctx.worker_vote_role("worker-3", voter_node_id=3, proposal_id=1)

    # --- step 4: propose Worker B as Coordinator ---
    ctx.step("Worker B proposes: Worker B → Coordinator role")
    ctx.benchmark(
        "propose_role",
        lambda: ctx.sui_cli([
            "client", "call",
            "--package", ctx._contract_package_id(),
            "--module", "node_registry",
            "--function", "propose_role",
            "--type-args", "0x2::sui::SUI",
            "--args",
            ctx._contract_registry_id(),
            "2", "2", str(ROLE_COORDINATOR), "0x6",
            "--gas-budget", "100000000",
        ]),
        entity_id="worker-2",
        role="Coordinator",
        nominee="worker-2",
    )

    # --- step 5: Workers A and C vote ---
    ctx.step("Workers A and C vote for Coordinator proposal")
    ctx.worker_vote_role("worker-1", voter_node_id=1, proposal_id=2)
    ctx.worker_vote_role("worker-3", voter_node_id=3, proposal_id=2)

    # --- step 6: propose Worker C as Router ---
    ctx.step("Worker C proposes: Worker C → Router role")
    ctx.benchmark(
        "propose_role",
        lambda: ctx.sui_cli([
            "client", "call",
            "--package", ctx._contract_package_id(),
            "--module", "node_registry",
            "--function", "propose_role",
            "--type-args", "0x2::sui::SUI",
            "--args",
            ctx._contract_registry_id(),
            "3", "3", str(ROLE_ROUTER), "0x6",
            "--gas-budget", "100000000",
        ]),
        entity_id="worker-3",
        role="Router",
        nominee="worker-3",
    )

    # --- step 7: Workers A and B vote ---
    ctx.step("Workers A and B vote for Router proposal")
    ctx.worker_vote_role("worker-1", voter_node_id=1, proposal_id=3)
    ctx.worker_vote_role("worker-2", voter_node_id=2, proposal_id=3)

    # --- step 8: client orders room ---
    ctx.step("Client orders room (Worker A is the SFU)")
    ctx.order_room("client-1", room_name="role-room-1", capacity=8, payment=500)

    # --- step 9: vote to assign room to Worker A (the SFU) ---
    ctx.step("Workers vote to assign room to Worker A")
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-4", voter_node_id=4, rental_id=1, nominee_node_id=1)

    # --- step 10: users join ---
    ctx.step("4 users join the room")
    for i in range(1, 5):
        ctx.add_user(f"user-{i}", room_name="role-room-1")
        ctx.join_room(f"user-{i}")

    ctx.sleep(3, "simulate conference session")

    # --- step 11: users leave ---
    ctx.step("All users leave")
    for i in range(1, 5):
        ctx.leave_room(f"user-{i}")

    # --- step 12: complete rental ---
    ctx.step("Client completes the rental")
    ctx.complete_rental("client-1", rental_id=1)
