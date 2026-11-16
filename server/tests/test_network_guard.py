# SPDX-License-Identifier: GPL-3.0-or-later
"""The suite must never reach the real network."""

import socket

import pytest
from pytest_socket import SocketBlockedError, SocketConnectBlockedError


def test_real_network_is_blocked() -> None:
    with pytest.raises((SocketBlockedError, SocketConnectBlockedError)):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
