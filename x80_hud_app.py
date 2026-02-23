"""
Pallton X80 Drone Controller — Military HUD Edition
=====================================================
Fullscreen military-style heads-up display with live video background.
All UI elements are drawn as transparent overlays on the video feed.

Protocol: XR872 (reverse-engineered from official APK)
Drone IP: 192.168.28.1 | Control: 7080 UDP | Video: 7070 UDP

Stick Layout (standard drone controller):
  LEFT STICK:  W/S = Throttle (climb/descend), A/D = Yaw (spin L/R)
  RIGHT STICK: Up/Down = Pitch (forward/back), Left/Right = Roll (strafe L/R)

Requirements: pip install Pillow
Optional:     pip install pygame  (for gamepad support)
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import threading
import time
import io
import os
import sys
import csv
from datetime import datetime
from collections import deque

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drone_protocol import DroneProtocol, Telemetry, FlightState
from hud_renderer import HUDRenderer
from autopilot import Autopilot, FlightPattern
from app_config import AppConfig, KEYBOARD_MAP, STICK_LAYOUT
from position_tracker import PositionTracker

# Try importing pygame for gamepad
# NOTE: pygame import is guarded — SDL may abort on incompatible macOS versions.
PYGAME_AVAILABLE = False
if os.environ.get("DRONE_ENABLE_GAMEPAD"):
    try:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        PYGAME_AVAILABLE = True
    except Exception:
        PYGAME_AVAILABLE = False

APP_NAME = "X80 DRONE HUD"
APP_VERSION = "3.0.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))


class FlightLogger:
    """Logs flight telemetry to CSV."""

    def __init__(self):
        self.logging = False
        self.file = None
        self.writer = None
        self.log_dir = os.path.join(APP_DIR, "logs")
        os.makedirs(self.log_dir, exist_ok=True)

    def start(self):
        if self.logging:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.log_dir, f"flight_{ts}.csv")
        self.file = open(path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow([
            "timestamp", "battery", "altitude", "heading",
            "roll", "pitch", "throttle", "yaw",
            "speed", "headless", "is_flying",
            "pos_x", "pos_y", "distance_home"
        ])
        self.logging = True

    def log(self, telemetry, state, sticks, position=None):
        if not self.logging or not self.writer:
            return
        try:
            row = [
                datetime.now().isoformat(),
                telemetry.battery_pct,
                telemetry.altitude,
                telemetry.heading,
                sticks["roll"], sticks["pitch"],
                sticks["throttle"], sticks["yaw"],
                state.speed, state.headless,
                telemetry.is_flying,
            ]
            if position:
                row.extend([
                    f"{position.x:.2f}",
                    f"{position.y:.2f}",
                    f"{position.distance:.2f}",
                ])
            else:
                row.extend([0, 0, 0])
            self.writer.writerow(row)
        except Exception:
            pass

    def stop(self):
        self.logging = False
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass
        self.file = None
        self.writer = None


class VideoRecorder:
    """Records MJPEG video frames."""

    def __init__(self):
        self.recording = False
        self.file = None
        self.start_time = 0
        self.duration = 0
        self.frame_count = 0
        self.rec_dir = os.path.join(APP_DIR, "recordings")
        os.makedirs(self.rec_dir, exist_ok=True)

    def start(self):
        if self.recording:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.rec_dir, f"rec_{ts}.mjpeg")
        self.file = open(path, "wb")
        self.recording = True
        self.start_time = time.time()
        self.frame_count = 0

    def write_frame(self, jpeg_bytes):
        if not self.recording or not self.file:
            return
        self.file.write(jpeg_bytes)
        self.frame_count += 1
        self.duration = time.time() - self.start_time

    def stop(self):
        if not self.recording:
            return
        if self.file:
            self.file.close()
        self.recording = False
        self.file = None
        self.duration = 0


class GamepadHandler:
    """Handles gamepad/joystick input via pygame."""

    def __init__(self):
        self.available = False
        self.joystick = None
        self._running = False
        self._thread = None

        if PYGAME_AVAILABLE:
            try:
                pygame.init()
                pygame.joystick.init()
                if pygame.joystick.get_count() > 0:
                    self.joystick = pygame.joystick.Joystick(0)
                    self.joystick.init()
                    self.available = True
            except Exception:
                pass

        # Axis values
        self.left_x = 0.0   # Yaw
        self.left_y = 0.0   # Throttle
        self.right_x = 0.0  # Roll
        self.right_y = 0.0  # Pitch

        # Button states (for edge detection)
        self.btn_a = False
        self.btn_b = False
        self.btn_x = False
        self.btn_y = False

        # Callbacks
        self.on_takeoff = None
        self.on_land = None
        self.on_flip = None
        self.on_estop = None

    def start(self):
        if not self.available or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                pygame.event.pump()
                js = self.joystick

                def axis(idx):
                    v = js.get_axis(idx) if idx < js.get_numaxes() else 0.0
                    return v if abs(v) > 0.1 else 0.0

                self.left_x = axis(0)
                self.left_y = axis(1)
                self.right_x = axis(2) if js.get_numaxes() > 2 else axis(3)
                self.right_y = axis(3) if js.get_numaxes() > 3 else axis(4)

                # Buttons (edge detection)
                if js.get_numbuttons() > 0:
                    a = js.get_button(0)
                    b = js.get_button(1) if js.get_numbuttons() > 1 else False
                    x_btn = js.get_button(2) if js.get_numbuttons() > 2 else False
                    y_btn = js.get_button(3) if js.get_numbuttons() > 3 else False

                    if a and not self.btn_a and self.on_takeoff:
                        self.on_takeoff()
                    if b and not self.btn_b and self.on_land:
                        self.on_land()
                    if x_btn and not self.btn_x and self.on_flip:
                        self.on_flip()
                    if y_btn and not self.btn_y and self.on_estop:
                        self.on_estop()

                    self.btn_a = a
                    self.btn_b = b
                    self.btn_x = x_btn
                    self.btn_y = y_btn
            except Exception:
                pass
            time.sleep(0.02)


class X80HUDApp:
    """
    Fullscreen military-style HUD drone controller.
    The entire window is the live video feed with all controls overlaid.
    """

    def __init__(self):
        # Core systems
        self.drone = DroneProtocol()
        self.hud = HUDRenderer()
        self.config = AppConfig()
        self.logger = FlightLogger()
        self.recorder = VideoRecorder()
        self.gamepad = GamepadHandler()

        # Position tracker (dead-reckoning)
        self.position_tracker = PositionTracker(
            max_speed=self.config.max_drone_speed,
            geofence_radius=self.config.geofence_radius,
            geofence_warning_radius=self.config.geofence_warning_radius,
        )

        # Autopilot — uses a dict for drone_state so it can write stick values
        self.stick_state = {"roll": 0, "pitch": 0, "throttle": 0, "yaw": 0}
        self.autopilot = Autopilot(self.stick_state)

        # UI state
        self.root = None
        self.video_label = None
        self.img_ref = None  # prevent GC
        self.is_fullscreen = False
        self.show_hud = True
        self.show_help = False

        # Video state
        self.last_jpeg = None
        self.video_active = False
        self.fps = 0
        self.frame_times = deque(maxlen=60)

        # Input state
        self.keys_down = set()
        self.shift_held = False

        # Status
        self.status_text = ""
        self.status_color = "#00d4ff"
        self.status_clear_time = 0
        self.photo_count = 0

        # Photo dir
        self.photo_dir = os.path.join(APP_DIR, "photos")
        os.makedirs(self.photo_dir, exist_ok=True)

    def run(self):
        """Launch the application."""
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.configure(bg="black")

        # Maximize window
        try:
            self.root.state("zoomed")  # Windows
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)  # Linux
            except tk.TclError:
                self.root.geometry("1280x720")

        # Single label fills entire window — this IS the screen
        self.video_label = tk.Label(self.root, bg="black", cursor="none")
        self.video_label.pack(fill=tk.BOTH, expand=True)

        # Bind events
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.video_label.bind("<Button-1>", self._on_mouse_click)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.focus_set()

        # Set drone callbacks
        self.drone.on_video_frame = self._on_video_frame
        self.drone.on_telemetry = self._on_telemetry
        self.drone.on_status = lambda msg: self._set_status(msg)

        # Setup gamepad callbacks
        if self.gamepad.available:
            self.gamepad.on_takeoff = lambda: self.drone.takeoff()
            self.gamepad.on_land = lambda: self.drone.land()
            self.gamepad.on_flip = lambda: self.drone.flip()
            self.gamepad.on_estop = lambda: self.drone.emergency_stop()
            self.gamepad.start()

        # Auto-connect
        self.root.after(500, self._auto_connect)

        # Start loops
        self._update_loop()
        self._render_loop()

        self.root.mainloop()

    # ── Auto Connect ──────────────────────────────────────────────────

    def _auto_connect(self):
        """Try to connect to the drone automatically."""
        self._set_status("CONNECTING...", "#ffaa00", 0)

        def do_connect():
            try:
                self.drone.connect()
                self.root.after(100, lambda: self._set_status("CONNECTED", "#00ff41"))
                self.root.after(200, self._start_video)
                self.logger.start()
            except Exception as e:
                self.root.after(100, lambda: self._set_status(
                    f"CONNECTION FAILED: {e}", "#ff0033", 10))

        threading.Thread(target=do_connect, daemon=True).start()

    def _start_video(self):
        self.drone.start_video()
        self.video_active = True
        self._set_status("VIDEO ACTIVE", "#00ff41")

    # ── Keyboard Input ────────────────────────────────────────────────

    def _on_key_press(self, event):
        sym = event.keysym
        self.shift_held = bool(event.state & 0x1)
        ctrl_held = bool(event.state & 0x4)

        # Movement keys (held) — LEFT STICK: W/S/A/D
        if sym.lower() in ("w", "a", "s", "d"):
            self.keys_down.add(sym.lower())
            return

        # Movement keys (held) — RIGHT STICK: Arrows
        if sym in ("Up", "Down", "Left", "Right"):
            if self.shift_held:
                # Trim adjustment
                if sym == "Left":
                    self.drone.flight_state.trim_roll -= 1
                elif sym == "Right":
                    self.drone.flight_state.trim_roll += 1
                elif sym == "Up":
                    self.drone.flight_state.trim_pitch -= 1
                elif sym == "Down":
                    self.drone.flight_state.trim_pitch += 1
                self._set_status(
                    f"TRIM R:{self.drone.flight_state.trim_roll:+d} "
                    f"P:{self.drone.flight_state.trim_pitch:+d}", "#00d4ff", 2)
            else:
                self.keys_down.add(sym)
            return

        # Camera tilt (held)
        if sym == "Prior":  # PageUp
            self.drone.camera_up()
            return
        if sym == "Next":  # PageDown
            self.drone.camera_down()
            return

        # Autopilot patterns (Ctrl+number)
        if ctrl_held and sym in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"):
            self._start_autopilot_by_index(int(sym) if sym != "0" else 10)
            return

        # One-shot commands
        if sym.lower() == "t":
            self.drone.takeoff()
            self._set_status("TAKEOFF", "#00ff41")
        elif sym.lower() == "l":
            self.drone.land()
            self._set_status("LANDING", "#ffaa00")
        elif sym == "space":
            self.drone.emergency_stop()
            self._set_status("EMERGENCY STOP", "#ff0033", 5)
        elif sym.lower() == "c":
            self.drone.calibrate()
            self.position_tracker.reset_home()
            self._set_status("CALIBRATING GYRO + HOME RESET", "#00d4ff")
        elif sym.lower() == "x":
            self.drone.flip()
            self._set_status("FLIP", "#00d4ff")
        elif sym.lower() == "f":
            self.drone.toggle_light()
            self._set_status("LIGHTS TOGGLED", "#00d4ff")
        elif sym.lower() == "h":
            self.drone.toggle_headless()
            mode = "ON" if self.drone.flight_state.headless else "OFF"
            self._set_status(f"HEADLESS {mode}", "#ffaa00")
        elif sym.lower() == "v":
            self._toggle_video()
        elif sym.lower() == "p":
            self._take_photo()
        elif sym.lower() == "r":
            self._toggle_recording()
        elif sym == "1":
            self.drone.set_speed(0.2)
            self._set_status("SPEED: LOW", "#00d4ff")
        elif sym == "2":
            self.drone.set_speed(0.5)
            self._set_status("SPEED: MEDIUM", "#00d4ff")
        elif sym == "3":
            self.drone.set_speed(0.9)
            self._set_status("SPEED: HIGH", "#ffaa00")
        elif sym == "Tab":
            self.show_hud = not self.show_hud
        elif sym == "question":
            self.show_help = not self.show_help
        elif sym == "F11":
            self._toggle_fullscreen()
        elif sym == "Escape":
            if self.autopilot.active:
                self.autopilot.stop()
                self._set_status("AUTOPILOT STOPPED", "#ffaa00")
        elif sym == "Home":
            self.position_tracker.reset_home()
            self._set_status("HOME POSITION RESET", "#00ff41")
        elif sym.lower() == "q":
            self._quit()

    def _on_key_release(self, event):
        sym = event.keysym
        self.shift_held = bool(event.state & 0x1)

        if sym.lower() in ("w", "a", "s", "d"):
            self.keys_down.discard(sym.lower())
        elif sym in ("Up", "Down", "Left", "Right"):
            self.keys_down.discard(sym)
        elif sym in ("Prior", "Next"):
            self.drone.camera_stop()

    # ── Mouse Click Handling ─────────────────────────────────────────

    def _on_mouse_click(self, event):
        """Hit-test against HUD button bounding boxes."""
        x, y = event.x, event.y
        for action, (x0, y0, x1, y1) in self.hud.button_rects.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._handle_hud_button(action)
                return

    def _handle_hud_button(self, action):
        """Dispatch HUD button actions."""
        if action == "calibrate":
            self.drone.calibrate()
            self.position_tracker.reset_home()
            self._set_status("CALIBRATING + HOME RESET", "#00d4ff")
        elif action == "cam_up":
            self.drone.camera_up()
            self._set_status("CAMERA UP", "#00d4ff")
            self.root.after(300, self.drone.camera_stop)
        elif action == "cam_dn":
            self.drone.camera_down()
            self._set_status("CAMERA DOWN", "#00d4ff")
            self.root.after(300, self.drone.camera_stop)
        elif action == "home_rst":
            self.position_tracker.reset_home()
            self._set_status("HOME POSITION RESET", "#00ff41")

    # ── Control Update Loop ───────────────────────────────────────────

    def _update_loop(self):
        """50Hz loop: process input, update drone controls, log data."""
        if not self.drone.is_connected:
            self.root.after(50, self._update_loop)
            return

        # Clear status if expired
        if self.status_clear_time and time.time() > self.status_clear_time:
            self.status_text = ""
            self.status_clear_time = 0

        # If autopilot is active, it controls the sticks via self.stick_state dict
        if self.autopilot.active:
            self.drone.flight_state.roll = int(self.stick_state["roll"])
            self.drone.flight_state.pitch = int(self.stick_state["pitch"])
            self.drone.flight_state.throttle = int(self.stick_state["throttle"])
            self.drone.flight_state.yaw = int(self.stick_state["yaw"])
        else:
            # Check gamepad first
            gp_active = False
            if self.gamepad.available:
                if (abs(self.gamepad.left_x) > 0.1 or abs(self.gamepad.left_y) > 0.1 or
                        abs(self.gamepad.right_x) > 0.1 or abs(self.gamepad.right_y) > 0.1):
                    gp_active = True
                    # Left stick: yaw (X) + throttle (Y, inverted)
                    self.stick_state["yaw"] = self.gamepad.left_x * 100
                    self.stick_state["throttle"] = -self.gamepad.left_y * 100
                    # Right stick: roll (X) + pitch (Y)
                    self.stick_state["roll"] = self.gamepad.right_x * 100
                    self.stick_state["pitch"] = self.gamepad.right_y * 100

            if not gp_active:
                self._process_keyboard()

            # Apply stick state to drone flight state
            self.drone.flight_state.roll = int(self.stick_state["roll"])
            self.drone.flight_state.pitch = int(self.stick_state["pitch"])
            self.drone.flight_state.throttle = int(self.stick_state["throttle"])
            self.drone.flight_state.yaw = int(self.stick_state["yaw"])

        # Update position tracker
        self.position_tracker.update(
            pitch=self.stick_state["pitch"],
            roll=self.stick_state["roll"],
            heading=self.drone.telemetry.heading,
            speed_mode=self.drone.speed_name,
            is_flying=self.drone.telemetry.is_flying,
        )

        # Geofence warnings
        if self.position_tracker.beyond_geofence:
            if not self.status_text or "GEOFENCE" not in self.status_text:
                self._set_status("GEOFENCE BREACH — RETURN TO HOME", "#ff0033", 2)
        elif self.position_tracker.at_geofence:
            if not self.status_text or "GEOFENCE" not in self.status_text:
                self._set_status("GEOFENCE WARNING — APPROACHING LIMIT", "#ffaa00", 2)

        # Log
        if self.logger.logging:
            self.logger.log(self.drone.telemetry, self.drone.flight_state,
                            self.stick_state, self.position_tracker.position)

        # Safety: low battery auto-land
        bat = self.drone.telemetry.battery_pct
        if 0 < bat <= self.config.auto_land_battery and self.drone.telemetry.is_flying:
            self.drone.land()
            self._set_status("AUTO-LAND: BATTERY CRITICAL", "#ff0033", 10)
        elif 0 < bat <= self.config.low_battery_warning:
            if not self.status_text:
                self._set_status("LOW BATTERY WARNING", "#ff0033", 2)

        self.root.after(20, self._update_loop)

    def _process_keyboard(self):
        """Map held keys to stick values. LEFT STICK: W/S/A/D, RIGHT STICK: Arrows."""
        # LEFT STICK — Throttle (W/S): progressive ramp
        if "w" in self.keys_down:
            self.stick_state["throttle"] = min(100, self.stick_state["throttle"] + 4)
        elif "s" in self.keys_down:
            self.stick_state["throttle"] = max(-100, self.stick_state["throttle"] - 4)
        else:
            t = self.stick_state["throttle"]
            if abs(t) < 3:
                self.stick_state["throttle"] = 0
            else:
                self.stick_state["throttle"] = t * 0.85

        # LEFT STICK — Yaw (A/D): instant
        if "a" in self.keys_down:
            self.stick_state["yaw"] = -80
        elif "d" in self.keys_down:
            self.stick_state["yaw"] = 80
        else:
            self.stick_state["yaw"] = 0

        # RIGHT STICK — Pitch (Up/Down): instant
        if "Up" in self.keys_down:
            self.stick_state["pitch"] = -80  # Forward
        elif "Down" in self.keys_down:
            self.stick_state["pitch"] = 80   # Backward
        else:
            self.stick_state["pitch"] = 0

        # RIGHT STICK — Roll (Left/Right): instant
        if "Left" in self.keys_down:
            self.stick_state["roll"] = -80
        elif "Right" in self.keys_down:
            self.stick_state["roll"] = 80
        else:
            self.stick_state["roll"] = 0

    # ── Render Loop ───────────────────────────────────────────────────

    def _render_loop(self):
        """~30fps render loop: video frame + HUD overlay."""
        now = time.time()
        self.frame_times.append(now)
        if len(self.frame_times) > 1:
            elapsed = self.frame_times[-1] - self.frame_times[0]
            if elapsed > 0:
                self.fps = len(self.frame_times) / elapsed

        # Get video frame or create black background
        frame = None
        if self.last_jpeg:
            try:
                img_data = io.BytesIO(self.last_jpeg)
                frame = Image.open(img_data)
                frame.load()  # Force decode now so errors are caught here
            except Exception:
                frame = None

        if frame is None:
            w = max(self.root.winfo_width(), 640)
            h = max(self.root.winfo_height(), 480)
            frame = Image.new("RGB", (w, h), "black")
            # Draw centered status text on black
            draw = ImageDraw.Draw(frame)
            try:
                font = ImageFont.truetype("consola.ttf", 28)
            except (IOError, OSError):
                try:
                    font = ImageFont.truetype("Courier", 28)
                except (IOError, OSError):
                    font = ImageFont.load_default()

            if self.drone.is_connected:
                msg = "WAITING FOR VIDEO SIGNAL..."
                color = "#ffaa00"
            else:
                msg = "NO SIGNAL"
                color = "#ff0033"

            bbox = draw.textbbox((0, 0), msg, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((w - tw) // 2, (h - th) // 2), msg, fill=color, font=font)
        else:
            # Resize to fill window
            w = max(self.root.winfo_width(), 640)
            h = max(self.root.winfo_height(), 480)
            try:
                frame = frame.resize((w, h), Image.LANCZOS)
            except OSError:
                # Truncated frame — skip it
                frame = Image.new("RGB", (w, h), (10, 10, 15))
                draw = ImageDraw.Draw(frame)
                draw.text((w // 2 - 40, h // 2), "BUFFERING...",
                          fill="#00ff41")

        # Record frame
        if self.recorder.recording and self.last_jpeg:
            self.recorder.write_frame(self.last_jpeg)

        # Draw HUD overlay
        if self.show_hud:
            t = self.drone.telemetry

            # Telemetry dict for HUD renderer
            telemetry_dict = {
                "battery": t.battery_pct,
                "voltage": t.battery_voltage,
                "altitude": t.altitude,
                "heading": t.heading,
                "signal": t.signal_strength,
                "is_flying": t.is_flying,
                "flight_time": t.flight_time if t.flight_time else self.drone.uptime,
                "roll": self.stick_state["roll"],
                "pitch": self.stick_state["pitch"],
            }

            # Flight state dict for HUD renderer (0-255 range for stick indicators)
            fs = self.drone.flight_state
            flight_state_dict = {
                "roll": 128 + int(self.stick_state["roll"] * 1.27),
                "pitch": 128 + int(self.stick_state["pitch"] * 1.27),
                "throttle": 128 + int(self.stick_state["throttle"] * 1.27),
                "yaw": 128 + int(self.stick_state["yaw"] * 1.27),
                "speed_mode": self.drone.speed_name,
                "headless": fs.headless,
                "light": fs.light,
                "flight_time": t.flight_time if t.flight_time else self.drone.uptime,
            }

            # Position data
            pos = self.position_tracker.position

            # App state dict
            app_state = {
                "fps": int(self.fps),
                "recording": self.recorder.recording,
                "recording_duration": self.recorder.duration,
                "photo_count": self.photo_count,
                "autopilot_active": self.autopilot.active,
                "autopilot_label": self.autopilot.current_step_label,
                "autopilot_progress": self.autopilot.progress,
                "show_help": self.show_help,
                "connected": self.drone.is_connected,
                "status_text": self.status_text,
                "status_color": self.status_color,
                "tx": getattr(self.drone, "packets_sent", 0),
                "rx": getattr(self.drone, "packets_received", 0),
                # Position / geofence data
                "pos_x": pos.x,
                "pos_y": pos.y,
                "pos_distance": pos.distance,
                "pos_bearing": pos.bearing,
                "heading": t.heading,
                "at_geofence": self.position_tracker.at_geofence,
                "beyond_geofence": self.position_tracker.beyond_geofence,
                "geofence_radius": self.config.geofence_radius,
                "show_minimap": self.config.show_minimap,
                "show_hud_buttons": self.config.show_hud_buttons,
            }

            frame = self.hud.render(frame, telemetry_dict, flight_state_dict, app_state)

        # Display on the single fullscreen label
        try:
            self.img_ref = ImageTk.PhotoImage(frame)
            self.video_label.config(image=self.img_ref)
        except Exception:
            pass

        self.root.after(33, self._render_loop)

    # ── Video Callback ────────────────────────────────────────────────

    def _on_video_frame(self, jpeg_bytes):
        """Called from drone video thread."""
        self.last_jpeg = jpeg_bytes

    def _on_telemetry(self, telemetry):
        """Called from drone receive thread."""
        pass  # Telemetry is read directly from self.drone.telemetry

    # ── Actions ───────────────────────────────────────────────────────

    def _toggle_video(self):
        if self.video_active:
            self.drone.stop_video()
            self.video_active = False
            self.last_jpeg = None
            self._set_status("VIDEO STOPPED", "#ffaa00")
        else:
            self.drone.start_video()
            self.video_active = True
            self._set_status("VIDEO STARTED", "#00ff41")

    def _take_photo(self):
        if not self.last_jpeg:
            self._set_status("NO VIDEO TO CAPTURE", "#ffaa00")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.photo_count += 1
        path = os.path.join(self.photo_dir, f"photo_{ts}_{self.photo_count:03d}.jpg")
        try:
            with open(path, "wb") as f:
                f.write(self.last_jpeg)
            self._set_status(f"PHOTO SAVED [{self.photo_count}]", "#00ff41")
        except Exception as e:
            self._set_status(f"PHOTO FAILED: {e}", "#ff0033")

    def _toggle_recording(self):
        if self.recorder.recording:
            self.recorder.stop()
            self._set_status("RECORDING STOPPED", "#00d4ff")
        else:
            self.recorder.start()
            self._set_status("RECORDING", "#ff0033")

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)

    def _start_autopilot_by_index(self, idx):
        """Start autopilot pattern by Ctrl+number index."""
        patterns = list(Autopilot.get_patterns().items())
        if idx < 1 or idx > len(patterns):
            self._set_status(f"NO PATTERN {idx}", "#ffaa00")
            return
        name, factory = patterns[idx - 1]
        if not self.drone.is_connected:
            self._set_status("CONNECT FIRST", "#ff0033")
            return
        pattern = factory()
        self.autopilot.start(pattern)
        self._set_status(f"AUTOPILOT: {name.upper()}", "#00d4ff")

    # ── Status ────────────────────────────────────────────────────────

    def _set_status(self, text, color="#00d4ff", duration=3):
        self.status_text = text
        self.status_color = color
        if duration > 0:
            self.status_clear_time = time.time() + duration
        else:
            self.status_clear_time = 0

    # ── Cleanup ───────────────────────────────────────────────────────

    def _quit(self):
        print("Shutting down...")
        if self.autopilot.active:
            self.autopilot.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.logger.stop()
        self.gamepad.stop()
        if self.drone.is_connected:
            try:
                self.drone.stop_video()
            except Exception:
                pass
            self.drone.disconnect()
        self.root.destroy()


def main():
    print("=" * 56)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print(f"  Pallton X80 | XR872 Protocol")
    print("=" * 56)
    print()
    print(f"  Drone IP:    192.168.28.1")
    print(f"  Control:     7080 (UDP)")
    print(f"  Video:       7070 (UDP)")
    print()
    print(f"  ┌─────────────────────────────────────────┐")
    print(f"  │  LEFT STICK       RIGHT STICK           │")
    print(f"  │  W = Climb        Up    = Forward       │")
    print(f"  │  S = Descend      Down  = Backward      │")
    print(f"  │  A = Spin Left    Left  = Strafe Left   │")
    print(f"  │  D = Spin Right   Right = Strafe Right  │")
    print(f"  ├─────────────────────────────────────────┤")
    print(f"  │  T=Takeoff  L=Land  SPACE=E-Stop        │")
    print(f"  │  C=Calibrate  ?=Help  F11=Fullscreen    │")
    print(f"  │  Ctrl+1..9 = Autopilot patterns         │")
    print(f"  └─────────────────────────────────────────┘")
    print()
    if PYGAME_AVAILABLE:
        print(f"  Gamepad:     Available")
    else:
        print(f"  Gamepad:     Not found (install pygame)")
    print()

    app = X80HUDApp()
    app.run()


if __name__ == "__main__":
    main()
