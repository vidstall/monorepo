"""Full worker economic lifecycle: varying stakes, serve rooms with WebRTC, two exit paths."""
from cli.scenario import Topology, ScenarioContext

NAME = "worker-lifecycle"
DESCRIPTION = "Workers register with varying stakes, serve rooms with real WebRTC, exit via withdraw_stake vs unregister"
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.t5-lc1m1.small",
    worker_nodes=4,
    dist_nodes=1,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="devnet",
    deploy_contract=True,
    teardown=True,
    session_duration_secs=5,
    benchmark_targets={
        "register_worker": 3000,
        "order_room": 5000,
        "worker_vote_room": 2000,
        "join_room": 4000,
        "withdraw_stake": 2000,
        "unregister_worker": 2000,
    },
)


def run(ctx: ScenarioContext) -> None:
    ctx.add_worker("worker-1", address="0xW1")
    ctx.add_worker("worker-2", address="0xW2")
    ctx.add_worker("worker-3", address="0xW3")
    ctx.add_worker("worker-4", address="0xW4")
    ctx.add_client("client-1", address="0xC1")

    ctx.step("Workers register with varying stakes")
    ctx.register_worker("worker-1", stake=1000)
    ctx.register_worker("worker-2", stake=2000)
    ctx.register_worker("worker-3", stake=5000)
    ctx.register_worker("worker-4", stake=1000)

    ctx.step("Client orders room 1")
    ctx.order_room("client-1", room_name="lifecycle-room-1", capacity=6, payment=500)

    ctx.step("Workers vote to assign Worker A")
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-4", voter_node_id=4, rental_id=1, nominee_node_id=1)

    ctx.step("4 users join room 1 via WebRTC")
    for i in range(1, 5):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="lifecycle-room-1")
        ctx.join_room(uid, rental_id=1)

    ctx.sleep(5, "conference on lifecycle-room-1")

    ctx.step("Users leave room 1")
    for i in range(1, 5):
        ctx.leave_room(f"user-{i}")

    ctx.step("Client completes rental 1")
    ctx.complete_rental("client-1", rental_id=1)

    ctx.step("Worker B exits via withdraw_worker_stake")
    ctx.deactivate_worker("worker-2")
    ctx.withdraw_worker_stake("worker-2")

    ctx.step("Worker C exits via unregister_worker")
    ctx.deactivate_worker("worker-3")
    ctx.unregister_worker("worker-3")

    ctx.step("Client orders room 2 (only Workers A + D remain)")
    ctx.order_room("client-1", room_name="lifecycle-room-2", capacity=4, payment=500)

    ctx.step("Both remaining workers vote to assign Worker D")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=2, nominee_node_id=4)
    ctx.worker_vote_room("worker-4", voter_node_id=4, rental_id=2, nominee_node_id=4)

    ctx.step("2 users join room 2 via WebRTC")
    for i in range(5, 7):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="lifecycle-room-2")
        ctx.join_room(uid, rental_id=2)

    ctx.sleep(5, "conference with reduced worker pool")

    ctx.step("Users leave room 2")
    ctx.leave_room("user-5")
    ctx.leave_room("user-6")

    ctx.step("Client completes rental 2")
    ctx.complete_rental("client-1", rental_id=2)

    ctx.step("Remaining workers deactivate and withdraw stake")
    ctx.deactivate_worker("worker-1")
    ctx.withdraw_worker_stake("worker-1")
    ctx.deactivate_worker("worker-4")
    ctx.withdraw_worker_stake("worker-4")
