import time
from collections.abc import Callable
from typing import Any

MAX_SIMULATED_SECONDS = 30.0


class TaskError(Exception):
    """A task failed. The failure may be transient: the job can be retried."""


class PermanentTaskError(TaskError):
    """A task failed for a reason that retrying cannot fix."""


def report_generation(payload: dict[str, Any], attempt: int) -> None:
    """Simulated task: waits for `seconds` (default 2, capped)."""
    seconds = float(payload.get("seconds", 2))
    time.sleep(max(0.0, min(seconds, MAX_SIMULATED_SECONDS)))


def always_fail(payload: dict[str, Any], attempt: int) -> None:
    """Simulated task that always fails."""
    raise TaskError("this task always fails")


def flaky(payload: dict[str, Any], attempt: int) -> None:
    """Simulated task that fails `fail_times` times (default 1), then succeeds."""
    fail_times = int(payload.get("fail_times", 1))
    if attempt <= fail_times:
        raise TaskError(f"simulated transient failure (attempt {attempt})")


Handler = Callable[[dict[str, Any], int], None]

HANDLERS: dict[str, Handler] = {
    "report-generation": report_generation,
    "fail": always_fail,
    "flaky": flaky,
}
