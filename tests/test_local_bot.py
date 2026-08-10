from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import bot_client, context, local_bot
from cli.wallet import chain_ops


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


class EnsureGasFundedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = {"PRIVATE_KEY": "suiprivkey1x", "SUI_NETWORK": "devnet"}

    def test_skips_when_network_has_no_faucet(self) -> None:
        env = {"PRIVATE_KEY": "suiprivkey1x", "SUI_NETWORK": "mainnet"}
        with patch.object(chain_ops, "sui_address_from_private_key") as derive:
            local_bot._ensure_gas_funded(env)
        derive.assert_not_called()

    def test_skips_when_no_private_key_configured(self) -> None:
        env = {"PRIVATE_KEY": "", "SUI_NETWORK": "devnet"}
        with patch.object(chain_ops, "sui_address_from_private_key") as derive:
            local_bot._ensure_gas_funded(env)
        derive.assert_not_called()

    def test_skips_faucet_when_balance_already_above_threshold(self) -> None:
        with (
            patch.object(chain_ops, "sui_address_from_private_key", return_value="0xabc"),
            patch.object(chain_ops, "current_balance_mist", return_value=local_bot.LOCAL_BOT_MIN_GAS_MIST),
            patch.object(context, "run") as run,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                local_bot._ensure_gas_funded(self.env)
        run.assert_not_called()

    def test_requests_faucet_when_balance_below_threshold(self) -> None:
        with (
            patch.object(chain_ops, "sui_address_from_private_key", return_value="0xabc"),
            patch.object(chain_ops, "current_balance_mist", return_value=0),
            patch("cli.contract.ensure_active_sui_env", return_value=0),
            patch.object(context, "run", return_value=0) as run,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                local_bot._ensure_gas_funded(self.env)
        run.assert_called_once_with(["sui", "client", "faucet", "--address", "0xabc"])

    def test_balance_check_failure_is_non_fatal(self) -> None:
        with (
            patch.object(chain_ops, "sui_address_from_private_key", side_effect=subprocess.CalledProcessError(1, "sui")),
            patch.object(context, "run") as run,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                local_bot._ensure_gas_funded(self.env)  # must not raise
        run.assert_not_called()


class RefreshTests(unittest.TestCase):
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
        self.crashed = local_bot.LocalBotSession(
            1, 1111, local_bot.BASE_PORT, "old-bot", "0xroom", "https://example/rooms/0xroom", "t", "log"
        )
        local_bot._write_sessions({1: self.crashed})

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_refresh_unknown_id_errors(self) -> None:
        local_bot._write_sessions({})
        with contextlib.redirect_stdout(io.StringIO()):
            code = local_bot.refresh(99)
        self.assertEqual(code, 1)

    def test_refresh_already_running_is_a_no_op(self) -> None:
        with patch.object(local_bot, "_pid_alive", return_value=True):
            with patch.object(context, "run_detached") as run_detached:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.refresh(1)
        self.assertEqual(code, 1)
        run_detached.assert_not_called()

    def test_refresh_with_no_recorded_room_errors_without_spawning(self) -> None:
        local_bot._write_sessions({1: local_bot.LocalBotSession(1, 1111, local_bot.BASE_PORT, "", "", "", "t", "log")})
        with patch.object(local_bot, "_pid_alive", return_value=False):
            with patch.object(context, "run_detached") as run_detached:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.refresh(1)
        self.assertEqual(code, 1)
        run_detached.assert_not_called()

    def test_refresh_rejoins_the_old_room_not_a_new_one(self) -> None:
        with patch.object(local_bot, "_pid_alive", return_value=False):
            with patch.object(
                bot_client,
                "join_room_local",
                return_value={"botId": "new-bot", "roomId": "0xroom", "joinUrl": "https://example/rooms/0xroom"},
            ) as join_room_local:
                with patch.object(bot_client, "create_room_local") as create_room_local:
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = local_bot.refresh(1)
        self.assertEqual(code, 0)
        join_room_local.assert_called_once_with(local_bot.BASE_PORT, "0xroom", media_mode="both")
        create_room_local.assert_not_called()
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].bot_id, "new-bot")
        self.assertEqual(sessions[1].room_id, "0xroom")

    def test_refresh_records_process_and_keeps_old_room_if_rejoin_fails(self) -> None:
        with patch.object(local_bot, "_pid_alive", return_value=False):
            with patch.object(bot_client, "join_room_local", return_value=None):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = local_bot.refresh(1)
        self.assertEqual(code, 1)
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].bot_id, "")
        self.assertEqual(sessions[1].room_id, "0xroom")

    def test_refresh_unhealthy_process_does_not_join_and_keeps_old_room(self) -> None:
        with patch.object(local_bot, "_pid_alive", return_value=False):
            with patch.object(local_bot, "_wait_for_healthz", return_value=False):
                with patch.object(bot_client, "join_room_local") as join_room_local:
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = local_bot.refresh(1)
        self.assertEqual(code, 1)
        join_room_local.assert_not_called()
        sessions = local_bot.read_sessions()
        self.assertEqual(sessions[1].pid, 4242)
        self.assertEqual(sessions[1].room_id, "0xroom")


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

    def test_stop_sends_sigterm_to_the_whole_process_group(self) -> None:
        # stop() must reach the WHOLE tree pnpm/tsx/node form (see
        # _terminate_process_tree's doc) via os.killpg, not just the tracked
        # pid via a plain os.kill -- a single-pid kill left tsx/node
        # descendants running as orphans once pnpm exited.
        with patch.object(bot_client, "delete_room_local", return_value={}):
            with patch.object(local_bot, "_pid_alive", side_effect=[True, False, False]):
                with patch("os.getpgid", return_value=4242) as getpgid:
                    with patch("os.killpg") as killpg:
                        with contextlib.redirect_stdout(io.StringIO()):
                            local_bot.stop(1)
        getpgid.assert_called_once_with(4242)
        killpg.assert_called_once()
        self.assertEqual(killpg.call_args.args[0], 4242)


