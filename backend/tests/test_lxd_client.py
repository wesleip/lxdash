"""Tests for services.lxd_client — the only module allowed to import pylxd."""

from __future__ import annotations

import asyncio
import gc
import json
import socket
import threading
import warnings
from unittest.mock import patch
from urllib.parse import quote, urlparse

import pylxd
import pytest

from services.lxd_client import LXDClient, LXDClientError

SOCKET_PATH = "/var/snap/lxd/common/lxd/unix.socket"


def test_connect_socket_percent_encodes_the_socket_path() -> None:
    """Regression: the unquoted form (`http+unix:///var/...`) parses with an
    empty netloc, so pylxd raised "No host supplied" before ever touching the
    daemon and every resource request came back as
    502 "Unable to connect to the LXD host."
    """
    sentinel = object()

    with patch("services.lxd_client.pylxd.Client", return_value=sentinel) as fake:
        client = asyncio.run(LXDClient.connect_socket(SOCKET_PATH, host_id=7))

    endpoint = fake.call_args.kwargs["endpoint"]
    assert endpoint == f"http+unix://{quote(SOCKET_PATH, safe='')}"

    # The socket path must live in the netloc, percent-encoded — that is what
    # requests-unixsocket connects to.
    parsed = urlparse(endpoint)
    assert parsed.scheme == "http+unix"
    assert parsed.netloc == quote(SOCKET_PATH, safe="")

    assert client._client is sentinel
    assert client.host_id == 7


def test_connect_socket_wraps_connection_failures() -> None:
    """Every failure raised while building the client must surface as
    LXDClientError (→ HTTP 502), never as an unhandled 500.
    """
    for exc in (
        pylxd.exceptions.ClientConnectionFailed("Invalid URL"),
        RuntimeError("something else broke"),
    ):
        with patch("services.lxd_client.pylxd.Client", side_effect=exc):
            with pytest.raises(LXDClientError, match="Cannot connect to socket"):
                asyncio.run(LXDClient.connect_socket(SOCKET_PATH))


# ---------------------------------------------------------------------------
# Integration: real pylxd over a real Unix socket
# ---------------------------------------------------------------------------


class _StubLXD:
    """A minimal LXD daemon on a Unix socket: answers GET /1.0 with 200.

    Enough for ``pylxd.Client.__init__``, which issues exactly that request to
    verify the connection. Talking to it proves the endpoint URL pylxd builds
    from our input actually reaches a socket — the assertion a mocked
    ``pylxd.Client`` can never make.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._closing = False
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(path)
        self._server.listen(4)
        self._server.settimeout(5.0)
        self.requests: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._closing:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5.0)
                try:
                    data = conn.recv(65536)
                except OSError:
                    continue
                if not data:
                    continue
                self.requests.append(data)
                body = json.dumps(
                    {
                        "type": "sync",
                        "status": "Success",
                        "status_code": 200,
                        "metadata": {
                            "api_version": "1.0",
                            "auth": "trusted",
                            "environment": {"server_name": "stub"},
                        },
                    }
                ).encode()
                try:
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + body
                    )
                except OSError:
                    continue

    def close(self) -> None:
        """Wake the accept() loop, let the thread exit, then release the socket.

        Closing the listening socket while the thread is blocked in accept()
        leaves the fd to be finalized during interpreter shutdown, which pytest
        reports as an unraisable exception.
        """
        self._closing = True
        try:
            wake = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            wake.settimeout(1.0)
            wake.connect(self._path)
            wake.close()
        except OSError:
            pass
        self._thread.join(timeout=5.0)
        self._server.close()


def test_connect_socket_reaches_a_real_unix_socket(tmp_path) -> None:
    """End-to-end: pylxd must complete its handshake over the Unix socket.

    This is the test the old unquoted ``http+unix:///path`` endpoint failed —
    it raised "No host supplied" without ever opening the socket, which is why
    every container/image/network request 502'd while the httpx-based health
    probe happily reported the host as reachable.
    """
    path = str(tmp_path / "lxd.sock")
    stub = _StubLXD(path)
    try:
        client = asyncio.run(LXDClient.connect_socket(path, host_id=3))
    finally:
        stub.close()

    assert client.host_id == 3
    assert stub.requests, "pylxd never reached the socket"
    assert b"GET /1.0" in stub.requests[0]


def test_connect_socket_reports_a_missing_socket() -> None:
    """A socket that does not exist must be an LXDClientError, not a crash."""
    with pytest.raises(LXDClientError, match="Cannot connect to socket"):
        asyncio.run(LXDClient.connect_socket("/nonexistent/lxd.sock"))

    # pylxd/requests leaks the socket it fails to connect with. Collect it here,
    # while ResourceWarning is ignored, so it does not surface as an unraisable
    # exception at session end (pyproject sets filterwarnings = error).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        gc.collect()
