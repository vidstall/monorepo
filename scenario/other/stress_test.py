"""High-load stress test: 10 concurrent rooms, 5 users each, 30s sessions."""
from cli.scenario import Topology, ScenarioContext

NAME = "stress-test"
DESCRIPTION = "10 concurrent rooms with 5 users each to stress-test SFU and coordinator."
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.c6.xlarge",
    media_nodes=5,
    routes_nodes=2,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="devnet",
    deploy_contract=True,
    teardown=True,
    session_duration_secs=30,
    benchmark_targets={
        "order_room": 5000,
        "worker_vote_room": 2000,
        "join_room": 4000,
    },
)


def run(ctx: ScenarioContext) -> None:
    ctx.step("Register 5 workers")
    for i in range(1, 6):
        ctx.add_worker(f"worker-{i}", address=f"0xW{i}")
        ctx.register_worker(f"worker-{i}")

    ctx.add_client("client-1", address="0xC1")
    ctx.add_client("client-2", address="0xC2")

    ctx.step("Order 10 concurrent rooms")
    for i in range(1, 11):
        client = "client-1" if i <= 5 else "client-2"
        ctx.order_room(client, room_name=f"stress-room-{i}", capacity=5, payment=200)

    ctx.step("Vote to assign workers")
    for rental_id in range(1, 11):
        nominee = ((rental_id - 1) % 5) + 1
        ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=rental_id, nominee_node_id=nominee)
        ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=rental_id, nominee_node_id=nominee)

    ctx.step("50 users join across 10 rooms")
    for room_i in range(1, 11):
        for user_i in range(1, 6):
            uid = f"user-r{room_i}-{user_i}"
            ctx.add_user(uid, room_name=f"stress-room-{room_i}")
            ctx.join_room(uid, rental_id=room_i)

    ctx.step("Hold concurrent sessions")
    ctx.sleep(ctx.topology.session_duration_secs, "stress test in progress")

    ctx.step("All users leave")
    for room_i in range(1, 11):
        for user_i in range(1, 6):
            ctx.leave_room(f"user-r{room_i}-{user_i}")

    ctx.step("Complete all rentals")
    for rental_id in range(1, 11):
        client = "client-1" if rental_id <= 5 else "client-2"
        ctx.complete_rental(client, rental_id=rental_id)
