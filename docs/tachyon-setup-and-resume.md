# Tachyon HIL Setup — State & Resume Guide

## Machine

| Field | Value |
|-------|-------|
| Host | `192.168.1.169` |
| User | `particle` (sudo, gpio groups) |
| OS | Ubuntu 24.04, aarch64, kernel `6.8.0-1058-particle` |
| Board | Particle Tachyon (Quectel QCM6490) |
| Attached DUT hardware | Adafruit EYESPI Pi Beret + ILI9341 2.2" 240×320 SPI TFT |
| SSH key | `~/.ssh/id_ed25519` (must be in agent: `ssh-add ~/.ssh/id_ed25519`) |

---

## What Was Done

### HIL Controller (this repo)

- Cloned to `~/dev-projects/python/usbip-hil-controller` on the Tachyon
- Installed into a venv: `~/dev-projects/python/usbip-hil-controller/.venv`
- Config lives in `~/dev-projects/python/usbip-hil-controller/run/`:
  - `controller.env` — DB path, topology path, bind address, static token
  - `topology.yaml` — full topology (see below)
  - `jobs.db` — SQLite job DB (auto-created; delete to reset)

**Topology registered:**

| Resource | ID | Type | Notes |
|---|---|---|---|
| Host (runner) | `localhost` | `kind: local` | Tachyon itself, runs python-snapper jobs |
| Host (broker) | `tachyon-protomq` | `role: protomq-broker` | ProtoMQ at `127.0.0.1:1884` API:5173 |
| Device | `tachyon-runner-a` | `sbc / particle-tachyon` | pool: wippersnapper-python |
| Aux | `tachyon-ili9341` | `display / ili9341-240x320` | Connected to tachyon-runner-a via SPI |

**ProtoMQ script for the ILI9341:** `tachyon-eyespi-beret-ili9341-240x320-demo`

### Wippersnapper Python repo

- Cloned to `~/dev-projects/python/Adafruit_Wippersnapper_Python` on the Tachyon
- Branch: `displays-v2`
- Venv: `~/dev-projects/python/Adafruit_Wippersnapper_Python/.venv`
- `.env` at repo root: `PROTOMQ_RUN_EXTERNALLY=False` (test fixture self-starts ProtoMQ)
- Fix applied: `pixels/hardware.py` — `import board` moved inside `PixelStrand.__init__` (lazy) so collection doesn't fail without GPIO access

**Test results before reboot:** 39 passed, 2 failed, 27 errors, 19 skipped.  
The 27 errors are all `RuntimeError: ProtoMQ failed to start` caused by a leaked node process holding port 1884 between test runs. The underlying issue is `atexit.register(self.stop)` in `ProtoMQService` — `stop()` is `async def` so the atexit hook creates a coroutine that's never awaited, leaving node running.

---

## Resuming After Reboot / Fresh Session

### 1. Ensure SSH agent has the key

```bash
ssh-add ~/.ssh/id_ed25519
ssh particle@192.168.1.169 "echo ok"
```

### 2. Start the HIL controller

```bash
ssh particle@192.168.1.169 "
  cd ~/dev-projects/python/usbip-hil-controller &&
  set -a && source run/controller.env && set +a &&
  nohup .venv/bin/hil-controller > /tmp/hil.log 2>&1 &
  sleep 4 && curl -s http://localhost:8080/healthz
"
```

Check topology loaded correctly:

```bash
ssh particle@192.168.1.169 "curl -s -H 'Authorization: Bearer dev-token-change-me' \
  http://localhost:8080/v1/topology | python3 -m json.tool"
```

### 3. Run a smoke job (inline script, no git source)

```bash
ssh particle@192.168.1.169 "
  curl -s -X POST -H 'Authorization: Bearer dev-token-change-me' \
    -H 'Content-Type: application/json' \
    -d '{\"target\":{\"device\":{\"id\":\"tachyon-runner-a\"},\"pool\":\"wippersnapper-python\"},
         \"script\":\"echo hello from tachyon hil\"}' \
    http://localhost:8080/v1/jobs
"
```

### 4. Run the Wippersnapper Python test suite

First check no stale ProtoMQ is running:

```bash
ssh particle@192.168.1.169 "ss -tlnp | grep -E '1884|5173' || echo ports-free"
```

If port 1884 is held by a leaked node process, kill it:

```bash
ssh particle@192.168.1.169 "fuser -k 1884/tcp 2>/dev/null; fuser -k 5173/tcp 2>/dev/null"
```

Then run:

```bash
ssh particle@192.168.1.169 "
  cd ~/dev-projects/python/Adafruit_Wippersnapper_Python &&
  timeout 180 .venv/bin/python -m pytest test/ -m 'not hardware' -q --tb=short
"
```

---

## Known Issues / Next Steps

### ProtoMQ port leak — fixes applied

The following changes were made directly to `Adafruit_Wippersnapper_Python/src/ProtoMQ/service.py` on the Tachyon (not yet upstreamed):

1. **`_kill_port(port)`** — added defensive method called at the top of `start()` to `fuser -k` any stale process on the MQTT and web ports before launching a new instance. Handles the case where the previous test session's last ProtoMQ wasn't cleaned up.

2. **`_stop_sync()`** — added synchronous kill method using SIGKILL (not SIGINT) to the process group, with `process.wait()` + port-free polling. Registered with `atexit` instead of the original `async def stop()`.

3. **`async def stop()`** — kept async (fixture does `await protomq.stop()`) but now delegates to `_stop_sync()`.

If you need to re-apply these fixes after a `git pull` on the wippersnapper repo, the pattern is:
- `start()`: call `self._kill_port(MQTT_PORT)` and `self._kill_port(WEB_PORT)` before Popen
- `atexit.register(self._stop_sync)` not `self.stop`
- `_stop_sync()`: `os.killpg(pid, SIGKILL)` + `process.wait(5)` + socket poll until free

### `BLINKA_OS_AGNOSTIC=1` required in `.env`

Without this, `board.SDA` on the Tachyon returns a raw tuple `(4, 8)` instead of a Blinka Pin object. `I2CBus.configure_bus()` then crashes with `AttributeError: 'tuple' object has no attribute 'direction'`. This exception is stored in the asyncio Task for `client.run()`, but the `checked_in` Future is never set — so `await ws_client.checked_in` hangs forever in every test.

The `.env` must have:
```
BLINKA_OS_AGNOSTIC=1
```

### ProtoMQ web build required before first test run

`tools/protomq/main.js` exits early if `dist/index.html` is missing. Run once after any fresh clone or repo update:

```bash
cd ~/dev-projects/python/Adafruit_Wippersnapper_Python/tools/protomq
npm run build-web
```

### 2 test failures

Not yet diagnosed — need to run with `--tb=long` after the above fixes are confirmed.

### HIL controller token

`dev-token-change-me` is the static bootstrap token in `run/controller.env`. Replace with a properly minted token for any non-local use:

```bash
ssh particle@192.168.1.169 "
  cd ~/dev-projects/python/usbip-hil-controller &&
  set -a && source run/controller.env && set +a &&
  .venv/bin/python scripts/mint-token.py
"
```

### Submitting a full Wippersnapper git-source job via the HIL controller

See `examples/wippersnapper-python/job-tachyon.json` for the Tachyon-specific template.  
Use `scripts/submit-wipper-test.sh` with:

```bash
GH_PAT=ghp_xxx \
HIL_API_TOKEN=dev-token-change-me \
HIL_API_BASE=http://192.168.1.169:8080 \
MQTT_HOST=127.0.0.1 \
WIPPER_REF=displays-v2 \
bash scripts/submit-wipper-test.sh
```
