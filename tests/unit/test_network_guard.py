"""The test suite must never reach external hosts (NFR-MNT-02, STD-001 §11)."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError

pytestmark = pytest.mark.unit


def test_connections_to_external_hosts_are_blocked() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("203.0.113.10", 443), timeout=1)  # TEST-NET-3 address
