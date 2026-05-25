"""Camera and ROI management API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hil_controller.auth.principal import Principal
from hil_controller.auth.tokens import require_auth
from hil_controller.db.connection import get_db, now_iso

router = APIRouter(tags=["cameras"])
Auth = Annotated[Principal, Depends(require_auth)]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CameraSummary(BaseModel):
    id: str
    host_id: Optional[str]
    source: str
    model: str
    pool: str
    status: str
    notes: Optional[str]
    streams: list[dict[str, Any]]


class ROIResponse(BaseModel):
    device_id: str
    camera_id: str
    x: int
    y: int
    w: int
    h: int
    source: str
    confidence: Optional[float]
    updated_at: str


class ROISetRequest(BaseModel):
    x: int
    y: int
    w: int
    h: int


# ---------------------------------------------------------------------------
# Camera list / detail
# ---------------------------------------------------------------------------


def _parse_streams(row: dict) -> list[dict[str, Any]]:
    raw = row.get("streams_json")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    if row.get("source"):
        return [{"url": row["source"], "type": "snapshot"}]
    return []


@router.get("/v1/cameras", response_model=list[CameraSummary])
async def list_cameras(request: Request, _auth: Auth) -> list[CameraSummary]:
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute("SELECT * FROM cameras ORDER BY id") as cur:
            rows = await cur.fetchall()
    return [
        CameraSummary(
            id=r["id"],
            host_id=r["host_id"],
            source=r["source"],
            model=r["model"],
            pool=r["pool"],
            status=r["status"],
            notes=r["notes"],
            streams=_parse_streams(dict(r)),
        )
        for r in rows
    ]


@router.get("/v1/cameras/{cam_id}", response_model=CameraSummary)
async def get_camera(request: Request, cam_id: str, _auth: Auth) -> CameraSummary:
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute("SELECT * FROM cameras WHERE id = ?", (cam_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    r = dict(row)
    return CameraSummary(
        id=r["id"],
        host_id=r["host_id"],
        source=r["source"],
        model=r["model"],
        pool=r["pool"],
        status=r["status"],
        notes=r["notes"],
        streams=_parse_streams(r),
    )


# ---------------------------------------------------------------------------
# Camera snapshot
# ---------------------------------------------------------------------------


@router.get("/v1/cameras/{cam_id}/snapshot")
async def camera_snapshot(request: Request, cam_id: str, _auth: Auth) -> Response:
    """Return a single JPEG frame from the camera's primary source URL."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute("SELECT source, streams_json FROM cameras WHERE id = ?", (cam_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    streams = _parse_streams(dict(row))
    # Use first snapshot-type stream, then any stream
    url = None
    for s in streams:
        if s.get("type") in ("snapshot", "mjpeg", "rtsp"):
            url = s.get("url")
            break
    if url is None and row["source"]:
        url = row["source"]
    if not url:
        raise HTTPException(status_code=503, detail="Camera has no stream URL configured")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return Response(content=r.content, media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch frame: {exc}") from exc


# ---------------------------------------------------------------------------
# Device camera assignment + ROI
# ---------------------------------------------------------------------------


@router.get("/v1/devices/{device_id}/camera")
async def get_device_camera(
    request: Request, device_id: str, _auth: Auth
) -> dict[str, Any]:
    """Return the camera assignment and current ROI for a device."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT camera_id, qr_identifier FROM devices WHERE id = ?", (device_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Device not found")

        roi = None
        async with db.execute(
            "SELECT * FROM camera_rois WHERE device_id = ?", (device_id,)
        ) as cur:
            roi_row = await cur.fetchone()
        if roi_row:
            roi = dict(roi_row)

    return {
        "device_id": device_id,
        "camera_id": row["camera_id"],
        "qr_identifier": row["qr_identifier"],
        "roi": roi,
    }


@router.put("/v1/devices/{device_id}/camera/roi", response_model=ROIResponse)
async def set_device_roi(
    request: Request, device_id: str, body: ROISetRequest, _auth: Auth
) -> ROIResponse:
    """Set a manual ROI for a device."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT camera_id FROM devices WHERE id = ?", (device_id,)
        ) as cur:
            dev = await cur.fetchone()
        if dev is None:
            raise HTTPException(status_code=404, detail="Device not found")
        if not dev["camera_id"]:
            raise HTTPException(status_code=422, detail="Device has no camera assigned")

        ts = now_iso()
        await db.execute(
            """INSERT INTO camera_rois (device_id, camera_id, x, y, w, h, source, confidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'manual', NULL, ?)
               ON CONFLICT(device_id) DO UPDATE SET
                 x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h,
                 source='manual', confidence=NULL, updated_at=excluded.updated_at""",
            (device_id, dev["camera_id"], body.x, body.y, body.w, body.h, ts),
        )
        await db.commit()

    return ROIResponse(
        device_id=device_id,
        camera_id=dev["camera_id"],
        x=body.x,
        y=body.y,
        w=body.w,
        h=body.h,
        source="manual",
        confidence=None,
        updated_at=ts,
    )


