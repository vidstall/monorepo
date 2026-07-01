"""Core room lifecycle: register, order, vote, join via WebRTC, session, leave, complete."""
from cli.scenario import Topology, ScenarioContext

NAME = "basic-room"
DESCRIPTION = "Register 3 workers, order a room, vote, 3 users join via WebRTC, hold session, leave, complete rental"
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.t5-lc1m1.small",
    media_nodes=3,
    routes_nodes=1,
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
    },
)


def run(ctx: ScenarioContext) -> None:
    ctx.add_worker("worker-1", address="0xW1")
    ctx.add_worker("worker-2", address="0xW2")
    ctx.add_worker("worker-3", address="0xW3")
    ctx.add_client("client-1", address="0xC1")

    ctx.step("Workers register on-chain")
    ctx.register_worker("worker-1")
    ctx.register_worker("worker-2")
    ctx.register_worker("worker-3")

    ctx.step("Client orders room with capacity=5")
    ctx.order_room("client-1", room_name="basic-room-1", capacity=5, payment=500)

    ctx.step("Workers vote to assign Worker A (quorum=2 of 3)")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)

    ctx.step("3 users join via WebRTC")
    for i in range(1, 4):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="basic-room-1")
        ctx.join_room(uid, rental_id=1)

    ctx.step("Hold conference session")
    ctx.sleep(5, "conference in progress")

    ctx.step("Users leave (WebRTC disconnect)")
    for i in range(1, 4):
        ctx.leave_room(f"user-{i}")

    ctx.step("Client completes the rental")
    ctx.complete_rental("client-1", rental_id=1)

    ctx.step("Worker C unregisters")
    ctx.deactivate_worker("worker-3")
    ctx.unregister_worker("worker-3")
