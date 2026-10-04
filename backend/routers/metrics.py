from __future__ import annotations

"""Server-Sent Events endpoint for live container statistics.

Clients connect to ``GET /containers/{name}/stats`` with an Accept header of
``text/event-stream``.  The server pushes a JSON payload every second with
CPU, memory, and network counters for the named container.

The endpoint streams until the client disconnects or an error occurs.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal
from dependencies import CurrentUser
from services.host_service import (
    AmbiguousHostError,
    HostNotFoundError,
    NoHostRegisteredError,
    open_client,
    resolve_host,
)
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
    interval: float = Query(default=1.0, ge=0.5, le=30.0, description="Poll interval in seconds"),
    host_id: int | None = Query(default=None, description="LXD host ID"),
    current_user: CurrentUser = None,  # type: ignore[assignment]
) -> EventSourceResponse:
    """Open an SSE stream that emits container stats every *interval* seconds.

    Each event has type ``stats`` and a JSON data payload.  On error an event
    of type ``error`` is emitted and the stream is closed.

    Clients should reconnect automatically on disconnect (standard SSE behaviour).
    """
    # The LXD client is resolved with a throwaway session: an SSE response has
    # no request-scoped dependency to lean on, and the client is stateless
    # after connect. The generator below is a plain async gen for that reason.
    db = SessionLocal()
    try:
        host = resolve_host(db, host_id)
    except NoHostRegisteredError as exc:
        logger.warning("metrics.no_host", host_id=host_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except AmbiguousHostError as exc:
        logger.warning("metrics.host_ambiguous", host_id=host_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HostNotFoundError as exc:
        logger.warning("metrics.host_not_found", host_id=host_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    finally:
        db.close()

    try:
        lxd = await open_client(host)
    except LXDClientError as exc:
        logger.warning("metrics.connect_failed", host_id=host.id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to the LXD host.",
        ) from exc

    return EventSourceResponse(
        _stats_generator(name, lxd, interval),
        media_type="text/event-stream",
    )
