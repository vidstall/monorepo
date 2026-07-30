from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from cli import contract, observer
from cli.contract import chain_io


class RunSuiDevinspectTests(unittest.TestCase):
    def test_picks_the_outer_object_not_the_shorter_nested_effects_blob(self) -> None:
        # The dev-inspect payload's top-level keys (transaction/command_outputs/
        # suggested_gas_price) don't match parse_json_payload()'s "objectChanges"/
        # "effects" scoring bonus -- but the NESTED transaction.effects sub-object
        # DOES contain an "effects" key of its own, and used to win under that
        # heuristic despite being much shorter. run_sui_devinspect() must pick the
        # full outer object instead (see its docstring).
        payload = {
            "transaction": {"effects": {"status": "Success"}},
            "command_outputs": [{"returnValues": [{"json": ["0xabc", "0xdef"]}]}],
            "suggested_gas_price": None,
        }
        fake_stdout = json.dumps(payload)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = fake_stdout
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0
            code, result, _ = chain_io.run_sui_devinspect(["sui", "client", "call"])
        self.assertEqual(code, 0)
        self.assertIn("command_outputs", result)
        self.assertEqual(result["command_outputs"][0]["returnValues"][0]["json"], ["0xabc", "0xdef"])

    def test_returns_none_payload_on_unparseable_output(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "not json at all"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 1
            code, result, _ = chain_io.run_sui_devinspect(["sui", "client", "call"])
        self.assertEqual(code, 1)
        self.assertIsNone(result)


class ListActiveRoomsTests(unittest.TestCase):
    def test_returns_none_when_room_manager_not_configured(self) -> None:
        with patch.object(contract, "load_deployment", return_value={}):
            self.assertIsNone(contract.list_active_rooms("devnet"))

    def test_zips_ids_and_infos_and_maps_status_names(self) -> None:
        deployment = {"CONTRACT_PACKAGE_ID": "0xpkg", "ROOM_MANAGER_ID": "0xrm"}
        room_ids = ["0xroom1", "0xroom2"]
        room_infos = [
            {"status": 0, "expected_participants": "4", "creator": "0xcreator1", "created_at": "10"},
            {"status": 2, "expected_participants": "8", "creator": "0xcreator2", "created_at": "20"},
        ]

        def fake_devinspect(package_id, room_manager_id, function):
            self.assertEqual(package_id, "0xpkg")
            self.assertEqual(room_manager_id, "0xrm")
            if function == "get_active_room_ids":
                return room_ids
            if function == "get_active_rooms":
                return room_infos
            raise AssertionError(f"unexpected function: {function}")

        with patch.object(contract, "load_deployment", return_value=deployment), patch(
            "cli.contract.rooms._devinspect_view", side_effect=fake_devinspect
        ):
            rooms = contract.list_active_rooms("devnet")

        self.assertEqual(len(rooms), 2)
        self.assertEqual(rooms[0]["room_id"], "0xroom1")
        self.assertEqual(rooms[0]["status"], "pending")
        self.assertEqual(rooms[0]["expected_participants"], 4)
        self.assertEqual(rooms[1]["status"], "active")
        self.assertEqual(rooms[1]["expected_participants"], 8)

    def test_returns_none_when_either_devinspect_call_fails(self) -> None:
        deployment = {"CONTRACT_PACKAGE_ID": "0xpkg", "ROOM_MANAGER_ID": "0xrm"}
        with patch.object(contract, "load_deployment", return_value=deployment), patch(
            "cli.contract.rooms._devinspect_view", return_value=None
        ):
            self.assertIsNone(contract.list_active_rooms("devnet"))


class RoomParticipantCountsTests(unittest.TestCase):
    def test_no_prometheus_host_registered_returns_none(self) -> None:
        with patch("cli.observer.query.read_hosts", return_value=[{"name": "bourbon", "services": ["grafana"]}]):
            self.assertIsNone(observer.room_participant_counts())

    def test_parses_prometheus_vector_result_into_room_id_counts(self) -> None:
        # room_participant_counts() only parses query()'s raw vector result --
        # host lookup/reachability is query()'s own concern, exercised
        # separately below.
        prom_result = [
            {"metric": {"roomId": "0xroom1"}, "value": [1690000000, "3"]},
            {"metric": {"roomId": "0xroom2"}, "value": [1690000000, "0"]},
        ]
        with patch("cli.observer.query.query", return_value=prom_result):
            counts = observer.room_participant_counts()
        self.assertEqual(counts, {"0xroom1": 3, "0xroom2": 0})

    def test_missing_prometheus_result_returns_none(self) -> None:
        with patch("cli.observer.query.query", return_value=None):
            self.assertIsNone(observer.room_participant_counts())


if __name__ == "__main__":
    unittest.main()
