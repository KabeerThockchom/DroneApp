# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pallton X80 drone controller with a fullscreen military-style HUD. Communicates with the drone over Wi-Fi using the XR872 UDP protocol (reverse-engineered from the official APK). The entire UI is a live camera feed with transparent instrument overlays rendered via Pillow.

## Running the App

```bash
pip install Pillow          # required
pip install pygame          # optional, for gamepad support
python3 x80_hud_app.py      # launch (connect to X80 DRONE Wi-Fi first)
```

Drone IP is `192.168.28.1`. Control port: 7080 (UDP). Video port: 7070 (UDP).

## Architecture

The app follows a layered architecture with four core modules:

- **`x80_hud_app.py`** — Main application and entry point. Contains `X80HUDApp` (tkinter fullscreen window), `FlightLogger` (CSV telemetry logging), `VideoRecorder` (MJPEG recording), and `GamepadHandler` (pygame joystick polling). Runs three concurrent loops: `_update_loop` (50Hz input/control), `_render_loop` (~30fps video+HUD), and the drone protocol threads.

- **`drone_protocol.py`** — XR872 UDP protocol implementation. `DroneProtocol` manages five daemon threads: control loop (140ms packets), heartbeat (1s), receive (telemetry parsing), video (MJPEG frame reassembly from fragmented UDP), and watchdog (connection health). Uses `FlightState` dataclass for control inputs and `Telemetry` dataclass for drone state. Control packets are 20-byte with header `0x66`, tail `0x99`, XOR checksum. Commands use `0xCC 0x5A` prefix.

- **`hud_renderer.py`** — `HUDRenderer` draws all overlay elements on an RGBA canvas using Pillow, then composites onto the video frame. Elements: compass tape, artificial horizon, altitude/speed ladders, battery gauge, stick indicators, mode indicators, recording/autopilot status. Accepts three dicts: `telemetry`, `flight_state`, `app_state`.

- **`autopilot.py`** — Time-based flight pattern execution (no GPS). `FlightPattern` defines sequences of `FlightStep` dataclasses (roll/pitch/throttle/yaw values + duration). `Autopilot` runs patterns in a background thread, writing stick values to a shared dict that the main update loop reads. 10 built-in patterns (circle, square, figure-eight, etc.) via static factory methods.

- **`app_config.py`** — `AppConfig` dataclass with JSON save/load/reset. Also exports `KEYBOARD_MAP` and `STICK_LAYOUT` dicts.

## Key Design Patterns

- **Shared mutable dict for autopilot control**: `Autopilot` writes to a `stick_state` dict; the main loop reads it. This avoids direct coupling between autopilot and the protocol layer.
- **Callback-based events**: `DroneProtocol` uses `on_video_frame`, `on_telemetry`, `on_status` callbacks set by the app.
- **Stick values use -100 to +100 range** internally, mapped to 0-255 for protocol packets and 0-255 for HUD stick indicators (centered at 128).
- **All UI runs on the tkinter main thread** via `root.after()` scheduling. Background threads (protocol, gamepad, autopilot) must not touch tkinter directly.

## Output Directories

- `photos/` — JPEG snapshots from video feed
- `recordings/` — MJPEG video files
- `logs/` — CSV flight telemetry logs
