---
name: project-camera-integration
description: Camera monitoring PoC from tyeth/protomq PR #1 being integrated into the HIL controller; plan at docs/CAMERA_INTEGRATION.md
metadata:
  type: project
---

Camera monitoring integration from `tyeth/protomq` PR #1 (branch `video-qr-pytest-capture`, head SHA `5964cf1f6ea7fa7b3ce7246cb9f10a232bbe5d57`).

**Goal:** Port camera monitoring into the HIL controller so admins can configure camera frames and ROI per DUT, with QR auto-detection as the initial hint and manual amendment as the durable setting.

**Current state (as of 2026-05-25):** Cameras already have a CRUD UI in the HTMX web interface (`/ui/cameras`). Cameras are modelled as aux devices (kind=camera) with multi-stream support (RTSP, MJPEG, snapshot, USB). No ROI/QR detection yet. Plan document: `docs/CAMERA_INTEGRATION.md` — library-first approach, 4 phases.

**Key decisions made:**
- Library-first — port PR tools as standalone module first (`src/hil_controller/adapters/camera/`)
- Hardcoded 13-board calibration data moves to topology.yaml + `camera_rois` DB table
- Functions only from calibration_data.py (compute_scale, transform_roi) are ported
- solenoid_hub_control.py, hil_exceptions.py, runner_config.py, conftest.py are NOT ported

**What's ported to `src/hil_controller/adapters/camera/`:**
- recorder.py (VideoRecorder), qr_locator.py, frame_extractor.py, calibration.py (math only), report.py
- monitor.py (generic CameraMonitor), sources.py (V4L2Camera via SSH + IPCamera via HTTP), capture.py

**Why:** User confirmed camera work belongs in the controller, not in protomq.
**How to apply:** Follow docs/CAMERA_INTEGRATION.md phases; start with Phase 1 (library port, no controller wiring). Check existing camera UI in web/router.py and templates/cameras_*.html before adding new endpoints.
