"""Tests for the FastAPI app object: /health and docs gating."""

from __future__ import annotations


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "env" in body


def test_docs_available_when_enabled(client):
    """Default APP_ENV=development from conftest sets DOCS_ENABLED=True."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_openapi_available_when_docs_enabled(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "openapi" in spec
    assert "paths" in spec


def test_unhandled_exception_returns_500_without_traceback():
    """Direct unit test on the registered exception handler.

    The handler must always return JSON
        {"detail": "An internal server error occurred."}
    with status 500, and must not include the exception message in the body
    (so stack-trace-style internals cannot leak to the client).
    """
    import asyncio

    from fastapi import Request

    from main import app

    handler = app.exception_handlers.get(Exception)
    assert handler is not None, "global Exception handler not registered"

    async def _call():
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/whatever",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        response = await handler(request, RuntimeError("secret-internal-detail"))
        return response

    response = asyncio.run(_call())
    assert response.status_code == 500
    body = response.body.decode()
    assert "secret-internal-detail" not in body
    assert body == '{"detail":"An internal server error occurred."}'


def test_routers_are_mounted(client):
    """Smoke check: every documented router prefix responds with something other
    than 404 at its root (auth may redirect/422, others require auth and return
    401 — either is fine; 404 means the router isn't mounted)."""
    for path in ("/auth/login", "/containers", "/images", "/networks", "/storage", "/users"):
        response = client.post(path) if path == "/auth/login" else client.get(path)
        assert response.status_code != 404, f"router for {path} not mounted"
