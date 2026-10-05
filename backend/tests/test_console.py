"""Tests for the /ws/containers/{name}/console WebSocket endpoint."""

from __future__ import annotations

import json
import threading
import time
from queue import Empty, Queue

import pytest

from models.host import ConnectionType, Host
from models.user import User, UserRole


@pytest.fixture
def admin_user() -> User:
    return User(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        role=UserRole.admin,
        is_active=True,
    )


def _make_host(db_session, name: str = "node1") -> Host:
    host = Host(
        name=name,
        address=f"/var/snap/lxd/common/lxd/unix.socket.{name}",
        connection_type=ConnectionType.socket,
        is_active=True,
    )
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)
    return host


def _seed_admin(db_session) -> User:
    """Insert an admin user the WS can authenticate as."""
    from services.auth_service import hash_password

    user = User(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password=hash_password("admin"),
        role=UserRole.admin,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_token_for(client, username: str = "admin", password: str = "admin") -> str:
    """Mint an access token via the live /auth/login endpoint."""
    resp = client.post(
        "/auth/login",
        data={"username": username, "password": password, "grant_type": "password"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _await_close_code(ws) -> int:
    """Drain frames until a close frame arrives; return its code.

    Starlette's TestClient surfaces an immediate close either as a
    ``WebSocketDisconnect`` raised on the next call (when the server
    closed *before* the test client sent anything) or as a
    ``{"type": "websocket.close", …}`` message (when the close frame
    arrives after the handshake completed). This helper accepts either.
    """
    from starlette.websockets import WebSocketDisconnect

    while True:
        try:
            frame = ws.receive()
        except WebSocketDisconnect as exc:
            return exc.code
        if frame.get("type") == "websocket.close":
            return int(frame.get("code", 1000))


def test_console_ws_closes_with_1008_when_token_missing(client, db_session):
    """Browsers cannot send Authorization on a WS, but a malicious caller
    still has to know the JWT. Without ``?token=...`` the upgrade must be
    rejected with the policy-violation close code (1008).

    Calling ``websocket.close()`` *before* ``websocket.accept()`` is a no-op
    in Starlette — the framework then answers the WS handshake with
    ``HTTP 403`` instead. The router now accepts first, then closes, so
    the close code survives.

    Note: a missing token is caught by the ``Query(..., token)`` validator
    before our handler runs, so the close frame can arrive *before* the
    handshake completes — Starlette surfaces that as ``WebSocketDisconnect``
    raised directly out of ``websocket_connect.__enter__``.
    """
    from starlette.websockets import WebSocketDisconnect

    _seed_admin(db_session)
    _make_host(db_session)

    try:
        with client.websocket_connect("/ws/containers/archlinux/console") as ws:
            code = _await_close_code(ws)
    except WebSocketDisconnect as exc:
        code = exc.code
    assert code == 1008


def test_console_ws_closes_with_1008_on_unknown_container(client, db_session):
    """Even with a valid token, asking for a container the host does not know
    closes with 1008 (no stack trace leaked to the operator)."""
    _seed_admin(db_session)
    _make_host(db_session)
    token = _auth_token_for(client)

    with client.websocket_connect(f"/ws/containers/no-such-container/console?token={token}") as ws:
        code = _await_close_code(ws)
    assert code == 1008


def test_console_ws_closes_with_1008_when_no_host_registered(client, db_session):
    """No host in the DB → 1008. The router must not leak the underlying
    exception to the client (AGENTS.md: "Never expose Python stack traces
    in HTTP responses")."""
    _seed_admin(db_session)
    token = _auth_token_for(client)

    with client.websocket_connect(f"/ws/containers/anything/console?token={token}") as ws:
        code = _await_close_code(ws)
    assert code == 1008


def test_console_ws_bridges_stdin_and_stdout_via_mock(client, db_session):
    """End-to-end happy path against MockLXDClient's ``/bin/sh -i``.

    The mock spawns a shell impersonating it, so typing ``echo hello`` must
    round-trip back as ``hello\\n`` (the shell echoes the command first, then
    executes it). The result asserts what the *browser* would see.
    """
    _seed_admin(db_session)
    _make_host(db_session)
    token = _auth_token_for(client)

    # Use a single reader thread that lives for the whole WS session;
    # spawning a fresh thread per accumulate() call loses the ordering
    # between reads and the second thread races with the first.
    q: Queue = Queue()
    with client.websocket_connect(f"/ws/containers/archlinux/console?token={token}") as ws:
        stop = threading.Event()

        def _reader() -> None:
            try:
                while not stop.is_set():
                    q.put(ws.receive())
            except Exception as exc:
                q.put(exc)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        def _drain(seconds: float) -> str:
            buf = b""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    frame = q.get(timeout=0.05)
                except Empty:
                    continue
                if isinstance(frame, BaseException):
                    break
                if frame.get("type") == "websocket.disconnect":
                    break
                text = frame.get("text")
                if text is not None:
                    buf += text.encode("utf-8")
                    continue
                payload = frame.get("bytes")
                if payload is not None:
                    buf += bytes(payload)
            return buf.decode("utf-8", errors="replace")

        try:
            # Give the shell a beat to print the prompt + the no-job-control
            # warning; the bridge surfaces them as binary frames.
            startup_text = _drain(1.0)
            # Send a real command and let the answer accumulate.
            ws.send_text("echo hello-from-test\n")
            answer = _drain(2.5)
        finally:
            stop.set()

    assert "mock@archlinux" in startup_text, f"prompt missing; got {startup_text!r}"
    assert "hello-from-test" in answer, f"echo output missing; got {answer!r}"


def test_console_ws_accepts_resize_message(client, db_session):
    """A JSON ``{type:'resize',cols,rows}`` frame must reach the session and
    not be forwarded to the shell as garbage text. We exercise it by sending
    the frame and checking the shell keeps running — if the router pushed
    the JSON to /bin/sh's stdin the shell would just echo it back.
    """
    _seed_admin(db_session)
    _make_host(db_session)
    token = _auth_token_for(client)

    q: Queue = Queue()
    with client.websocket_connect(f"/ws/containers/ubuntu/console?token={token}") as ws:
        stop = threading.Event()

        def _reader() -> None:
            try:
                while not stop.is_set():
                    q.put(ws.receive())
            except Exception as exc:
                q.put(exc)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        def _drain(seconds: float) -> str:
            buf = b""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    frame = q.get(timeout=0.05)
                except Empty:
                    continue
                if isinstance(frame, BaseException):
                    break
                if frame.get("type") == "websocket.disconnect":
                    break
                text = frame.get("text")
                if text is not None:
                    buf += text.encode("utf-8")
                    continue
                payload = frame.get("bytes")
                if payload is not None:
                    buf += bytes(payload)
            return buf.decode("utf-8", errors="replace")

        try:
            _drain(1.0)
            ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
            ws.send_text("echo still-alive\n")
            buf = _drain(2.5)
        finally:
            stop.set()

    assert "still-alive" in buf, f"shell stopped responding after resize; got {buf!r}"
