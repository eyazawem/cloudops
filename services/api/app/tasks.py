import time
from collections.abc import Callable
from typing import Any

MAX_SIMULATED_SECONDS = 30.0


class TaskError(Exception):
    """Raised when a task fails."""


def report_generation(payload: dict[str, Any]) -> None:
    """Simulated task: waits for `seconds` (default 2, capped)."""
    seconds = float(payload.get("seconds", 2))
    time.sleep(max(0.0, min(seconds, MAX_SIMULATED_SECONDS)))


def always_fail(payload: dict[str, Any]) -> None:
    """Simulated task that always fails, to exercise the failure path."""
    raise TaskError("this task always fails")


HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "report-generation": report_generation,
    "fail": always_fail,
}
