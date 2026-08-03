from __future__ import annotations

import time

from ansible.plugins.callback import CallbackBase

# Diagnostic-only callback for tracking down where ansible-playbook time
# actually goes (see IaC/README.md's "Ansible role layout" section) --
# doesn't affect deploy behavior, only stdout. Keyed by task NAME, not by
# (task, host) pair -- with `strategy: free` the same task name can start
# on one host while a slower host is still mid-task on the previous one,
# so per-host timing would double-count overlapping wall-clock time.
# Aggregating by name instead gives the metric that actually matters here:
# total wall-clock time this task contributed to the run, summed across
# every host/loop iteration it ran on.
DOCUMENTATION = """
    name: task_timer
    type: aggregate
    short_description: Print a slowest-first task duration summary at playbook end.
"""


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "task_timer"
    CALLBACK_NEEDS_ENABLED = False

    def __init__(self) -> None:
        super().__init__()
        self._task_start: float | None = None
        self._task_name: str | None = None
        # {task_name: total_seconds} -- accumulated across every host/loop
        # iteration that task name ran for, since free-strategy runs can
        # interleave the same task name across hosts concurrently.
        self._totals: dict[str, float] = {}

    def _close_current(self) -> None:
        if self._task_start is None or self._task_name is None:
            return
        elapsed = time.monotonic() - self._task_start
        self._totals[self._task_name] = self._totals.get(self._task_name, 0.0) + elapsed
        self._task_start = None
        self._task_name = None

    def v2_playbook_on_task_start(self, task, is_conditional) -> None:
        self._close_current()
        self._task_name = task.get_name()
        self._task_start = time.monotonic()

    def v2_playbook_on_handler_task_start(self, task) -> None:
        self.v2_playbook_on_task_start(task, False)

    def v2_playbook_on_stats(self, stats) -> None:
        self._close_current()
        ranked = sorted(self._totals.items(), key=lambda item: item[1], reverse=True)
        self._display.display("\nTASK TIMER (slowest first, summed across all hosts/loop iterations):")
        for name, seconds in ranked[:25]:
            self._display.display(f"  {seconds:7.1f}s  {name}")
