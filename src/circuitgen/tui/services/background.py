"""Run short blocking work without stopping Textual's event loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from threading import Thread
from typing import Callable, TypeVar


T = TypeVar("T")


async def run_background_stage(operation: Callable[[], T]) -> T:
    result: Future[T] = Future()

    def run() -> None:
        if result.set_running_or_notify_cancel():
            try:
                result.set_result(operation())
            except Exception as exc:
                result.set_exception(exc)

    Thread(target=run, daemon=True).start()
    return await asyncio.wrap_future(result)
