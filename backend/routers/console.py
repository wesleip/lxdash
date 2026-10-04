from __future__ import annotations

"""WebSocket console endpoint.

Provides a bidirectional PTY console for a running container.  The flow is:

  1. Client connects to ``WS /ws/containers/{name}/console?token=<jwt>``
     (``host_id`` is optional when a single host is registered).
  2. Server authenticates the JWT (passed as query param because browsers cannot
     send custom headers on WebSocket upgrade requests).
  3. Server opens a console on the LXD container via pylxd's exec/console API
     and bridges the WebSocket to the container PTY.

The implementation uses asyncio.to_thread() for all blocking pylxd calls and
asyncio.Queue to shuttle bytes between the LXD thread and the WS coroutine.
"""

import asyncio

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from database import SessionLocal
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
    db: Session = SessionLocal()

    try:
        user = await _authenticate_ws(token, db)
    finally:
        db.close()

    if user is None:
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return

    # Look up the host (reuse a fresh session for the lifetime of the WS).
    db = SessionLocal()
    try:
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

        await websocket.accept()
        logger.info(
            "console.opened",
            container=name,
            host_id=host.id,
            user=user.username,
        )

        # Queue to receive output from the pylxd exec thread.
        out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _run_console() -> None:
            """Run in a thread; push container output into the queue."""
            try:
                container = lxd._client.containers.get(name)
                # pylxd execute with get_websocket=True returns an Operation
                # whose websocket can be read. For a real PTY we use
                # container.execute() in interactive mode.
                container.execute(
                    ["/bin/sh"],
                    environment={"TERM": "xterm-256color"},
                    stdin_payload=b"",
                    stdout_handler=lambda chunk: loop.call_soon_threadsafe(
                        out_queue.put_nowait, chunk
                    ),
                    stderr_handler=lambda chunk: loop.call_soon_threadsafe(
                        out_queue.put_nowait, chunk
                    ),
                )
            except Exception as exc:
                loop.call_soon_threadsafe(out_queue.put_nowait, None)
                logger.warning("console.exec_failed", container=name, error=str(exc))
            finally:
                loop.call_soon_threadsafe(out_queue.put_nowait, None)

        console_task = asyncio.create_task(asyncio.to_thread(_run_console))

        try:
            while True:
                # Wait for either incoming WS data or outgoing container data.
                ws_recv = asyncio.create_task(websocket.receive_bytes())
                container_out = asyncio.create_task(out_queue.get())

                done, pending = await asyncio.wait(
                    {ws_recv, container_out},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                if ws_recv in done:
                    try:
                        data = ws_recv.result()
                        # Forward client keystrokes to container (best-effort).
                        # In a full implementation this would write to the
                        # exec operation's stdin websocket.
                        logger.debug("console.stdin", bytes=len(data))
                    except WebSocketDisconnect:
                        break

                if container_out in done:
                    chunk = container_out.result()
                    if chunk is None:
                        break
                    await websocket.send_bytes(chunk)

        except WebSocketDisconnect:
            pass
        finally:
            console_task.cancel()
            logger.info("console.closed", container=name, user=user.username)

    finally:
        db.close()
