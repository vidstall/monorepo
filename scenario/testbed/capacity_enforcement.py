"""Capacity enforcement: fill room with real WebRTC, verify rejection, free slot, rejoin."""
from cli.scenario import Topology, ScenarioContext

NAME = "capacity-enforcement"
DESCRIPTION = "Fill room to capacity=5 with real WebRTC, verify 6th user rejected, free slot, confirm new user can join"
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.t5-lc1m1.small",
    worker_nodes=3,
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
    ctx.order_room("client-1", room_name="cap-room", capacity=5, payment=500)

    ctx.step("Workers vote to assign Worker A")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)

    ctx.step("5 users join via WebRTC (fill to capacity)")
    for i in range(1, 6):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="cap-room")
        ctx.join_room(uid, rental_id=1)

    ctx.step("6th user attempts to join (should be rejected at capacity)")
    ctx.add_user("user-6", room_name="cap-room")
    ctx.join_room("user-6", rental_id=1)
    user_6 = ctx.report.users["user-6"]
    if not ctx.dry_run and not user_6.rejected:
        raise RuntimeError("Expected user-6 to be rejected at capacity")
    ctx.log("PASS: user-6 correctly rejected at capacity")

    ctx.step("User 3 leaves, freeing a slot")
    ctx.leave_room("user-3")

    ctx.step("7th user joins the freed slot")
    ctx.add_user("user-7", room_name="cap-room")
    ctx.join_room("user-7", rental_id=1)
    user_7 = ctx.report.users["user-7"]
    if not ctx.dry_run and user_7.rejected:
        raise RuntimeError("Expected user-7 to join successfully after slot freed")
    ctx.log("PASS: user-7 joined after slot freed")

    ctx.step("All remaining users leave")
    for uid in ("user-1", "user-2", "user-4", "user-5", "user-7"):
        ctx.leave_room(uid)

    ctx.step("Client completes the rental")
    ctx.complete_rental("client-1", rental_id=1)
