import asyncio
import os
import time

import pytest

from mitmproxy.script.concurrent import run_in_thread
from mitmproxy.script.concurrent import should_run_in_thread
from mitmproxy.test import taddons
from mitmproxy.test import tflow


class TestConcurrent:
    @pytest.mark.parametrize(
        "addon", ["concurrent_decorator.py", "concurrent_decorator_class.py"]
    )
    async def test_concurrent(self, addon, tdata):
        with taddons.context() as tctx:
            sc = tctx.script(tdata.path(f"mitmproxy/data/addonscripts/{addon}"))
            f1, f2 = tflow.tflow(), tflow.tflow()
            start = time.time()
            await asyncio.gather(
                tctx.cycle(sc, f1),
                tctx.cycle(sc, f2),
            )
            end = time.time()
            # This test may fail on overloaded CI systems, increase upper bound if necessary.
            if os.environ.get("CI"):
                assert 0.5 <= end - start
            else:
                assert 0.5 <= end - start < 1

    def test_concurrent_err(self, tdata, caplog):
        with taddons.context() as tctx:
            tctx.script(
                tdata.path("mitmproxy/data/addonscripts/concurrent_decorator_err.py")
            )
            assert "decorator not supported" in caplog.text


def test_run_in_thread_marker():
    def plain(value: str) -> str:
        return value

    assert run_in_thread(plain) is plain
    assert should_run_in_thread(plain)
    assert plain("value") == "value"


def test_run_in_thread_bound_method():
    class Transformer:
        @run_in_thread
        def transform(self, value: str) -> str:
            return value

    assert should_run_in_thread(Transformer().transform)


@pytest.mark.parametrize("kind", ["coroutine", "async_generator"])
def test_run_in_thread_rejects_async_functions(kind):
    if kind == "coroutine":

        async def function():
            return None

    else:

        async def function():
            yield None

    with pytest.raises(ValueError, match="cannot be used with async functions"):
        run_in_thread(function)
