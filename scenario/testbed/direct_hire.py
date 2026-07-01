"""Direct hire vs voting: side-by-side benchmark with real WebRTC connections."""
from cli.scenario import Topology, ScenarioContext

NAME = "direct-hire"
DESCRIPTION = "Compare direct-hire vs vote-based assignment, both with real WebRTC sessions"
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
        "hire_worker": 3000,
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

    # --- Direct hire path ---
    ctx.step("Client directly hires Worker A (bypasses voting)")
    ctx.hire_worker("client-1", worker_node_id=1, room_name="direct-room", capacity=8, payment=500)

    ctx.step("4 users join the directly-hired room via WebRTC")
    for i in range(1, 5):
        uid = f"user-d{i}"
        ctx.add_user(uid, room_name="direct-room")
        ctx.join_room(uid, rental_id=1)

    ctx.step("Worker A updates metadata mid-session")
    ctx.update_worker_metadata("worker-1",
                               metadata_uri="ipfs://xaisen-worker-v2",
                               metadata_hash="0x" + "cd" * 32)

    ctx.sleep(5, "direct-hire conference in progress")

    ctx.step("Users leave the direct-hire room")
    for i in range(1, 5):
        ctx.leave_room(f"user-d{i}")

    ctx.step("Client completes the direct-hire rental")
    ctx.complete_rental("client-1", rental_id=1)

    # --- Voting path for comparison ---
    ctx.step("Client orders room via voting (for latency comparison)")
    ctx.order_room("client-1", room_name="voted-room", capacity=8, payment=500)

    ctx.step("Workers vote to assign Worker B")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=2, nominee_node_id=2)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=2, nominee_node_id=2)

    ctx.step("4 users join the voted room via WebRTC")
    for i in range(1, 5):
        uid = f"user-v{i}"
        ctx.add_user(uid, room_name="voted-room")
        ctx.join_room(uid, rental_id=2)

    ctx.sleep(5, "voted-room conference in progress")

    ctx.step("Users leave the voted room")
    for i in range(1, 5):
        ctx.leave_room(f"user-v{i}")

    ctx.step("Client completes the voted rental")
    ctx.complete_rental("client-1", rental_id=2)
