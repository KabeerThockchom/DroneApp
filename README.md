# Pallton X80 Drone Controller — Military HUD Edition v3.0

A custom-built, fullscreen military-style heads-up display (HUD) controller for the **Pallton X80** drone. The entire screen is the live camera feed, with all flight instruments, controls, and telemetry drawn as transparent overlays — just like a fighter jet HUD.

**Protocol:** XR872 (reverse-engineered from the official `com.guanxu.X80_Drone` APK)

---

## Quick Start

```bash
# Install dependency
pip install Pillow

# Optional: gamepad support
pip install pygame

# Run
python x80_hud_app.py
```

1. Power on the drone
2. Connect your PC to the **X80 DRONE_xxxxxx** Wi-Fi network
3. Run `python x80_hud_app.py`
4. The app auto-connects, starts video, and shows the HUD

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
| `C` | Calibrate Gyro |
| `X` | Flip |

### Camera & Recording

| Key | Action |
|-----|--------|
| `V` | Toggle Video Stream |
| `P` | Take Photo (saved to `photos/`) |
| `R` | Start/Stop Recording (saved to `recordings/`) |
| `PgUp` | Tilt Camera Up |
| `PgDn` | Tilt Camera Down |

### Settings

| Key | Action |
|-----|--------|
| `1` / `2` / `3` | Speed: Low / Medium / High |
| `H` | Toggle Headless Mode |
| `F` | Toggle Lights |
| `Shift+Arrows` | Trim Adjustment |
| `Tab` | Toggle HUD On/Off |
| `?` | Show Help Overlay |
| `F11` | Toggle Fullscreen |
| `Q` | Quit |

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

### Gamepad (Xbox/PS Controller)

If `pygame` is installed and a gamepad is detected:

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
- **Mode indicators** — speed, headless, lights status
- **Recording indicator** — pulsing red REC with timer
- **Autopilot indicator** — pattern name and progress bar
- **Status bar** — bottom center, shows command feedback
- **Packet counter** — TX/RX packet counts

---

## File Structure

```
x80_hud_app/
├── x80_hud_app.py       # Main application (run this)
├── drone_protocol.py     # XR872 UDP protocol layer
├── hud_renderer.py       # Military HUD overlay renderer
├── autopilot.py          # 10 automated flight patterns
├── app_config.py         # Settings, keyboard map, stick layout
├── README.md             # This file
├── photos/               # Captured photos
├── recordings/           # Video recordings (MJPEG)
└── logs/                 # Flight telemetry logs (CSV)
```

---

## XR872 Protocol Summary

| Function | Port | Protocol |
|----------|------|----------|
| Flight Control | 7080 | UDP, 20-byte packets at 140ms |
| Video Stream | 7070 | UDP, MJPEG frames (fragmented) |
| Commands | 7080 | UDP, `0xCC 0x5A` prefix |

**Drone IP:** `192.168.28.1` (gateway of the drone's Wi-Fi network)

---

## Safety

- **Always calibrate** on a flat surface before first flight
- **Low battery auto-land** triggers at 10% (configurable)
- **Low battery warning** at 20%
- **Emergency stop** (SPACE) cuts all motors immediately
- **Remove propellers** when testing controls for the first time

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "NO SIGNAL" | Make sure you're connected to the drone's Wi-Fi |
| No video | Press `V` to toggle video, or restart the drone |
| Laggy controls | Close other apps using Wi-Fi; reduce window size |
| Gamepad not detected | Install `pygame` and reconnect the controller |
| Font looks wrong | Install `consola.ttf` or any monospace font |
