from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import context
from cli.infra import ansible


class RunDetachedTests(unittest.TestCase):
    def test_starts_new_session_and_does_not_wait(self) -> None:
        with patch.object(context.subprocess, "Popen") as popen:
            context.run_detached(["echo", "hi"], cwd=context.ROOT)

        popen.assert_called_once()
        self.assertEqual(popen.call_args.kwargs["start_new_session"], True)
        # No .wait()/.communicate() call on the returned Mock -- run_detached
        # must return as soon as Popen() is issued, not once the process exits.
        popen.return_value.wait.assert_not_called()
        popen.return_value.communicate.assert_not_called()

    def test_redirects_output_to_log_path_instead_of_inheriting_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "nested" / "run.log"
            with patch.object(context.subprocess, "Popen") as popen:
                context.run_detached(["echo", "hi"], cwd=context.ROOT, log_path=log_path)

            self.assertTrue(log_path.parent.is_dir())
            self.assertIsNot(popen.call_args.kwargs["stdout"], context.subprocess.DEVNULL)


class AnsiblePlaybookDetachTests(unittest.TestCase):
    def test_detach_calls_run_detached_not_run_and_returns_zero_without_waiting(self) -> None:
        from cli import infra

        with (
            patch.object(ansible, "venv_bin", return_value=Path("/usr/bin/ansible-playbook")),
            patch.object(Path, "exists", return_value=True),
            patch.object(infra, "run_detached") as run_detached,
            patch.object(infra, "run") as run,
        ):
            code = ansible.ansible_playbook("site.yml", host_limit="node-1", detach=True, log_path=Path("/tmp/x.log"))

        self.assertEqual(code, 0)
        run_detached.assert_called_once()
        run.assert_not_called()
        self.assertEqual(run_detached.call_args.kwargs["log_path"], Path("/tmp/x.log"))


class ToggleContainerTests(unittest.TestCase):
    def test_calls_ansible_playbook_with_toggle_container_yml_and_expected_vars(self) -> None:
        # record_history()/active_stack() are real, unmocked module-level
        # calls inside toggle_container() -- must be patched here or this
        # test writes a real entry into the developer's actual
        # runtime/history.toml (confirmed happened once; see git history).
        with (
            patch.object(ansible, "ansible_playbook", return_value=0) as ansible_playbook,
            patch.object(ansible, "record_history") as record_history,
            patch.object(ansible, "active_stack", return_value="devnet"),
        ):
            code = ansible.toggle_container(
                host_limit="006", container_name="xaisen-akamai-006-relay-1", action="start", detach=True, log_path=Path("/tmp/x.log")
            )

        self.assertEqual(code, 0)
        ansible_playbook.assert_called_once_with(
            "toggle_container.yml",
            extra_vars={"xaisen_toggle_action": "start", "xaisen_container_name": "xaisen-akamai-006-relay-1"},
            host_limit="006",
            detach=True,
            log_path=Path("/tmp/x.log"),
        )
        record_history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
