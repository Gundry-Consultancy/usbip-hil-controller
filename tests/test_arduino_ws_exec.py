"""Phase 2 tests: ArduinoWsExecAdapter — phase-aware multi-transport routing.

Build/flash/run are routed to a controller vs DUT-host transport per an
`exec` plan. The usbip flash path is wrapped in an exclusive_device lease and
tears the bridge down in a finally. All via fake transports — no hardware.
"""

from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hil_controller.adapters.arduino_ws_exec import ArduinoWsExecAdapter
from hil_controller.hosts.base import ExecResult


def _result(exit_status=0, stdout="", stderr=""):
    r = MagicMock(spec=ExecResult)
    r.exit_status = exit_status
    r.stdout = stdout
    r.stderr = stderr
    return r


def _transport():
    t = AsyncMock()
    t.exec = AsyncMock(return_value=_result(0))
    t.copy_to = AsyncMock(return_value=None)
    t.copy_from = AsyncMock(return_value=None)
    return t


def _argvs(t):
    return [c.args[0] for c in t.exec.call_args_list]


def _make(*, controller, dut, flash_mode="usbip", build_host="controller", db_path="db"):
    return ArduinoWsExecAdapter(
        controller_transport=controller,
        dut_transport=dut,
        job_id="job-1",
        source={
            "repo": "https://github.com/tyeth/Adafruit_WipperSnapper_Arduino.git",
            "ref": "displays-v2",
            "setup": ["bash", "-c", "python3 -m venv .venv && pio run -e revtft"],
        },
        params={"entry": "bash", "args": ["-c", "cd protomq && npm start"]},
        exec_plan={
            "build_host": build_host,
            "flash_mode": flash_mode,
            "test_host": "none",
            "protomq_host": "controller",
            "pio_env": "adafruit_feather_esp32s3_reversetft",
        },
        device={"id": "mcu-revtft", "hub_port_path": "1-1.1.1.4"},
        server_addr="192.168.1.234",
        db_path=db_path,
        work_dir=PurePosixPath("/tmp/hil/job-1"),
    )


@pytest.fixture
def fake_leases():
    with patch("hil_controller.adapters.arduino_ws_exec.leases") as m:
        m.acquire = AsyncMock(return_value={"id": 42})
        m.release = AsyncMock(return_value=True)
        yield m


async def _controller_with_usbip(controller):
    """Wire a controller transport so the usbip flash path succeeds."""

    async def controller_exec(argv, **kw):
        if argv[0] == "bash" and "ttyACM" in argv[-1]:
            n = sum(
                1
                for c in controller.exec.call_args_list
                if c.args[0][0] == "bash" and "ttyACM" in c.args[0][-1]
            )
            return _result(0, stdout="" if n <= 1 else "/dev/ttyACM0\n")
        if argv[:3] == ["sudo", "usbip", "port"]:
            return _result(0, stdout="Port 00:\n x -> usbip://h/1-1.1.1.4\n")
        return _result(0)

    controller.exec.side_effect = controller_exec


@pytest.mark.asyncio
async def test_build_runs_clone_and_setup_on_controller(fake_leases):
    controller, dut = _transport(), _transport()
    await _controller_with_usbip(controller)
    adapter = _make(controller=controller, dut=dut)
    adapter._settle_s = 0
    await adapter.deploy()
    # the repo clone + setup chain landed on the controller, not the DUT host
    c = _argvs(controller)
    assert any("git" in a and "clone" in a for a in c)
    assert any(a[:2] == ["bash", "-c"] and "pio run" in a[2] for a in c)


@pytest.mark.asyncio
async def test_usbip_flash_binds_on_dut_attaches_uploads_on_controller(fake_leases):
    controller, dut = _transport(), _transport()

    async def controller_exec(argv, **kw):
        if argv[0] == "bash" and "ttyACM" in argv[-1]:
            n = sum(1 for c in controller.exec.call_args_list if c.args[0][0] == "bash" and "ttyACM" in c.args[0][-1])
            return _result(0, stdout="" if n <= 1 else "/dev/ttyACM0\n")
        if argv[:3] == ["sudo", "usbip", "port"]:
            return _result(0, stdout="Port 00:\n x -> usbip://h/1-1.1.1.4\n")
        return _result(0)

    controller.exec.side_effect = controller_exec
    adapter = _make(controller=controller, dut=dut)
    adapter._settle_s = 0
    await adapter.deploy()

    dut_cmds, c_cmds = _argvs(dut), _argvs(controller)
    assert ["sudo", "usbip", "bind", "-b", "1-1.1.1.4"] in dut_cmds
    assert any(a[:3] == ["sudo", "usbip", "attach"] for a in c_cmds)
    # the upload (pio --target upload) ran on the controller against the new port
    assert any(
        a[0] == "bash" and "--target upload" in a[-1] and "/dev/ttyACM0" in a[-1]
        for a in c_cmds
    )
    fake_leases.acquire.assert_awaited_once()
    fake_leases.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_usbip_flash_releases_lease_even_on_failure(fake_leases):
    controller, dut = _transport(), _transport()

    async def controller_exec(argv, **kw):
        if argv[0] == "bash" and "ttyACM" in argv[-1]:
            return _result(0, stdout="")  # no port ever appears
        if argv[:3] == ["sudo", "usbip", "port"]:
            return _result(0, stdout="")
        return _result(0)

    controller.exec.side_effect = controller_exec
    adapter = _make(controller=controller, dut=dut)
    adapter._settle_s = 0
    with pytest.raises(RuntimeError):
        await adapter.deploy()
    fake_leases.release.assert_awaited_once_with("db", 42)


@pytest.mark.asyncio
async def test_ship_artifacts_copies_build_then_esptools_on_dut(fake_leases):
    controller, dut = _transport(), _transport()
    adapter = _make(controller=controller, dut=dut, flash_mode="ship-artifacts")
    await adapter.deploy()
    # pulled artifacts off the controller and pushed them to the DUT host
    controller.copy_from.assert_awaited()
    dut.copy_to.assert_awaited()
    # esptool ran on the DUT host
    assert any("esptool" in a[-1] for a in _argvs(dut) if a and a[0] == "bash")
    # ship-artifacts does not take a usbip lease
    fake_leases.acquire.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_executes_on_controller_for_protomq_host(fake_leases):
    controller, dut = _transport(), _transport()
    controller.exec.return_value = _result(0, stdout="ok")
    adapter = _make(controller=controller, dut=dut)
    result = await adapter.run()
    assert result == "pass"
    assert any(a[:2] == ["bash", "-c"] and "npm start" in a[2] for a in _argvs(controller))
    # nothing ran on the DUT host during run()
    assert _argvs(dut) == []


@pytest.mark.asyncio
async def test_cross_host_build_run_is_rejected_clearly(fake_leases):
    controller, dut = _transport(), _transport()
    adapter = ArduinoWsExecAdapter(
        controller_transport=controller,
        dut_transport=dut,
        job_id="job-x",
        source={"repo": "r", "ref": "m", "setup": []},
        params={"entry": "bash", "args": ["-c", "true"]},
        exec_plan={
            "build_host": "controller",
            "flash_mode": "usbip",
            "test_host": "dut-host",  # run on DUT but build on controller
            "protomq_host": "off",
            "pio_env": "env",
        },
        device={"id": "d", "hub_port_path": "1-1"},
        server_addr="1.2.3.4",
        db_path="db",
    )
    with pytest.raises(NotImplementedError):
        await adapter.deploy()
