from dataclasses import dataclass

import pytest

from mitmproxy import connection
from mitmproxy.hooks import all_hooks
from mitmproxy.proxy import commands


@pytest.fixture
def tconn() -> connection.Server:
    return connection.Server(address=None)


def test_dataclasses(tconn):
    assert repr(commands.RequestWakeup(58))
    assert repr(commands.SendData(tconn, b"foo"))
    assert repr(commands.OpenConnection(tconn))
    assert repr(commands.CloseConnection(tconn))
    assert repr(commands.CloseTcpConnection(tconn, half_close=True))
    assert repr(commands.Log("hello"))


def test_start_hook():
    with pytest.raises(TypeError):
        commands.StartHook()

    @dataclass
    class TestHook(commands.StartHook):
        data: bytes

    f = TestHook(b"foo")
    assert f.args() == [b"foo"]
    assert TestHook in all_hooks.values()


@pytest.mark.parametrize("command_cls", [commands.RunInThread, commands.Await])
def test_command_unwrap(command_cls):
    if command_cls is commands.RunInThread:
        command = command_cls(pow, 2, exp=3)
    else:

        async def awaitable(base, exp):
            return pow(base, exp)

        command = command_cls(awaitable(2, exp=3))

    generator = command.unwrap()

    assert next(generator) is command
    with pytest.raises(StopIteration) as done:
        generator.send((8, None))
    assert done.value.value == 8

    if command_cls is commands.RunInThread:
        assert command.args == (2,)
        assert command.kwargs == {"exp": 3}


@pytest.mark.parametrize("command_cls", [commands.RunInThread, commands.Await])
def test_command_unwrap_error(command_cls):
    error = RuntimeError("test error")
    if command_cls is commands.RunInThread:
        command = command_cls(lambda: None)
    else:

        async def awaitable():
            return None

        command = command_cls(awaitable())

    generator = command.unwrap()
    assert next(generator) is command
    with pytest.raises(RuntimeError, match="test error"):
        generator.send((None, error))

    if command_cls is commands.Await:
        command.awaitable.close()