class TerminateProcessTreeTests(unittest.TestCase):
    def test_sigterm_then_sigkill_if_still_alive_after_grace(self) -> None:
        with patch.object(local_bot, "STOP_GRACE_SECONDS", 0):
            with patch.object(local_bot, "_pid_alive", return_value=True):
                with patch("os.getpgid", return_value=555):
                    with patch("os.killpg") as killpg:
                        local_bot._terminate_process_tree(4242)
        self.assertEqual(killpg.call_count, 2)
        import signal as _signal

        self.assertEqual(killpg.call_args_list[0].args, (555, _signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (555, _signal.SIGKILL))

    def test_no_sigkill_when_process_exits_within_grace(self) -> None:
        with patch.object(local_bot, "_pid_alive", return_value=False):
            with patch("os.getpgid", return_value=555):
                with patch("os.killpg") as killpg:
                    local_bot._terminate_process_tree(4242)
        killpg.assert_called_once()

    def test_already_dead_pid_is_a_silent_no_op(self) -> None:
        with patch("os.getpgid", side_effect=ProcessLookupError):
            with patch("os.killpg") as killpg:
                local_bot._terminate_process_tree(4242)
        killpg.assert_not_called()


class FindBotProcessPidsTests(unittest.TestCase):
    def _run(self, ps_output: str) -> set[int]:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=ps_output, stderr="")
        with patch.object(local_bot.subprocess, "run", return_value=completed):
            return local_bot._find_bot_process_pids()

    def test_matches_pnpm_bot_dev(self) -> None:
        pids = self._run("12345 node /opt/homebrew/bin/pnpm --filter bot dev\n")
        self.assertEqual(pids, {12345})

    def test_matches_orphaned_tsx_watch_child(self) -> None:
        pids = self._run(
            "23456 node /path/services/worker/apps/bot/node_modules/.bin/tsx/dist/cli.mjs watch src/index.ts\n"
        )
        self.assertEqual(pids, {23456})

    def test_ignores_unrelated_processes(self) -> None:
        pids = self._run(
            "1 /sbin/launchd\n"
            "222 node /opt/homebrew/bin/pnpm --filter relay dev\n"
            "333 node /path/apps/other-service/src/index.ts\n"
        )
        self.assertEqual(pids, set())

    def test_subprocess_failure_returns_empty_set(self) -> None:
        with patch.object(local_bot.subprocess, "run", side_effect=OSError("no ps")):
            self.assertEqual(local_bot._find_bot_process_pids(), set())


class StopAllTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "local_bots.toml"
        self.patch = patch.object(context, "RUNTIME_LOCAL_BOTS_TOML", self.toml_path)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_stops_every_tracked_session(self) -> None:
        local_bot._write_sessions(
            {
                1: local_bot.LocalBotSession(1, 111, local_bot.BASE_PORT, "b1", "0xr1", "u1", "t", "log1"),
                2: local_bot.LocalBotSession(2, 222, local_bot.BASE_PORT + 1, "b2", "0xr2", "u2", "t", "log2"),
            }
        )
        with patch.object(bot_client, "delete_room_local", return_value={}):
            with patch.object(local_bot, "_pid_alive", return_value=False):
                with patch.object(local_bot, "_find_bot_process_pids", return_value=set()):
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = local_bot.stop_all()
        self.assertEqual(code, 0)
        self.assertEqual(local_bot.read_sessions(), {})

    def test_reaps_orphaned_processes_not_in_local_bots_toml(self) -> None:
        with patch.object(local_bot, "_find_bot_process_pids", return_value={99999}):
            with patch.object(local_bot, "_pid_alive", return_value=True):
                with patch.object(local_bot, "_terminate_process_tree") as terminate:
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = local_bot.stop_all()
        self.assertEqual(code, 0)
        terminate.assert_called_once_with(99999)

    def test_no_sessions_and_no_orphans_is_a_clean_no_op(self) -> None:
        with patch.object(local_bot, "_find_bot_process_pids", return_value=set()):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = local_bot.stop_all()
        self.assertEqual(code, 0)
        self.assertIn("No local bot sessions", out.getvalue())


class LogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "local_bots.toml"
        self.patch = patch.object(context, "RUNTIME_LOCAL_BOTS_TOML", self.toml_path)
        self.patch.start()
        self.log_path = Path(self.temp.name) / "1.log"

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def _write_session(self) -> None:
        local_bot._write_sessions(
            {1: local_bot.LocalBotSession(1, 4242, local_bot.BASE_PORT, "bot-1", "0xroom", "url", "t", str(self.log_path))}
        )

    def test_unknown_id_errors(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            code = local_bot.log(99)
        self.assertEqual(code, 1)

    def test_missing_log_file_errors(self) -> None:
        self._write_session()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = local_bot.log(1)
        self.assertEqual(code, 1)
        self.assertIn("no log file found", out.getvalue())

    def test_prints_trailing_lines_in_order(self) -> None:
        self._write_session()
        self.log_path.write_text("\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = local_bot.log(1, lines=5)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines(), ["line16", "line17", "line18", "line19", "line20"])

    def test_lines_exceeding_file_length_returns_whole_file(self) -> None:
        self._write_session()
        self.log_path.write_text("only-one-line\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = local_bot.log(1, lines=100)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines(), ["only-one-line"])

    def test_follow_shells_out_to_tail_f(self) -> None:
        self._write_session()
        self.log_path.write_text("line1\n", encoding="utf-8")
        with patch.object(subprocess, "call", return_value=0) as call:
            code = local_bot.log(1, lines=50, follow=True)
        self.assertEqual(code, 0)
        call.assert_called_once_with(["tail", "-n", "50", "-f", str(self.log_path)])


if __name__ == "__main__":
    unittest.main()
