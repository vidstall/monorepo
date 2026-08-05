from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import bot_client, context, local_bot


class PortAllocationTests(unittest.TestCase):
    def test_id_one_is_base_port(self) -> None:
        self.assertEqual(local_bot._port_for(1), local_bot.BASE_PORT)

    def test_ids_increment_sequentially(self) -> None:
        self.assertEqual(local_bot._port_for(2), local_bot.BASE_PORT + 1)
        self.assertEqual(local_bot._port_for(5), local_bot.BASE_PORT + 4)


class PidAliveTests(unittest.TestCase):
    def test_dead_pid_returns_false(self) -> None:
        with patch("os.kill", side_effect=ProcessLookupError):
            self.assertFalse(local_bot._pid_alive(12345))

    def test_alive_pid_returns_true(self) -> None:
        with patch("os.kill", return_value=None):
            self.assertTrue(local_bot._pid_alive(12345))

    def test_permission_error_still_counts_as_alive(self) -> None:
        with patch("os.kill", side_effect=PermissionError):
            self.assertTrue(local_bot._pid_alive(1))


class SessionStateRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "local_bots.toml"
        self.patch = patch.object(context, "RUNTIME_LOCAL_BOTS_TOML", self.toml_path)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(local_bot.read_sessions(), {})

    def test_round_trip_preserves_fields(self) -> None:
        session = local_bot.LocalBotSession(
            id=1,
            pid=999,
            port=8095,
            bot_id="abc-123",
            room_id="0xroom",
            join_url="https://thesis.rotexai.com/rooms/0xroom?pw=123",
            started_at="2026-08-05T08:40:00+00:00",
            log_path="runtime/local_bots/1.log",
        )
        local_bot._write_sessions({1: session})
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions, {1: session})

    def test_write_preserves_multiple_entries(self) -> None:
        s1 = local_bot.LocalBotSession(1, 100, 8095, "b1", "0xroom1", "url1", "t1", "log1")
        s2 = local_bot.LocalBotSession(2, 200, 8096, "b2", "0xroom2", "url2", "t2", "log2")
        local_bot._write_sessions({1: s1, 2: s2})
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions, {1: s1, 2: s2})

    def test_malformed_toml_returns_empty(self) -> None:
        self.toml_path.parent.mkdir(parents=True, exist_ok=True)
        self.toml_path.write_text("not valid toml [[[", encoding="utf-8")
        self.assertEqual(local_bot.read_sessions(), {})


class StartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "local_bots.toml"
        self.env_path = Path(self.temp.name) / ".env"
        self.env_path.write_text("PRIVATE_KEY=suiprivkey1x\n", encoding="utf-8")
        self.patches = [
            patch.object(context, "RUNTIME_LOCAL_BOTS_TOML", self.toml_path),
            patch.object(local_bot, "BOT_APP_DIR", Path(self.temp.name)),
            patch.object(context, "run_detached", return_value=4242),
            patch.object(local_bot, "_wait_for_healthz", return_value=True),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_start_writes_session_on_success(self) -> None:
        with patch.object(
            bot_client,
            "create_room_local",
            return_value={"botId": "b1", "roomId": "0xroom", "joinUrl": "https://example/rooms/0xroom"},
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                code = local_bot.start(1)
        self.assertEqual(code, 0)
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].port, local_bot.BASE_PORT)
        self.assertEqual(sessions[1].room_id, "0xroom")
        self.assertEqual(sessions[1].join_url, "https://example/rooms/0xroom")

    def test_start_missing_env_file_errors_without_spawning(self) -> None:
        self.env_path.unlink()
        with patch.object(context, "run_detached") as run_detached:
            with contextlib.redirect_stdout(io.StringIO()):
                code = local_bot.start(1)
        self.assertEqual(code, 1)
        run_detached.assert_not_called()
        self.assertEqual(local_bot.read_sessions(), {})

    def test_start_already_running_does_not_spawn_again(self) -> None:
        existing = local_bot.LocalBotSession(1, 4242, local_bot.BASE_PORT, "b1", "0xroom", "url", "t", "log")
        local_bot._write_sessions({1: existing})
        with patch.object(local_bot, "_pid_alive", return_value=True):
            with patch.object(context, "run_detached") as run_detached:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.start(1)
        self.assertEqual(code, 1)
        run_detached.assert_not_called()

    def test_start_records_process_even_if_room_creation_fails(self) -> None:
        with patch.object(bot_client, "create_room_local", return_value=None):
            with contextlib.redirect_stdout(io.StringIO()):
                code = local_bot.start(1)
        self.assertEqual(code, 1)
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].room_id, "")

    def test_start_unhealthy_process_does_not_create_room(self) -> None:
        with patch.object(local_bot, "_wait_for_healthz", return_value=False):
            with patch.object(bot_client, "create_room_local") as create_room_local:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.start(1)
        self.assertEqual(code, 1)
        create_room_local.assert_not_called()
        # Still recorded (pid tracked) so `stop` can find and kill the
        # hung process later -- it must not leak untracked.
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].room_id, "")


class StopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "local_bots.toml"
        self.patch = patch.object(context, "RUNTIME_LOCAL_BOTS_TOML", self.toml_path)
        self.patch.start()
        self.session = local_bot.LocalBotSession(
            1, 4242, local_bot.BASE_PORT, "bot-1", "0xroom", "url", "t", "log"
        )
        local_bot._write_sessions({1: self.session})

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_stop_unknown_id_errors(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            code = local_bot.stop(99)
        self.assertEqual(code, 1)

    def test_stop_deletes_room_kills_process_and_clears_state(self) -> None:
        with patch.object(bot_client, "delete_room_local", return_value={}) as delete_room_local:
            with patch.object(local_bot, "_pid_alive", return_value=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.stop(1)
        delete_room_local.assert_called_once_with(local_bot.BASE_PORT, "bot-1")
        self.assertEqual(code, 0)
        self.assertEqual(local_bot.read_sessions(), {})

    def test_stop_sends_sigterm_to_live_process(self) -> None:
        with patch.object(bot_client, "delete_room_local", return_value={}):
            with patch.object(local_bot, "_pid_alive", side_effect=[True, False, False]):
                with patch("os.kill") as kill:
                    with contextlib.redirect_stdout(io.StringIO()):
                        local_bot.stop(1)
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[0], 4242)


if __name__ == "__main__":
    unittest.main()
