"""Tests for services.lxd_probe — the raw LXD REST API transport."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.lxd_probe import (
    LXDProbeError,
    ensure_socket_accessible,
    fetch_resources,
    fetch_server_info,
    post_cluster_preseed,
)
from tests.conftest import patch_socket_access

SOCKET = "/lxd-test/unix.socket"


def _response(status_code: int, json_body: dict | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = ""
    return response


def _client(*responses: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=list(responses))
    client.post = AsyncMock(side_effect=list(responses))
    return client


@pytest.fixture
def reachable_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    patch_socket_access(monkeypatch)


# ---------------------------------------------------------------------------
# Socket pre-flight
# ---------------------------------------------------------------------------


def test_missing_socket_names_the_alternative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Debian/Ubuntu's deb install puts the socket elsewhere than the snap."""
    monkeypatch.setattr("os.path.exists", lambda _: False)

    with pytest.raises(LXDProbeError) as excinfo:
        ensure_socket_accessible("/var/snap/lxd/common/lxd/unix.socket")

    assert "/var/lib/lxd/unix.socket" in str(excinfo.value)


def test_permission_error_names_uids_and_gids(monkeypatch: pytest.MonkeyPatch) -> None:
    import stat as stat_mod

    sock_stat = type(
        "Stat",
        (),
        {"st_mode": stat_mod.S_IFSOCK | 0o660, "st_uid": 0, "st_gid": 998},
    )()
    monkeypatch.setattr("os.path.exists", lambda _: True)
    monkeypatch.setattr("os.stat", lambda _: sock_stat)
    monkeypatch.setattr("os.getuid", lambda: 999)
    monkeypatch.setattr("os.getgid", lambda: 999)
    monkeypatch.setattr("os.getgroups", lambda: [999])

    with pytest.raises(LXDProbeError) as excinfo:
        ensure_socket_accessible(SOCKET)

    msg = str(excinfo.value)
    assert "Permission denied" in msg
    assert "UID 999" in msg and "GID 998" in msg
    assert "LXD_GID" in msg


def test_regular_file_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import stat as stat_mod

    monkeypatch.setattr("os.path.exists", lambda _: True)
    monkeypatch.setattr("os.stat", lambda _: type("S", (), {"st_mode": stat_mod.S_IFREG | 0o644})())

    with pytest.raises(LXDProbeError, match="not a Unix socket"):
        ensure_socket_accessible(SOCKET)


# ---------------------------------------------------------------------------
# fetch_server_info
# ---------------------------------------------------------------------------


async def test_server_info_reports_a_clustered_daemon(reachable_socket) -> None:
    root = _response(
        200,
        {
            "metadata": {
                "api_version": "1.0",
                "api_extensions": ["storage", "clustering"],
                "server": "lxd",
                "public": False,
                "auth": "trusted",
                "auth_user_method": "tls",
            }
        },
    )
    cluster = _response(
        200,
        {"metadata": {"enabled": True, "server_name": "node1", "certificate_fingerprint": "abc"}},
    )

    with patch(
        "services.lxd_probe.httpx.AsyncClient",
        return_value=_client(root, cluster),
    ):
        info = await fetch_server_info(SOCKET)

    assert info.api_version == "1.0"
    assert info.api_extensions == ("storage", "clustering")
    assert info.auth_user_method == "tls"
    assert info.cluster_state == "present"
    assert info.clustered is True
    assert info.server_name == "node1"
    assert info.certificate_fingerprint == "abc"


async def test_server_info_reports_a_standalone_daemon(reachable_socket) -> None:
    """enabled=false on /1.0/cluster is a fully working single-node LXD."""
    root = _response(200, {"metadata": {"api_version": "1.0", "server": "lxd"}})
    cluster = _response(200, {"metadata": {"enabled": False, "server_name": "node1"}})

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(root, cluster)):
        info = await fetch_server_info(SOCKET)

    assert info.cluster_state == "present"
    assert info.clustered is False


