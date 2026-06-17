"""Capacity stress test: rapid user joins, rejection at limit, throughput measurement."""
from cli.scenario import Topology, ScenarioContext

NAME = "capacity-stress"
DESCRIPTION = "Rapid user joins to measure join latency and capacity enforcement under load"
TOPOLOGY = Topology(worker_nodes=3, client_nodes=2, coordinator_nodes=1, contract_network="testnet")


def run(ctx: ScenarioContext) -> None:
    # --- setup ---
    for i in range(1, 4):
        ctx.add_worker(f"worker-{i}", address=f"0xW{i}")
    ctx.add_client("client-1", address="0xC1")
    ctx.add_client("client-2", address="0xC2")

    # --- step 1: workers register ---
    ctx.step("Workers A-C register")
    for i in range(1, 4):
        ctx.register_worker(f"worker-{i}")

    # --- step 2: first room, capacity=20 ---
    ctx.step("Client 1 orders room with capacity=20")
    ctx.order_room("client-1", room_name="stress-room-1", capacity=20, payment=500)

    # --- step 3: vote to assign Worker A ---
    ctx.step("Workers vote to assign Worker A")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=1, nominee_node_id=1)
    ctx.worker_vote_room("worker-2", voter_node_id=2, rental_id=1, nominee_node_id=1)

    # --- step 4: 20 users join rapidly ---
    ctx.step("20 users join in rapid succession")
    for i in range(1, 21):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="stress-room-1")
        ctx.join_room(uid)

    # --- step 5: 21st user rejected ---
    ctx.step("21st user attempts to join (should be rejected)")
    ctx.add_user("user-21", room_name="stress-room-1")
    ctx.join_room("user-21")

    # --- step 6: 10 users leave ---
    ctx.step("10 users leave simultaneously")
    for i in range(1, 11):
        ctx.leave_room(f"user-{i}")

    # --- step 7: 10 new users fill the slots ---
    ctx.step("10 new users join the freed slots")
    for i in range(22, 32):
        uid = f"user-{i}"
        ctx.add_user(uid, room_name="stress-room-1")
        ctx.join_room(uid)

    # --- step 8: complete first rental ---
    ctx.step("Client 1 completes the rental")
    ctx.complete_rental("client-1", rental_id=1)

    # --- step 9: second room, capacity=50 ---
    ctx.step("Client 2 orders room with capacity=50")
    ctx.order_room("client-2", room_name="stress-room-2", capacity=50, payment=500)

    # --- step 10: vote to assign Worker B ---
    ctx.step("Workers vote to assign Worker B")
    ctx.worker_vote_room("worker-1", voter_node_id=1, rental_id=2, nominee_node_id=2)
    ctx.worker_vote_room("worker-3", voter_node_id=3, rental_id=2, nominee_node_id=2)

    # --- step 11: 50 users join in batches of 10 ---
    ctx.step("50 users join in batches of 10")
    user_counter = 100
    for batch in range(5):
        ctx.log(f"batch {batch + 1}/5")
        for _ in range(10):
            uid = f"user-{user_counter}"
            ctx.add_user(uid, room_name="stress-room-2")
            ctx.join_room(uid)
            user_counter += 1

    # --- step 12: all leave ---
    ctx.step("All users leave")
    for uid in list(ctx.report.users.keys()):
        u = ctx.report.users[uid]
        if u.joined_at and not u.left_at:
            ctx.leave_room(uid)

    # --- step 13: complete second rental ---
    ctx.step("Client 2 completes the rental")
    ctx.complete_rental("client-2", rental_id=2)
