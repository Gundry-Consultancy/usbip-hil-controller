"""Seed hosts, devices, auxes, and connections from topology.yaml into the DB."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import yaml

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed_topology(db_path: str, topology_file: str) -> None:
    if not topology_file:
        return
    path = Path(topology_file)
    if not path.exists():
        log.warning("Topology file not found: %s", path)
        return

    data = yaml.safe_load(path.read_text()) or {}
    hosts = data.get("hosts", [])
    devices = data.get("devices", [])
    auxes = data.get("auxes", [])
    cameras = data.get("cameras", [])
    connections = data.get("connections", [])
    peripherals = data.get("peripherals", [])

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys=OFF")

        for h in hosts:
            await db.execute(
                """
                INSERT INTO hosts
                    (id, role, addr, transport, ssh_user, ssh_key_path,
                     max_concurrent_jobs, capabilities_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    role=excluded.role, addr=excluded.addr,
                    transport=excluded.transport, ssh_user=excluded.ssh_user,
                    ssh_key_path=excluded.ssh_key_path,
                    max_concurrent_jobs=excluded.max_concurrent_jobs,
                    capabilities_json=excluded.capabilities_json
                """,
                (
                    h["id"],
                    h.get("role", ""),
                    h.get("addr", ""),
                    h.get("transport", "ssh"),
                    h.get("ssh_user", "pi"),
                    h.get("ssh_key_path"),
                    h.get("max_concurrent_jobs"),
                    json.dumps(h.get("capabilities", [])),
                    h.get("status", "available"),
                ),
            )

        for cam in cameras:
            await db.execute(
                """
                INSERT INTO cameras
                    (id, host_id, source, model, resolution_w, resolution_h, fps,
                     pool, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    host_id=excluded.host_id, source=excluded.source,
                    model=excluded.model,
                    resolution_w=excluded.resolution_w, resolution_h=excluded.resolution_h,
                    fps=excluded.fps, pool=excluded.pool, notes=excluded.notes
                """,
                (
                    cam["id"],
                    cam.get("host_id"),
                    cam.get("source", ""),
                    cam.get("model", ""),
                    cam.get("resolution", [None, None])[0],
                    cam.get("resolution", [None, None])[1],
                    cam.get("fps"),
                    cam.get("pool", "public"),
                    cam.get("status", "available"),
                    cam.get("notes"),
                ),
            )

        for d in devices:
            hub_host_id = d.get("hub_host_id") or d["host_id"]
            await db.execute(
                """
                INSERT INTO devices
                    (id, host_id, kind, model, capabilities_json, usb_json,
                     pool, status, serial_port, flasher, camera_id, qr_identifier,
                     hub_host_id, hub_port_path, solenoid_channel, usb_serial)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    host_id=excluded.host_id, kind=excluded.kind,
                    model=excluded.model,
                    capabilities_json=excluded.capabilities_json,
                    usb_json=excluded.usb_json,
                    pool=excluded.pool,
                    serial_port=excluded.serial_port,
                    flasher=excluded.flasher,
                    camera_id=excluded.camera_id,
                    qr_identifier=excluded.qr_identifier,
                    hub_host_id=excluded.hub_host_id,
                    hub_port_path=excluded.hub_port_path,
                    solenoid_channel=excluded.solenoid_channel,
                    usb_serial=excluded.usb_serial
                """,
                (
                    d["id"],
                    d["host_id"],
                    d.get("kind", ""),
                    d.get("model", ""),
                    json.dumps(d.get("capabilities", [])),
                    json.dumps(d["usb"]) if "usb" in d else None,
                    d.get("pool", "public"),
                    d.get("status", "available"),
                    d.get("serial_port"),
                    d.get("flasher"),
                    d.get("camera_id"),
                    d.get("qr_identifier"),
                    hub_host_id,
                    d.get("hub_port_path"),
                    d.get("solenoid_channel"),
                    d.get("usb_serial"),
                ),
            )
            await _seed_usb_ids(db, d)

        for a in auxes:
            await db.execute(
                """
                INSERT INTO auxes
                    (id, kind, model, capabilities_json, interface,
                     observability, pool, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind, model=excluded.model,
                    capabilities_json=excluded.capabilities_json,
                    interface=excluded.interface,
                    observability=excluded.observability,
                    pool=excluded.pool
                """,
                (
                    a["id"],
                    a.get("kind", ""),
                    a.get("model", ""),
                    json.dumps(a.get("capabilities", [])),
                    a.get("interface", ""),
                    a.get("observability", "none"),
                    a.get("pool", "public"),
                    a.get("status", "available"),
                ),
            )

        for p in peripherals:
            await db.execute(
                """
                INSERT INTO peripherals
                    (id, kind, model, product_url, specs_json, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind, model=excluded.model,
                    product_url=excluded.product_url,
                    specs_json=excluded.specs_json,
                    notes=excluded.notes
                """,
                (
                    p["id"],
                    p.get("kind", "display"),
                    p.get("model", ""),
                    p.get("product_url"),
                    json.dumps(p["specs"]) if "specs" in p else None,
                    p.get("notes"),
                ),
            )

        # Seed device→peripheral associations from peripheral_ids on each device.
        for d in devices:
            for pid in d.get("peripheral_ids", []):
                await db.execute(
                    """
                    INSERT OR IGNORE INTO device_peripherals (device_id, peripheral_id)
                    VALUES (?, ?)
                    """,
                    (d["id"], pid),
                )

        if connections:
            await db.execute("DELETE FROM connections")
            for c in connections:
                await db.execute(
                    "INSERT INTO connections (aux_id, device_id, mux_id, mux_channel) VALUES (?, ?, ?, ?)",
                    (c["aux"], c.get("device"), c.get("mux"), c.get("channel")),
                )

        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()

    log.info(
        "Seeded %d hosts, %d devices, %d auxes, %d cameras, %d peripherals from %s",
        len(hosts),
        len(devices),
        len(auxes),
        len(cameras),
        len(peripherals),
        path,
    )


async def _seed_usb_ids(db: aiosqlite.Connection, device: dict) -> None:
    """Seed device_usb_ids from a device's usb_ids list or legacy usb block.

    Idempotent: re-running upserts last_seen_at and refreshes role/description,
    but does not duplicate rows (UNIQUE on device_id, vid, pid, iserial).
    """
    rows: list[dict] = []
    if "usb_ids" in device and isinstance(device["usb_ids"], list):
        rows = list(device["usb_ids"])
    elif "usb" in device and isinstance(device["usb"], dict):
        # Legacy single-id block — treat as one unknown-role row.
        rows = [{"vid": device["usb"].get("vid"), "pid": device["usb"].get("pid"),
                 "role": "unknown"}]

    if not rows:
        return

    now = _now_iso()
    device_id = device["id"]
    for r in rows:
        vid = (r.get("vid") or "").strip().lower()
        pid = (r.get("pid") or "").strip().lower()
        if not (vid and pid):
            continue
        iserial = r.get("iserial")
        role = r.get("role") or "unknown"
        description = r.get("description")
        bcd = r.get("bcd_device")

        # Upsert: if exact (device_id, vid, pid, iserial) row exists, refresh
        # role/description/last_seen; otherwise insert.
        async with db.execute(
            "SELECT id FROM device_usb_ids "
            "WHERE device_id=? AND vid=? AND pid=? AND COALESCE(iserial,'')=COALESCE(?,'')",
            (device_id, vid, pid, iserial),
        ) as cur:
            existing = await cur.fetchone()

        if existing:
            await db.execute(
                "UPDATE device_usb_ids "
                "SET role=?, description=COALESCE(?, description), "
                "    bcd_device=COALESCE(?, bcd_device), last_seen_at=? "
                "WHERE id=?",
                (role, description, bcd, now, existing[0]),
            )
        else:
            await db.execute(
                "INSERT INTO device_usb_ids "
                "(device_id, vid, pid, role, bcd_device, description, iserial, "
                " first_seen_at, last_seen_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'seeder')",
                (device_id, vid, pid, role, bcd, description, iserial, now, now),
            )
