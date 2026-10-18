"""In-process wake-up for SSE streams. Events are persisted first; this only cuts latency.

Correctness never depends on it: streams also re-poll the database on a short timeout.
"""

import asyncio


class RunHub:
    def __init__(self) -> None:
        self._conds: dict[str, asyncio.Condition] = {}
        self.cancels: dict[str, asyncio.Event] = {}  # live runs -> cancel flag
        self.tasks: set[asyncio.Task[None]] = set()  # strong refs so runs aren't garbage-collected

    def _cond(self, run_id: str) -> asyncio.Condition:
        return self._conds.setdefault(run_id, asyncio.Condition())

    async def notify(self, run_id: str) -> None:
        cond = self._cond(run_id)
        async with cond:
            cond.notify_all()

    async def wait(self, run_id: str, timeout: float) -> None:
        cond = self._cond(run_id)
        async with cond:
            try:
                await asyncio.wait_for(cond.wait(), timeout)
            except TimeoutError:
                pass

    def forget(self, run_id: str) -> None:
        self._conds.pop(run_id, None)

    def track(self, task: asyncio.Task[None]) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
