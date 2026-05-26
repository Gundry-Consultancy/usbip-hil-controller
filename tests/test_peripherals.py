"""Tests for the peripherals topology section: seeder, DB, and API."""

import pytest


# ---------------------------------------------------------------------------
# Seeder — peripherals table populated from topology.yaml
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeder_creates_peripheral_records(seeded_client):
    """Topology seed must create peripheral rows accessible via topology API."""
    r = await seeded_client.get("/v1/topology")
    assert r.status_code == 200
    body = r.json()
    periph_ids = {p["id"] for p in body["peripherals"]}
    assert "fake-oled-periph-01" in periph_ids


@pytest.mark.asyncio
async def test_seeder_peripheral_fields_are_correct(seeded_client):
    r = await seeded_client.get("/v1/topology")
    assert r.status_code == 200
    periph = next(
        p for p in r.json()["peripherals"] if p["id"] == "fake-oled-periph-01"
    )
    assert periph["kind"] == "display"
    assert periph["model"] == "OLED 128x32"
    assert periph["product_url"] == "https://adafru.it/2900"
    assert periph["notes"] == "Monochrome OLED FeatherWing 128x32"


@pytest.mark.asyncio
async def test_seeder_links_device_to_peripheral(seeded_client):
    """device_peripherals junction must be seeded from peripheral_ids on devices."""
    r = await seeded_client.get("/v1/topology")
    assert r.status_code == 200
    body = r.json()
    qtpy = next(d for d in body["devices"] if d["id"] == "fake-qtpy-01")
    assert "peripheral_ids" in qtpy
    assert "fake-oled-periph-01" in qtpy["peripheral_ids"]


@pytest.mark.asyncio
async def test_device_without_peripherals_has_empty_list(seeded_client):
    """SBC device with no peripheral_ids must have an empty list, not missing key."""
    r = await seeded_client.get("/v1/topology")
    assert r.status_code == 200
    pi5 = next(d for d in r.json()["devices"] if d["id"] == "fake-pi5-01")
    assert "peripheral_ids" in pi5
    assert pi5["peripheral_ids"] == []


# ---------------------------------------------------------------------------
# DB integrity — foreign key references
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topology_peripherals_section_is_present(seeded_client):
    r = await seeded_client.get("/v1/topology")
    assert r.status_code == 200
    assert "peripherals" in r.json()


@pytest.mark.asyncio
async def test_topology_requires_auth_for_peripherals(client):
    r = await client.get("/v1/topology")
    assert r.status_code == 401
