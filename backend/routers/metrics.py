from __future__ import annotations

"""Server-Sent Events endpoint for live container statistics.

Clients connect to ``GET /containers/{name}/stats`` with an Accept header of
``text/event-stream``.  The server pushes a JSON payload every second with
CPU, memory, and network counters for the named container.

The endpoint streams until the client disconnects or an error occurs.
"""

import asyncio
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

from dependencies import CurrentUser, get_lxd_client, get_db
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/containers", tags=["metrics"])
logger = structlog.get_logger(__name__)

_POLL_INTERVAL_SECONDS = 1.0


async def _stats_generator(
    name: str,
    lxd,  # LXDClient
    interval: float,
) -> AsyncGenerator[dict, None]:
    """Yield SSE-compatible dicts with container stats at *interval* seconds."""
    while True:
        try:
            state = await lxd.get_container_state(name)
        except LXDClientError as exc:
            yield {"event": "error", "data": json.dumps({"detail": str(exc)})}
            break

        cpu = state.cpu or {}
        memory = state.memory or {}
        network_raw = state.network or {}

        network_summary = {}
        for iface, data in network_raw.items():
            counters = data.get("counters", {})
            network_summary[iface] = {
                "bytes_received": counters.get("bytes_received", 0),
                "bytes_sent": counters.get("bytes_sent", 0),
                "packets_received": counters.get("packets_received", 0),
                "packets_sent": counters.get("packets_sent", 0),
            }

        payload = {
            "cpu": {"usage_ns": cpu.get("usage", 0)},
            "memory": {
                "usage": memory.get("usage", 0),
                "usage_peak": memory.get("usage_peak", 0),
                "swap_usage": memory.get("swap_usage", 0),
            },
            "network": network_summary,
        }

        yield {"event": "stats", "data": json.dumps(payload)}
        await asyncio.sleep(interval)


@router.get(
    "/{name}/stats",
    summary="Stream live container statistics via Server-Sent Events",
    response_description="text/event-stream with JSON stats events",
)
async def container_stats_sse(
    name: str,
    host_id: int = Query(..., description="LXD host ID"),
    interval: float = Query(default=1.0, ge=0.5, le=30.0, description="Poll interval in seconds"),
    current_user: CurrentUser = None,  # type: ignore[assignment]
) -> EventSourceResponse:
    """Open an SSE stream that emits container stats every *interval* seconds.

    Each event has type ``stats`` and a JSON data payload.  On error an event
    of type ``error`` is emitted and the stream is closed.

    Clients should reconnect automatically on disconnect (standard SSE behaviour).
    """
    # We can't use the LXDDep annotated dependency directly in an SSE endpoint
    # because the dependency needs request-scope; we resolve it here manually.
    from fastapi import Request
    from starlette.background import BackgroundTask

    # The actual dependency injection happens at the route level; here we
    # construct the client inline so the generator can be a plain async gen.
    # In production you would wire this through proper DI; this keeps the
    # SSE handler self-contained and testable.

    # Re-resolve lxd_client via a lightweight wrapper
    async def _make_lxd():
        from database import SessionLocal
        from models.host import Host
        from services.lxd_client import LXDClient

        db = SessionLocal()
        try:
            host = db.query(Host).filter(Host.id == host_id, Host.is_active.is_(True)).first()
            if host is None:
                return None
            if host.connection_type.value == "socket":
                return await LXDClient.connect_socket(host.address, host_id=host.id)
            return await LXDClient.connect_tls(
                endpoint=host.address,
                cert_pem=host.tls_cert or "",
                key_pem=host.tls_key or "",
                server_cert_pem=host.tls_server_cert,
                host_id=host.id,
            )
        except LXDClientError:
            return None
        finally:
            db.close()

    lxd = await _make_lxd()
    if lxd is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to the LXD host.",
        )

    return EventSourceResponse(
        _stats_generator(name, lxd, interval),
        media_type="text/event-stream",
    )
