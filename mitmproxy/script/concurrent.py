"""Primitives for marking callbacks for worker-thread execution."""

import asyncio
import inspect
from collections.abc import Callable
from typing import TypeVar

from mitmproxy import hooks

TCallable = TypeVar("TCallable", bound=Callable[..., object])


def run_in_thread(function: TCallable) -> TCallable:
    """Mark a supported callback for execution in a worker thread."""
    if inspect.iscoroutinefunction(function) or inspect.isasyncgenfunction(function):
        raise ValueError("run_in_thread cannot be used with async functions.")

    setattr(function, "__mitmproxy_run_in_thread__", True)
    return function


def should_run_in_thread(function: Callable[..., object]) -> bool:
    function = getattr(function, "__func__", function)
    return bool(getattr(function, "__mitmproxy_run_in_thread__", False))


def concurrent(fn):
    if fn.__name__ not in set(hooks.all_hooks.keys()) - {"load", "configure"}:
        raise NotImplementedError(
            "Concurrent decorator not supported for '%s' method." % fn.__name__
        )

    async def _concurrent(*args):
        def run():
            if inspect.iscoroutinefunction(fn):
                # Run the async function in a new event loop
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(fn(*args))
                finally:
                    loop.close()
            else:
                fn(*args)

        await asyncio.get_running_loop().run_in_executor(None, run)

    return _concurrent
