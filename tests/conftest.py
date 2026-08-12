"""Default test safety boundary: no Internet or exchange connections."""

import socket
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def block_external_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[None, None, None]:
    if request.node.get_closest_marker("external") is not None:
        yield
        return

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_message() -> RuntimeError:
        return RuntimeError(
            "external network access is disabled in the default test suite; "
            "mark an explicitly authorized test with @pytest.mark.external"
        )

    def guarded_connect(sock: socket.socket, address: object) -> object:
        # Windows' ProactorEventLoop creates its self-pipe with a loopback
        # socketpair. Keep that process-local primitive available.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise blocked_message()

    def guarded_connect_ex(sock: socket.socket, address: object) -> object:
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect_ex(sock, address)
        raise blocked_message()

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise blocked_message()

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
