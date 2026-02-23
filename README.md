# Pallton X80 Drone Controller — Military HUD Edition v3.1

A custom-built, fullscreen military-style heads-up display (HUD) controller for the **Pallton X80** drone. The entire screen is the live camera feed, with all flight instruments, controls, and telemetry drawn as transparent overlays — just like a fighter jet HUD.

**Protocol:** XR872 (reverse-engineered from the official `com.guanxu.X80_Drone` APK)

---

## Quick Start

```bash
# Create venv (recommended — system Python tkinter may not work on newer macOS)
python3 -m venv .venv
source .venv/bin/activate

# Install dependency
pip install Pillow

# Run
python3 x80_hud_app.py
```

1. Power on the drone
2. Connect your PC to the **X80 DRONE_xxxxxx** Wi-Fi network
3. Run the app
4. The app auto-connects, starts video, and shows the HUD

> **Note:** Indoor mode is ON by default — throttle is capped at 30% for safe indoor testing.

---

## Controls — Dual Stick Layout

The controls mirror a standard drone remote controller:

```
┌──────────────────────┬──────────────────────┐
│     LEFT STICK       │     RIGHT STICK      │
│                      │                      │
│   W = Climb          │   Up    = Forward    │
│   S = Descend        │   Down  = Backward   │
│   A = Spin Left      │   Left  = Strafe L   │
│   D = Spin Right     │   Right = Strafe R   │
│                      │                      │
│   (Throttle + Yaw)   │   (Pitch + Roll)     │
└──────────────────────┴──────────────────────┘
```

### Commands

| Key | Action |
|-----|--------|
| `T` | Takeoff |
| `L` | Land |
| `SPACE` | Emergency Stop |
| `C` | Calibrate Gyro + Reset Home Position |
| `X` | Flip |

### Camera & Recording

| Key | MacBook Alt | Action |
|-----|-------------|--------|
| `V` | | Toggle Video Stream |
| `P` | | Take Photo (saved to `photos/`) |
| `R` | | Start/Stop Recording (saved to `recordings/`) |
| `PgUp` | `,` (comma) | Tilt Camera Up (hold) |
| `PgDn` | `.` (period) | Tilt Camera Down (hold) |
| `B` | | Switch Camera (Front/Bottom) |
| `G` | | Rotate Camera 180 |
| `Y` | | Toggle Timelapse (photos every 5s) |

### Settings & Modes

| Key | MacBook Alt | Action |
|-----|-------------|--------|
| `1` / `2` / `3` | | Speed: Low / Medium / High |
| `I` | | Toggle Indoor Mode (throttle cap) |
| `H` | | Toggle Headless Mode |
| `F` | | Toggle Lights |
| `Shift+Arrows` | | Trim Adjustment |
| `Tab` | | Toggle HUD On/Off |
| `?` | | Show Help Overlay |
| `F11` | `Ctrl+F` | Toggle Fullscreen |
| `Q` | | Quit |

### Position Tracking

| Key | MacBook Alt | Action |
|-----|-------------|--------|
| `Home` | `N` | Reset Home Position |

The mini-map radar tracks estimated drone position via dead-reckoning. A 50m geofence boundary turns amber at 45m and red at 50m with a pulsing screen border.

### Autopilot Patterns

| Key | Pattern |
|-----|---------|
| `Ctrl+1` | Circle |
| `Ctrl+2` | Square |
| `Ctrl+3` | Figure Eight |
| `Ctrl+4` | Zigzag |
| `Ctrl+5` | Hover & Rotate |
| `Ctrl+6` | Ascend & Descend |
| `Ctrl+7` | Orbit |
| `Ctrl+8` | Helix |
| `Ctrl+9` | Pendulum |
| `Ctrl+0` | Spiral Out |
| `Escape` | Stop Autopilot |

### Clickable HUD Buttons

The right side of the HUD has clickable buttons (mouse click):

**CALIBRATE** | **CAM UP** | **CAM DN** | **HOME RST** | **TIMELAPSE** | **INDOOR** | **TAKEOFF** | **LAND**

### Gamepad (Xbox/PS Controller)

Set `DRONE_ENABLE_GAMEPAD=1` environment variable, then install `pygame`:

