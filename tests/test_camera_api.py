"""Tests for the camera and ROI management API."""

from __future__ import annotations

import json

import pytest

TOKEN = "test-token-for-ci"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_camera(client, cam_id: str = "test-cam-01", url: str = "http://cam/shot.jpg"):
    from urllib.parse import urlencode

    body = urlencode([
        ("id", cam_id), ("model", "Test Cam"),
        ("stream_url", url), ("stream_type", "snapshot"),
        ("pool", "public"), ("status", "available"),
    ])
    r = await client.post(
        "/ui/cameras",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        cookies={"hil_token": TOKEN},
    )
    assert r.status_code == 200, f"create_camera failed: {r.text}"
    return cam_id


async def _create_host_and_device(client, host_id="cam-host-01", device_id="cam-dev-01"):
    await client.post(
        "/ui/hosts",
        data={"id": host_id, "role": "microcontroller-fleet", "addr": "10.0.9.1",
              "transport": "ssh", "ssh_user": "pi", "status": "available"},
        cookies={"hil_token": TOKEN},
    )
    await client.post(
        "/ui/devices",
        data={"id": device_id, "host_id": host_id, "kind": "microcontroller",
              "model": "esp32-s3", "pool": "public", "status": "available"},
        cookies={"hil_token": TOKEN},
    )
    return device_id


# ---------------------------------------------------------------------------
# Camera list / detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_cameras_empty(authed_client):
    r = await authed_client.get("/v1/cameras")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_cameras_after_create(client):
    await _create_camera(client, "list-cam-01")
    r = await client.get("/v1/cameras", headers=AUTH)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert "list-cam-01" in ids


@pytest.mark.asyncio
async def test_get_camera_detail(client):
    await _create_camera(client, "detail-cam-01", "http://192.168.1.100/shot.jpg")
    r = await client.get("/v1/cameras/detail-cam-01", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "detail-cam-01"
    assert data["source"] == "http://192.168.1.100/shot.jpg"
    assert len(data["streams"]) == 1


@pytest.mark.asyncio
async def test_get_camera_not_found(authed_client):
    r = await authed_client.get("/v1/cameras/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# ROI management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_roi_no_camera_assigned(client):
    """Device exists but has no camera_id → 422."""
    device_id = await _create_host_and_device(client, "roi-host-01", "roi-dev-01")
    r = await client.put(
        f"/v1/devices/{device_id}/camera/roi",
        json={"x": 10, "y": 20, "w": 100, "h": 80},
        headers=AUTH,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_set_roi_device_not_found(authed_client):
    r = await authed_client.put(
        "/v1/devices/nonexistent-device/camera/roi",
        json={"x": 0, "y": 0, "w": 100, "h": 100},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_roi_is_idempotent(client):
    """DELETE /roi on a device with no ROI should still return 200."""
    await _create_host_and_device(client, "del-roi-host", "del-roi-dev")
    r = await client.delete("/v1/devices/del-roi-dev/camera/roi", headers=AUTH)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_device_camera_not_found(authed_client):
    r = await authed_client.get("/v1/devices/no-such-device/camera")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_device_camera_no_assignment(client):
    await _create_host_and_device(client, "gcam-host", "gcam-dev")
    r = await client.get("/v1/devices/gcam-dev/camera", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["camera_id"] is None
    assert data["roi"] is None


# ---------------------------------------------------------------------------
# Cameras API requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cameras_list_requires_auth(client):
    r = await client.get("/v1/cameras")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_camera_snapshot_requires_auth(client):
    r = await client.get("/v1/cameras/any/snapshot")
    assert r.status_code == 401
