from __future__ import annotations

"""WebSocket console endpoint.

Bridges a browser xterm.js terminal to a running LXD container's PTY:

  1. Client connects to ``WS /ws/containers/{name}/console?token=<jwt>``
     (``host_id`` is optional when a single host is registered).
  2. Server authenticates the JWT (passed as query param because browsers
     cannot send custom headers on WebSocket upgrade requests).
  3. Server opens an interactive exec on the LXD container via
     :meth:`LXDClient.open_interactive_exec`, which calls
     ``raw_interactive_execute`` and yields two WebSockets (data + control).
  4. Server pumps bytes between the browser WebSocket and the LXD-side
     WebSockets until either side closes.

Wire protocol between browser and server (binary frames keep round-trip
cost low; xterm.js speaks both):

* browser → server: raw bytes, written to the container's stdin
* browser → server: JSON text frame ``{"type":"resize","cols":N,"rows":N}``
  when the viewport changes
* server → browser: raw bytes from the container's stdout/stderr

Closing any of the three WebSockets tears the other two down: the LXD-side
exec operation is reaped by LXD once the data+control sockets close, and
the browser gets a clean disconnect.
"""

import asyncio
import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from dependencies import get_db
from models.user import User
from services.auth_service import decode_token
from services.host_service import HostRegistryError, open_client, resolve_host
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/ws", tags=["console"])
logger = structlog.get_logger(__name__)

_CLOSE_POLICY_VIOLATION = 1008  # WebSocket close code


async def _authenticate_ws(token: str, db: Session) -> User | None:
    """Validate a JWT access token and return the User, or None on failure."""
    try:
        payload = decode_token(token)
    except JWTError:
        return None

    if payload.get("type") != "access":
        return None

    subject: str | None = payload.get("sub")
    if not subject:
        return None

    return db.query(User).filter(User.username == subject, User.is_active.is_(True)).first()


@router.websocket("/containers/{name}/console")
async def container_console(
    websocket: WebSocket,
    name: str,
    db: Annotated[Session, Depends(get_db)],
    token: str = Query(..., description="JWT access token"),
    host_id: int | None = Query(default=None, description="LXD host ID"),
    width: int = Query(default=80, ge=10, le=500),
    height: int = Query(default=24, ge=5, le=200),
) -> None:
    """Stream a PTY console session for *name* over WebSocket.

    Binary frames from the client are forwarded to the container's stdin.
    Output from the container is forwarded back as binary frames.

    ``host_id`` is optional: with a single registered host it is inferred, the
    same way the REST routes do.

    The connection is closed with code 1008 on auth failure.
    """
    user = await _authenticate_ws(token, db)

    if user is None:
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return

    try:
        host = resolve_host(db, host_id)
    except HostRegistryError as exc:
        logger.warning("console.host_unresolved", host_id=host_id, error=str(exc))
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return

    try:
        lxd = await open_client(host)
    except LXDClientError as exc:
        logger.warning("console.connect_failed", host_id=host.id, error=str(exc))
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return

    try:
        session = await lxd.open_interactive_exec(
            name,
            ["/bin/sh"],
            environment={
                "TERM": "xterm-256color",
                "COLUMNS": str(width),
                "LINES": str(height),
            },
        )
    except LXDClientError as exc:
        logger.warning("console.open_failed", container=name, host_id=host.id, error=str(exc))
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return

    async def pump_to_container() -> None:
        """Browser WebSocket → LXD stdin + control plane."""
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                raise WebSocketDisconnect
            payload = frame.get("bytes")
            if payload is not None:
                if payload:
                    logger.debug("console.stdin", container=name, bytes=len(payload))
                    await session.send_stdin(bytes(payload))
                continue
            text = frame.get("text")
            if text is None:
                continue
            # A text frame is either a JSON control message (``{"type":"resize",…}``)
            # or, as a fallback, raw keystrokes encoded as text (some clients
            # don't expose binary frames). Anything that parses as JSON and
            # looks like a control message is handled; everything else is
            # forwarded to the container as stdin bytes.
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                if text:
                    await session.send_stdin(text.encode("utf-8"))
                continue
            if not isinstance(msg, dict):
                if text:
                    await session.send_stdin(text.encode("utf-8"))
                continue
            if msg.get("type") == "resize":
                cols = int(msg.get("cols") or width)
                rows = int(msg.get("rows") or height)
                await session.send_resize(cols, rows)

    async def pump_from_container() -> None:
        """LXD stdout/stderr → browser WebSocket (binary frames)."""
        while True:
            chunk = await session.recv_data()
            if chunk is None:
                # EOF — the LXD-side exec operation finished.
                return
            await websocket.send_bytes(chunk)

    async with session:
        await websocket.accept()
        logger.info(
            "console.opened",
            container=name,
            host_id=host.id,
            user=user.username,
        )

        # Push the initial window size so apps like vim fill the
        # terminal correctly on the very first paint.
        await session.send_resize(width, height)

        try:
            await asyncio.gather(pump_to_container(), pump_from_container())
        except WebSocketDisconnect:
            pass
        finally:
            logger.info("console.closed", container=name, user=user.username)