async def test_server_info_reports_an_absent_cluster(reachable_socket) -> None:
    root = _response(200, {"metadata": {"api_version": "1.0", "server": "lxd", "public": True}})
    cluster = _response(404, {"error": "not found"})

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(root, cluster)):
        info = await fetch_server_info(SOCKET)

    assert info.cluster_state == "absent"
    assert info.clustered is False


async def test_server_info_reports_an_untrusted_cluster(reachable_socket) -> None:
    root = _response(200, {"metadata": {"api_version": "1.0", "server": "lxd"}})
    cluster = _response(403, {"error": "not authorized"})

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(root, cluster)):
        info = await fetch_server_info(SOCKET)

    assert info.cluster_state == "forbidden"


async def test_server_info_raises_when_root_is_not_200(reachable_socket) -> None:
    root = _response(500, {"error": "Internal server error"})

    with (
        patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(root)),
        pytest.raises(LXDProbeError, match="HTTP 500"),
    ):
        await fetch_server_info(SOCKET)


async def test_server_info_converts_transport_errors(reachable_socket) -> None:
    client = _client()
    client.get = AsyncMock(side_effect=httpx.ConnectError("no route to host"))

    with (
        patch("services.lxd_probe.httpx.AsyncClient", return_value=client),
        pytest.raises(LXDProbeError, match="Cannot reach LXD daemon"),
    ):
        await fetch_server_info(SOCKET)


async def test_tls_probe_requires_client_material() -> None:
    with pytest.raises(LXDProbeError, match="no client certificate"):
        await fetch_server_info("https://10.0.0.1:8443", "tls")


# ---------------------------------------------------------------------------
# fetch_resources
# ---------------------------------------------------------------------------


async def test_resources_are_parsed(reachable_socket) -> None:
    response = _response(
        200,
        {
            "metadata": {
                "cpu": {"total": 16},
                "memory": {"total": 34_000_000_000},
                "system": {
                    "architecture": "x86_64",
                    "os_name": "Ubuntu",
                    "os_version": "24.04",
                    "hostname": "srv01",
                },
            }
        },
    )

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(response)):
        resources = await fetch_resources(SOCKET)

    assert resources.cpu_total == 16
    assert resources.memory_total == 34_000_000_000
    assert resources.architecture == "x86_64"
    assert resources.hostname == "srv01"


async def test_resources_degrade_to_defaults(reachable_socket) -> None:
    """A daemon without /1.0/resources must not fail the health check."""
    response = _response(404, {"error": "not found"})

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(response)):
        resources = await fetch_resources(SOCKET)

    assert resources.cpu_total is None
    assert resources.hostname is None


# ---------------------------------------------------------------------------
# post_cluster_preseed
# ---------------------------------------------------------------------------


async def test_preseed_accepts_202(reachable_socket) -> None:
    response = _response(202, {"type": "async", "operation": "/1.0/operations/1"})

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(response)):
        status = await post_cluster_preseed(SOCKET, {"cluster": {"server_name": "node1"}})

    assert status == 202


async def test_preseed_surfaces_the_lxd_error(reachable_socket) -> None:
    response = _response(400, {"error": "LXD cluster is already enabled"})

    with (
        patch("services.lxd_probe.httpx.AsyncClient", return_value=_client(response)),
        pytest.raises(LXDProbeError, match="LXD cluster is already enabled"),
    ):
        await post_cluster_preseed(SOCKET, {"cluster": {"server_name": "node1"}})


async def test_preseed_posts_to_the_cluster_endpoint(reachable_socket) -> None:
    client = _client(_response(202, {}))
    preseed = {"cluster": {"server_name": "node1", "enabled": True}}

    with patch("services.lxd_probe.httpx.AsyncClient", return_value=client):
        await post_cluster_preseed(SOCKET, preseed)

    url, kwargs = client.post.call_args.args[0], client.post.call_args.kwargs
    assert url.endswith("/1.0/cluster")
    assert kwargs["json"] == preseed
