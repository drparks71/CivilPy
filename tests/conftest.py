#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Suite-wide guards.

No test may open a network connection. The ODOT / AssetWise / TIMS / Midas
clients are exercised against mocked transports only; a test that needs a
live service is a test that writes to someone else's system, so it fails
here instead. Mark a test ``@pytest.mark.network`` to opt out deliberately
(it is then skipped unless ``--run-network`` is passed).
"""

import socket

import pytest

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex


def _is_local(address) -> bool:
    """Loopback is allowed: pytest-xdist and in-process servers use it."""
    if isinstance(address, tuple) and address:
        host = address[0]
        return host in ("127.0.0.1", "::1", "localhost", "")
    return isinstance(address, (str, bytes))  # UNIX domain sockets


def _blocked(self, address, *args, **kwargs):
    if _is_local(address):
        return _REAL_CONNECT(self, address, *args, **kwargs)
    raise RuntimeError(
        f"test attempted a network connection to {address!r}; "
        "mock the transport, or mark the test @pytest.mark.network"
    )


def _blocked_ex(self, address, *args, **kwargs):
    if _is_local(address):
        return _REAL_CONNECT_EX(self, address, *args, **kwargs)
    raise RuntimeError(
        f"test attempted a network connection to {address!r}; "
        "mock the transport, or mark the test @pytest.mark.network"
    )


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", default=False,
                     help="run tests marked @pytest.mark.network against live services")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: the test talks to a live service")


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("network"):
        if not request.config.getoption("--run-network"):
            pytest.skip("live-service test; pass --run-network to run it")
        yield
        return
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_ex)
    yield
