"""GET /v1/devices, GET /v1/devices/{id}"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from hil_controller.auth.principal import Principal
from hil_controller.auth.tokens import require_auth
from hil_controller.db.connection import get_db

router = APIRouter(prefix="/v1/devices", tags=["devices"])
Auth = Annotated[Principal, Depends(require_auth)]


class DeviceSummary(BaseModel):
    id: str
    host_id: str
    kind: str
    model: str
    capabilities: list[str]
    pool: str
    status: str


class DeviceDetail(DeviceSummary):
    serial_port: str | None
    flasher: str | None
    current_job: str | None
    host: dict[str, Any] | None
    auxes: list[dict[str, Any]]


@router.get("", response_model=list[DeviceSummary])
async def list_devices(
    request: Request,
    _auth: Auth,
    host: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    model: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    pool: str | None = Query(default=None),
) -> list[DeviceSummary]:
    db_path: str = request.app.state.db_path
    filters: list[str] = []
    params: list[Any] = []

    if host:
        filters.append("d.host_id = ?")
        params.append(host)
    if kind:
        filters.append("d.kind = ?")
        params.append(kind)
    if model:
        filters.append("d.model = ?")
        params.append(model)
    if pool:
        filters.append("d.pool = ?")
        params.append(pool)

    capability_join = ""
    if capability:
        capability_join = ", json_each(d.capabilities_json) AS jcap"
        filters.append("jcap.value = ?")
        params.append(capability)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = f"SELECT DISTINCT d.* FROM devices d{capability_join} {where} ORDER BY d.id"

    async with get_db(db_path) as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()

    return [
        DeviceSummary(
            id=r["id"],
            host_id=r["host_id"],
            kind=r["kind"],
            model=r["model"],
            capabilities=json.loads(r["capabilities_json"]),
            pool=r["pool"],
            status=r["status"],
        )
        for r in rows
    ]


@router.get("/{device_id}", response_model=DeviceDetail)
async def get_device(request: Request, device_id: str, _auth: Auth) -> DeviceDetail:
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Device not found")

        async with db.execute(
            """
            SELECT id FROM jobs
            WHERE assigned_device = ?
              AND state NOT IN ('finished','error','timeout','cancelled')
            LIMIT 1
            """,
            (device_id,),
        ) as cur:
            job_row = await cur.fetchone()

        async with db.execute(
            "SELECT id, role, addr, transport, status FROM hosts WHERE id = ?",
            (row["host_id"],),
        ) as cur:
            host_row = await cur.fetchone()

        async with db.execute(
            """
            SELECT a.* FROM auxes a
            JOIN connections c ON c.aux_id = a.id
            WHERE c.device_id = ?
            """,
            (device_id,),
        ) as cur:
            aux_rows = await cur.fetchall()

    return DeviceDetail(
        id=row["id"],
        host_id=row["host_id"],
        kind=row["kind"],
        model=row["model"],
        capabilities=json.loads(row["capabilities_json"]),
        pool=row["pool"],
        status=row["status"],
        serial_port=row["serial_port"],
        flasher=row["flasher"],
        current_job=job_row["id"] if job_row else None,
        host=dict(host_row) if host_row else None,
        auxes=[dict(a) for a in aux_rows],
    )
