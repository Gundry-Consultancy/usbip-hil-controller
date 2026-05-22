---
name: project-state
description: Current implementation state of the HIL controller
metadata:
  type: project
---

As of 2026-05-22, M0 through M4.5 + M1.5 + M2 (no OIDC) are on `main` (commit 0788483).

**What is built:**

M0–M4.5: pyproject.toml, FastAPI app, `/healthz` `/readyz`, SQLite init, `POST /v1/jobs`,
long-poll wait, cancel, asyncio scheduler+EventBus, SSHTransport, GitDeployAdapter,
RealHostRegistry, static + argon2id bearer auth, mint-token.py, topology.example.yaml,
systemd unit, hil-controller-ci.yml. Branch was `claude/m0-m1-hil-controller-impl`,
merged to main.

M1.5: hosts/devices/auxes/connections/audit_log DB tables; topology seeder (upsert from
topology.yaml at startup); `GET /v1/hosts`, `/v1/hosts/{id}`, `GET /v1/devices`
(filters: host/kind/model/capability/pool), `/v1/devices/{id}`, `GET /v1/aux`
(filters: kind/capability/pool), `/v1/aux/{id}`, `GET /v1/topology`, `POST /v1/topology/resolve`.

M2 (no OIDC): `auth/principal.py` Principal dataclass; `require_auth` returns Principal;
static token = superuser; DB tokens carry `allowed_pools`/`allowed_profiles`/`capabilities`;
pool/profile/trusted-firmware gating on job submit (403); audit_log writes;
mint-token.py `--allowed-pools`/`--allowed-profiles`/`--default-profile`/`--capabilities`;
token_id uses `token_hex` (no underscores).

**54 tests pass, 0 failures.**

**Not yet done:**
- M2 remainder: GitHub OIDC verifier, policy file
- M2.5: secret profiles YAML, per-job secrets materialisation, artifact sanitisation
- M3.5: MCU adapter chain (serial capture, esptool, MCP23017)
- M4: USB-IP, solenoid-hub reset, uf2-msc / picotool flashers
- M5: ProtoMQ helpers, camera, artifact storage, Prometheus metrics
- HTMX dashboard
- topology/importers/ (protomq_scripts.py, hardware_md.py)
