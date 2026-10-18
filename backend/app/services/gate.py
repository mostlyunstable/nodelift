"""One place that decides whether code may start running.

Every execution path (stored runs, single-node tests) goes through here, so the limits cannot be
bypassed by picking a different endpoint.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from app.domain.errors import AppError


class ExecutionGate:
    def __init__(self, max_runs: int = 4, max_node_tests: int = 4) -> None:
        self.max_runs = max_runs
        self.max_node_tests = max_node_tests
        self.cancels: dict[str, asyncio.Event] = {}  # live runs -> cancel flag
        self._node_tests = 0

    def open_run(self, run_id: str) -> asyncio.Event:
        if len(self.cancels) >= self.max_runs:
            raise AppError(
                429, "too_many_runs", f"At most {self.max_runs} runs at once; try again shortly"
            )
        flag = asyncio.Event()
        self.cancels[run_id] = flag
        return flag

    def close_run(self, run_id: str) -> None:
        self.cancels.pop(run_id, None)

    @contextmanager
    def node_test(self) -> Iterator[None]:
        if self._node_tests >= self.max_node_tests:
            raise AppError(
                429,
                "too_many_node_tests",
                f"At most {self.max_node_tests} node tests at once; try again shortly",
            )
        self._node_tests += 1
        try:
            yield
        finally:
            self._node_tests -= 1
