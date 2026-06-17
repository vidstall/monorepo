"""Worker network dynamics: join, drop, rejoin, unregister permanently."""
from cli.scenario import Topology, ScenarioContext

NAME = "worker-churn"
DESCRIPTION = "5 workers register, some deactivate/reactivate/unregister while rooms are served"
TOPOLOGY = Topology(worker_nodes=5, client_nodes=1, coordinator_nodes=1, contract_network="testnet")


def run(ctx: ScenarioContext) -> None:
    c1 = ctx.add_client("client-1", address="0xC1")

    # --- step 1: all workers register ---
    ctx.step("Workers A-E register on-chain")
    for i in range(1, 6):
        ctx.add_worker(f"worker-{i}", address=f"0xW{i}")
        ctx.register_worker(f"worker-{i}")

    # --- step 2: first room order ---
    ctx.step("Client orders room with capacity=10")
    ctx.order_room("client-1", room_name="churn-room-1", capacity=10, payment=500)

    # --- step 3: vote to assign Worker A ---
    ctx.step("Workers vote to assign Worker A")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=1, nominee_node_id=1)

    # --- step 4: users join ---
    ctx.step("5 users join the room")
    for i in range(1, 6):
        ctx.add_user(f"user-{i}", room_name="churn-room-1")
        ctx.join_room(f"user-{i}")

    # --- step 5: Worker B drops ---
    ctx.step("Worker B deactivates (drops from network)")
    ctx.deactivate_worker("worker-2")

    ctx.sleep(3, "Worker B is offline")

    # --- step 6: Worker B comes back ---
    ctx.step("Worker B reactivates (rejoins network)")
    ctx.activate_worker("worker-2")

    # --- step 7: Worker D leaves permanently ---
    ctx.step("Worker D deactivates and unregisters permanently")
    ctx.deactivate_worker("worker-4")
    ctx.unregister_worker("worker-4")

    # --- step 8: complete first rental ---
    ctx.step("Client completes the first rental")
    ctx.complete_rental("client-1", rental_id=1)

    # --- step 9: second room order (4 workers remain) ---
    ctx.step("Client orders second room with capacity=10")
    ctx.order_room("client-1", room_name="churn-room-2", capacity=10, payment=500)

    # --- step 10: vote to assign Worker C (only 4 active workers now) ---
    ctx.step("Remaining workers vote to assign Worker C")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=2, nominee_node_id=3)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=2, nominee_node_id=3)
    ctx.worker_vote_room("worker-5", voter_node_id=5, rental_id=2, nominee_node_id=3)

    # --- step 11: users in second room ---
    ctx.step("5 users join the second room")
    for i in range(6, 11):
        ctx.add_user(f"user-{i}", room_name="churn-room-2")
        ctx.join_room(f"user-{i}")

    # --- step 12: all users leave ---
    ctx.step("All users leave both rooms")
    for i in range(1, 11):
        ctx.leave_room(f"user-{i}")

    # --- step 13: complete second rental ---
    ctx.step("Client completes the second rental")
    ctx.complete_rental("client-1", rental_id=2)
