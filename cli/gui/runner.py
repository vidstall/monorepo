from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Callable

import flet as ft


class ActionRunner:
    """Runs a blocking cli.* call off the Flet UI thread (via
    page.run_thread), capturing whatever it print()s -- every function in
    cli/*.py communicates through plain print(), there's no --json output
    on vidctl itself -- into a shared scrolling log panel. Re-enables the
    triggering control and invokes on_done with the call's return value
    (or None on exception) once finished."""

    def __init__(self, page: ft.Page, log_view: ft.ListView) -> None:
        self.page = page
        self.log_view = log_view

    def log(self, message: str) -> None:
        self.log_view.controls.append(ft.Text(message, font_family="monospace", size=12, selectable=True))
        self.page.update()

    def run(
        self,
        label: str,
        fn: Callable[..., Any],
        *args: Any,
        trigger: ft.Control | None = None,
        on_done: Callable[[Any], None] | None = None,
        **kwargs: Any,
    ) -> None:
        if trigger is not None:
            trigger.disabled = True
            self.page.update()

        def worker() -> None:
            self.log(f"$ {label}")
            buffer = io.StringIO()
            result: Any = None
            error: BaseException | None = None
            try:
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - surface any failure to the log panel instead of crashing the app
                error = exc
            output = buffer.getvalue()
            for line in output.splitlines():
                self.log(line)
            if error is not None:
                self.log(f"FAILED: {error}")
                self.log(traceback.format_exc())
            else:
                self.log(f"done: {label}")
            if trigger is not None:
                trigger.disabled = False
            self.page.update()
            if on_done is not None:
                on_done(None if error is not None else result)

        self.page.run_thread(worker)