@router.delete("/v1/devices/{device_id}/camera/roi")
async def delete_device_roi(
    request: Request, device_id: str, _auth: Auth
) -> dict[str, str]:
    """Clear manual ROI override for a device."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        await db.execute("DELETE FROM camera_rois WHERE device_id = ?", (device_id,))
        await db.commit()
    return {"status": "cleared", "device_id": device_id}


@router.get("/v1/devices/{device_id}/camera/snapshot")
async def device_camera_snapshot(
    request: Request, device_id: str, _auth: Auth
) -> Response:
    """Return the current frame cropped to the device's ROI."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT d.camera_id, r.x, r.y, r.w, r.h, c.source, c.streams_json "
            "FROM devices d "
            "LEFT JOIN camera_rois r ON r.device_id = d.id "
            "LEFT JOIN cameras c ON c.id = d.camera_id "
            "WHERE d.id = ?",
            (device_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if not row["camera_id"]:
        raise HTTPException(status_code=422, detail="Device has no camera assigned")

    # Fetch full frame
    streams = _parse_streams({"source": row["source"], "streams_json": row["streams_json"]})
    url = next((s["url"] for s in streams if s.get("type") in ("snapshot", "mjpeg")), row["source"])
    if not url:
        raise HTTPException(status_code=503, detail="Camera has no stream URL")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            frame_bytes = r.content
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch frame: {exc}") from exc

    # Crop if ROI exists
    if row["x"] is not None:
        try:
            import cv2
            import numpy as np

            arr = np.frombuffer(frame_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                x, y, w, h = int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])
                crop = img[y : y + h, x : x + w]
                _, buf = cv2.imencode(".jpg", crop)
                return Response(content=buf.tobytes(), media_type="image/jpeg")
        except ImportError:
            pass  # cv2 not available; return full frame

    return Response(content=frame_bytes, media_type="image/jpeg")


@router.post("/v1/devices/{device_id}/camera/calibrate")
async def calibrate_device_roi(
    request: Request, device_id: str, _auth: Auth
) -> dict[str, Any]:
    """Trigger QR auto-detection on a live frame; return proposed ROI (does not save)."""
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT d.camera_id, d.qr_identifier, c.source, c.streams_json "
            "FROM devices d LEFT JOIN cameras c ON c.id = d.camera_id "
            "WHERE d.id = ?",
            (device_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if not row["camera_id"]:
        raise HTTPException(status_code=422, detail="Device has no camera assigned")
    if not row["qr_identifier"]:
        raise HTTPException(status_code=422, detail="Device has no qr_identifier set")

    streams = _parse_streams({"source": row["source"], "streams_json": row["streams_json"]})
    url = next((s["url"] for s in streams if s.get("type") in ("snapshot", "mjpeg")), row["source"])
    if not url:
        raise HTTPException(status_code=503, detail="Camera has no stream URL")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            frame_bytes = r.content
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch frame: {exc}") from exc

    try:
        import cv2
        import numpy as np

        from hil_controller.adapters.camera.qr_locator import (
            scan_qr_codes,
            segment_board_roi,
        )

        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"found": False, "reason": "frame_decode_failed"}

        qrs = scan_qr_codes(img)
        qr_id = row["qr_identifier"]
        if qr_id not in qrs:
            return {"found": False, "reason": "no_qr_detected", "qr_identifier": qr_id}

        bbox = qrs[qr_id]
        board = segment_board_roi(img, bbox)
        return {
            "found": True,
            "qr_data": qr_id,
            "roi": {"x": board.x, "y": board.y, "w": board.w, "h": board.h},
            "confidence": 0.9,
        }
    except ImportError:
        return {"found": False, "reason": "cv2_not_available"}


@router.post("/v1/devices/{device_id}/camera/calibrate/save")
async def save_calibration(
    request: Request, device_id: str, _auth: Auth
) -> ROIResponse:
    """Run QR calibration and save the result to camera_rois."""
    result = await calibrate_device_roi(request, device_id, _auth)
    if not result.get("found"):
        raise HTTPException(status_code=422, detail=result.get("reason", "calibration_failed"))

    roi = result["roi"]
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT camera_id FROM devices WHERE id = ?", (device_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    ts = now_iso()
    async with get_db(db_path) as db:
        await db.execute(
            """INSERT INTO camera_rois (device_id, camera_id, x, y, w, h, source, confidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'qr_auto', ?, ?)
               ON CONFLICT(device_id) DO UPDATE SET
                 x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h,
                 source='qr_auto', confidence=excluded.confidence, updated_at=excluded.updated_at""",
            (device_id, row["camera_id"], roi["x"], roi["y"], roi["w"], roi["h"],
             result.get("confidence", 0.9), ts),
        )
        await db.commit()

    return ROIResponse(
        device_id=device_id,
        camera_id=row["camera_id"],
        x=roi["x"],
        y=roi["y"],
        w=roi["w"],
        h=roi["h"],
        source="qr_auto",
        confidence=result.get("confidence"),
        updated_at=ts,
    )
