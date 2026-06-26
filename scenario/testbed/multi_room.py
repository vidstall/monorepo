"""Multiple concurrent rooms: voting + direct hire, cancel, re-order with real WebRTC."""
from cli.scenario import Topology, ScenarioContext

NAME = "multi-room"
DESCRIPTION = "2 clients run separate rooms concurrently with real WebRTC, cancel one, re-order cheaper"
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.t5-lc1m1.small",
    worker_nodes=3,
    dist_nodes=1,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="testnet",
    deploy_contract=True,
    teardown=True,
    session_duration_secs=5,
    benchmark_targets={
        "register_worker": 3000,
        "order_room": 5000,
        "hire_worker": 3000,
        "worker_vote_room": 2000,
        "join_room": 4000,
        "cancel_rental": 2000,
    },
)


def run(ctx: ScenarioContext) -> None:
    ctx.add_worker("worker-1", address="0xW1")
    ctx.add_worker("worker-2", address="0xW2")
    ctx.add_worker("worker-3", address="0xW3")
    ctx.add_client("client-1", address="0xC1")
    ctx.add_client("client-2", address="0xC2")

    ctx.step("Workers register with varying prices")
    ctx.register_worker("worker-1", price_per_rental=300)
    ctx.register_worker("worker-2", price_per_rental=500)
    ctx.register_worker("worker-3", price_per_rental=200)

    ctx.step("Client 1 orders room-alpha via voting")
    ctx.order_room("client-1", room_name="room-alpha", capacity=4, payment=500)

    ctx.step("Client 2 directly hires Worker B for room-beta")
    ctx.hire_worker("client-2", worker_node_id=2, room_name="room-beta", capacity=4, payment=500)

    ctx.step("Workers vote to assign Worker A to room-alpha")
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=1, nominee_node_id=1)

    ctx.step("3 users join room-alpha via WebRTC")
    for i in range(1, 4):
        uid = f"user-a{i}"
        ctx.add_user(uid, room_name="room-alpha")
        ctx.join_room(uid, rental_id=1)

    ctx.step("3 users join room-beta via WebRTC")
    for i in range(1, 4):
        uid = f"user-b{i}"
        ctx.add_user(uid, room_name="room-beta")
        ctx.join_room(uid, rental_id=2)

    ctx.step("Both rooms active concurrently")
    ctx.sleep(5, "two rooms active with 6 WebRTC connections")

    ctx.step("Users leave room-beta, client 2 cancels (refund)")
    for i in range(1, 4):
        ctx.leave_room(f"user-b{i}")
    ctx.cancel_rental("client-2", rental_id=2)

    ctx.step("Client 2 re-orders room-gamma at lower price via voting")
    ctx.order_room("client-2", room_name="room-gamma", capacity=4, payment=200)

    ctx.step("Workers vote to assign Worker C to room-gamma")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=3, nominee_node_id=3)
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=3, nominee_node_id=3)

    ctx.step("2 users join room-gamma while room-alpha still active")
    for i in range(1, 3):
        uid = f"user-g{i}"
        ctx.add_user(uid, room_name="room-gamma")
        ctx.join_room(uid, rental_id=3)

    ctx.sleep(3, "two rooms active")

    ctx.step("All users leave")
    for i in range(1, 4):
        ctx.leave_room(f"user-a{i}")
    for i in range(1, 3):
        ctx.leave_room(f"user-g{i}")

    ctx.step("Both clients complete their active rentals")
    ctx.complete_rental("client-1", rental_id=1)
    ctx.complete_rental("client-2", rental_id=3)