- **Left Stick:** Throttle (Y) + Yaw (X)
- **Right Stick:** Pitch (Y) + Roll (X)
- **A Button:** Takeoff
- **B Button:** Land
- **X Button:** Flip
- **Y Button:** Emergency Stop

---

## HUD Elements

The military-style overlay includes:

- **Compass tape** — heading in degrees with N/E/S/W cardinals
- **Artificial horizon** — pitch ladder with horizon line
- **Altitude ladder** — right side, shows altitude in meters
- **Throttle/speed ladder** — left side, shows throttle % and speed mode
- **Battery gauge** — top-left, with color-coded warnings
- **Flight timer** — elapsed flight time
- **Signal strength** — top-right
- **Center reticle** — crosshair with circle
- **Dual stick indicators** — bottom corners, show real-time stick positions
- **Mode indicators** — speed, headless, lights, indoor mode status
- **Mini-map radar** — circular radar with drone position, home marker, geofence rings
- **Clickable HUD buttons** — military-style buttons for common actions
- **Indoor mode indicator** — amber warning with throttle cap percentage
- **Recording indicator** — pulsing red REC with timer
- **Timelapse indicator** — photo count when active
- **Autopilot indicator** — pattern name and progress bar
- **Geofence border** — pulsing red screen border when beyond 50m
- **Status bar** — bottom center, shows command feedback
- **Packet counter** — TX/RX packet counts

---

## Indoor Mode

Indoor mode (default: ON) is designed for safe testing inside your house:

- Throttle capped at **30%** — prevents the drone from shooting to the ceiling
- Speed forced to **LOW** when enabled
- Toggle with `I` key or the INDOOR HUD button
- Configurable throttle cap via `hover_throttle_cap` in `config.json`

---

## File Structure

```
DroneApp/
├── x80_hud_app.py              # Main application (run this)
├── drone_protocol.py            # XR872 UDP protocol layer
├── hud_renderer.py              # Military HUD overlay renderer
├── autopilot.py                 # 10 automated flight patterns
├── position_tracker.py          # Dead-reckoning position estimator
├── app_config.py                # Settings, keyboard map, stick layout
├── X80_DRONE_APK_Documentation.md  # Full APK reverse-engineering docs
├── CLAUDE.md                    # AI assistant project context
├── README.md                    # This file
├── photos/                      # Captured photos + timelapse
├── recordings/                  # Video recordings (MJPEG)
└── logs/                        # Flight telemetry logs (CSV)
```

---

## XR872 Protocol Summary

| Function | Port | Protocol |
|----------|------|----------|
| Flight Control | 7080 | UDP, 20-byte packets at 140ms |
| Telemetry | 7080 | UDP, 10-byte or 15-byte packets |
| Video Stream | 7070 | UDP, MJPEG frames (fragmented) |
| Commands | 7080 | UDP, `0xCC 0x5A` prefix (triple-packet) |

**Drone IP:** `192.168.28.1` (gateway of the drone's Wi-Fi network)

Command flags (takeoff, land, calibrate, flip, estop) auto-clear after 1 second, matching the official APK behavior.

---

## Safety

- **Indoor mode ON by default** — 30% throttle cap for safe indoor testing
- **Always calibrate** (`C` key) on a flat surface before first flight
- **Low battery auto-land** triggers at 10% (configurable)
- **Low battery warning** at 20%
- **Emergency stop** (`SPACE`) cuts all motors immediately
- **Geofence warning** at 45m, breach alert at 50m
- **Remove propellers** when testing controls for the first time

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "NO SIGNAL" | Make sure you're connected to the drone's Wi-Fi |
| No video | Press `V` to toggle video, or restart the drone |
| Takeoff doesn't work | Command flags auto-clear after 1s — press `T` once, don't hold |
| Drone flies too high indoors | Enable indoor mode (`I` key) — caps throttle at 30% |
| Laggy controls | Close other apps using Wi-Fi; reduce window size |
| SDL/macOS crash on launch | Use the venv: `.venv/bin/python3 x80_hud_app.py` |
| PgUp/PgDn missing (MacBook) | Use `,` and `.` keys instead |
| Home key missing (MacBook) | Use `N` key instead |
| F11 not working (MacBook) | Use `Ctrl+F` instead |
| Gamepad not detected | Set `DRONE_ENABLE_GAMEPAD=1` and install `pygame` |
| Font looks wrong | Install `consola.ttf` or any monospace font |
