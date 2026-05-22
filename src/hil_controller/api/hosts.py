"""GET /v1/hosts, GET /v1/hosts/{id}"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from hil_controller.auth.principal import Principal
from hil_controller.auth.tokens import require_auth
from hil_controller.db.connection import get_db

router = APIRouter(prefix="/v1/hosts", tags=["hosts"])
Auth = Annotated[Principal, Depends(require_auth)]


class HostSummary(BaseModel):
    id: str
    role: str
    addr: str
    transport: str
    status: str
    last_seen_at: str | None
    max_concurrent_jobs: int | None
    capabilities: list[str]
    device_count: int


class HostDetail(HostSummary):
    ssh_user: str
    devices: list[dict[str, Any]]
    recent_jobs: list[dict[str, Any]]


@router.get("", response_model=list[HostSummary])
async def list_hosts(request: Request, _auth: Auth) -> list[HostSummary]:
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute(
            """
            SELECT h.id, h.role, h.addr, h.transport, h.status, h.last_seen_at,
                   h.max_concurrent_jobs, h.capabilities_json,
                   COUNT(d.id) AS device_count
            FROM hosts h
            LEFT JOIN devices d ON d.host_id = h.id
            GROUP BY h.id
            ORDER BY h.id
            """
        ) as cur:
            rows = await cur.fetchall()
    return [
        HostSummary(
            id=r["id"],
            role=r["role"],
            addr=r["addr"],
            transport=r["transport"],
            status=r["status"],
            last_seen_at=r["last_seen_at"],
            max_concurrent_jobs=r["max_concurrent_jobs"],
            capabilities=json.loads(r["capabilities_json"]),
            device_count=r["device_count"],
        )
        for r in rows
    ]


@router.get("/{host_id}", response_model=HostDetail)
async def get_host(request: Request, host_id: str, _auth: Auth) -> HostDetail:
    db_path: str = request.app.state.db_path
    async with get_db(db_path) as db:
        async with db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Host not found")

        async with db.execute(
            "SELECT * FROM devices WHERE host_id = ? ORDER BY id", (host_id,)
        ) as cur:
            device_rows = await cur.fetchall()

        async with db.execute(
            """
            SELECT id, state, result, created_at, finished_at
            FROM jobs WHERE assigned_host = ? ORDER BY created_at DESC LIMIT 10
            """,
            (host_id,),
        ) as cur:
            job_rows = await cur.fetchall()

    return HostDetail(
        id=row["id"],
        role=row["role"],
        addr=row["addr"],
        transport=row["transport"],
        status=row["status"],
        last_seen_at=row["last_seen_at"],
        max_concurrent_jobs=row["max_concurrent_jobs"],
        capabilities=json.loads(row["capabilities_json"]),
        device_count=len(device_rows),
        ssh_user=row["ssh_user"],
        devices=[dict(d) for d in device_rows],
        recent_jobs=[dict(j) for j in job_rows],
    )
