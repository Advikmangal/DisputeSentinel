import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Unit tests must use local mocks, never PayPal, Gemini or other services."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in unit tests")

    def guarded(original):
        def connect(sock, address):
            # Windows asyncio creates a loopback socketpair for its event loop.
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return original(sock, address)
            return blocked()
        return connect

    monkeypatch.setattr(socket.socket, "connect", guarded(original_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(original_connect_ex))
    monkeypatch.setattr(socket, "create_connection", blocked)
