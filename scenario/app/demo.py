"""Full product demo — workers register, client rents a room, users join via WebRTC, session, complete."""
from pathlib import Path

from cli.scenario import ScenarioContext, Topology

_VIDEO_FILE = str(Path(__file__).resolve().parents[2] / "video" / "Never-Gonna-Give-You-Up-1080p.mp4")

NAME = "app-demo"
DESCRIPTION = "End-to-end product walkthrough: 3 workers, 1 client, 5 WebRTC users, 300 s session, rental completed"

TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type=None,
    worker_nodes=3,
    dist_nodes=1,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="devnet",
    deploy_contract=True,
    teardown=True,
    registry_init=True,
    registry_build=True,
    session_duration_secs=300,
    benchmark_targets={},
)


def run(ctx: ScenarioContext) -> None:
    ctx.step("Create per-worker wallets")
    w1_addr, w1_new = ctx.ensure_wallet("worker-1")
    w2_addr, w2_new = ctx.ensure_wallet("worker-2")
    w3_addr, w3_new = ctx.ensure_wallet("worker-3")
    # Fund each wallet with 0.05 SUI for gas only on first creation
    for addr, is_new, label in [
        (w1_addr, w1_new, "worker-1"),
        (w2_addr, w2_new, "worker-2"),
        (w3_addr, w3_new, "worker-3"),
    ]:
        if is_new:
            ctx.fund_wallet(addr, 50_000_000)
            ctx.log(f"funded: {addr[:12]}… ({label})")
        else:
            ctx.log(f"skipped funding: {addr[:12]}… ({label}, existing wallet)")

    ctx.step("Workers come online")
    ctx.add_worker("worker-1", address=w1_addr)
    ctx.add_worker("worker-2", address=w2_addr)
    ctx.add_worker("worker-3", address=w3_addr)
    w1_id = ctx.register_worker("worker-1", price_per_rental=400, stake=1000)
    ctx.log(f"worker-1 registered — node_id={w1_id}, price 400, stake 1000")
    w2_id = ctx.register_worker("worker-2", price_per_rental=350, stake=1000)
    ctx.log(f"worker-2 registered — node_id={w2_id}, price 350, stake 1000")
    w3_id = ctx.register_worker("worker-3", price_per_rental=500, stake=1000)
    ctx.log(f"worker-3 registered — node_id={w3_id}, price 500, stake 1000")

    ctx.step("Client rents a room")
    ctx.add_client("client-1", address="")
    rental_id = ctx.order_room("client-1", room_name="demo-room", capacity=5, payment=500)
    ctx.log(f"room ordered — rental_id={rental_id}, name=demo-room, capacity=5, escrowed payment=500")

    ctx.step("Workers vote to assign the room")
    # Each worker signs from its own wallet — votes are unique per sender.
    # Quorum: nominee_votes * 2 > active_worker_count → 2*2 > 3 → true after vote 2.
    ctx.worker_vote_room("worker-1", voter_node_id=w1_id, rental_id=rental_id, nominee_node_id=w1_id)
    ctx.log("worker-1 voted: nominated worker-1 (1/3)")
    ctx.worker_vote_room("worker-2", voter_node_id=w2_id, rental_id=rental_id, nominee_node_id=w1_id)
    ctx.log("worker-2 voted: nominated worker-1 (2/3) — quorum reached, worker-1 assigned")

    ctx.step("5 users join the conference via WebRTC")
    for i in range(1, 6):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="demo-room")
        # 1 in every 5 users streams the video file; the rest publish mock green frames
        video_file = _VIDEO_FILE if i % 5 == 1 else None
        ctx.join_room(uid, rental_id=rental_id, video_file=video_file)
        ctx.log(f"{uid} connected to demo-room" + (" (streaming video)" if video_file else ""))

    ctx.step("Conference in progress")
    ctx.sleep(ctx.topology.session_duration_secs, "participants exchanging audio and video")

    ctx.step("Users leave the conference")
    for i in range(1, 6):
        ctx.leave_room(f"user-{i}")
        ctx.log(f"user-{i} disconnected")

    ctx.step("Client completes the rental — payment released to worker-1")
    ctx.complete_rental("client-1", rental_id=rental_id)
    ctx.log("rental completed, escrowed funds released to worker-1")

    ctx.step("Workers wind down")
    ctx.deactivate_worker("worker-1")
    ctx.deactivate_worker("worker-2")
    ctx.deactivate_worker("worker-3")
    ctx.unregister_worker("worker-1")
    ctx.log("worker-1 unregistered and stake withdrawn")
    ctx.unregister_worker("worker-2")
    ctx.log("worker-2 unregistered and stake withdrawn")
    ctx.unregister_worker("worker-3")
    ctx.log("worker-3 unregistered and stake withdrawn")
