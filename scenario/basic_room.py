"""Basic room lifecycle: register workers, order room, vote, users join/leave, complete."""
from cli.scenario import Topology, ScenarioContext

NAME = "basic-room"
DESCRIPTION = "3 workers register, client orders a room (capacity=5), workers vote, users join and leave, rental completes"
TOPOLOGY = Topology(worker_nodes=3, client_nodes=1, coordinator_nodes=1, contract_network="testnet")


def run(ctx: ScenarioContext) -> None:
    # --- setup entities ---
    w1 = ctx.add_worker("worker-1", address="0xW1")
    w2 = ctx.add_worker("worker-2", address="0xW2")
    w3 = ctx.add_worker("worker-3", address="0xW3")
    c1 = ctx.add_client("client-1", address="0xC1")

    # --- step 1: workers register ---
    ctx.step("Worker A registers on-chain")
    ctx.register_worker("worker-1")

    ctx.step("Worker B registers on-chain")
    ctx.register_worker("worker-2")

    ctx.step("Worker C registers on-chain")
    ctx.register_worker("worker-3")

    # --- step 4: client orders room ---
    ctx.step("Client orders room with capacity=5")
    rental_id = ctx.order_room("client-1", room_name="xaisen-room-1", capacity=5, payment=500)

    # --- step 5: workers vote ---
    ctx.step("Worker A votes to assign Worker A")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)

    ctx.step("Worker B votes to assign Worker A (quorum reached)")
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)

    # --- step 7: users join ---
    ctx.step("3 users join the room")
    for i in range(1, 4):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="xaisen-room-1")
        ctx.join_room(uid)

    ctx.step("2 more users join (room now at capacity=5)")
    for i in range(4, 6):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="xaisen-room-1")
        ctx.join_room(uid)

    # --- step 9: 6th user rejected ---
    ctx.step("6th user attempts to join (should be rejected at capacity)")
    ctx.add_user("user-6", room_name="xaisen-room-1")
    ctx.join_room("user-6")

    # --- step 10: some users leave ---
    ctx.step("2 users leave the room")
    ctx.sleep(2, "simulate session time")
    ctx.leave_room("user-1")
    ctx.leave_room("user-2")

    # --- step 11: new user joins freed slot ---
    ctx.step("New user joins the freed slot")
    ctx.add_user("user-7", room_name="xaisen-room-1")
    ctx.join_room("user-7")

    # --- step 12: rental completes ---
    ctx.step("Client completes the rental")
    ctx.complete_rental("client-1", rental_id=1)

    # --- step 13: worker unregisters ---
    ctx.step("Worker C unregisters and withdraws stake")
    ctx.deactivate_worker("worker-3")
    ctx.unregister_worker("worker-3")
