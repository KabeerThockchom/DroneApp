"""
Military-style HUD renderer for the Pallton X80 Drone Controller.
Draws all overlay elements on top of the live video feed.
"""
import math
import time
from PIL import Image, ImageDraw, ImageFont


class HUDRenderer:
    """
    Renders a military-style Head-Up Display (HUD) overlay on a video frame.
    All elements are drawn with transparency on an RGBA canvas, then composited.
    """

    def __init__(self):
        self.primary_color = (0, 255, 65, 255)    # Green
        self.warning_color = (255, 170, 0, 255)    # Amber
        self.danger_color = (255, 0, 51, 255)      # Red
        self.info_color = (0, 212, 255, 255)        # Cyan
        self.bg_color = (0, 0, 0, 128)              # Semi-transparent black

        self.font_small = self._get_font(14)
        self.font_medium = self._get_font(18)
        self.font_large = self._get_font(24)
        self.font_xl = self._get_font(32)

        # Bounding boxes for clickable HUD buttons: {name: (x0, y0, x1, y1)}
        self.button_rects = {}

    def _get_font(self, size):
        """Load a monospace font, with fallbacks."""
        for name in ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    def _text_size(self, font, text):
        """Get text width and height, compatible with all Pillow versions."""
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            return font.getsize(text)

    def render(self, img: Image.Image, telemetry: dict, flight_state: dict, app_state: dict) -> Image.Image:
        """
        Draw the full HUD overlay onto the provided image.

        Args:
            img: Base video frame.
            telemetry: Dict with battery, voltage, altitude, heading, signal, is_flying, flight_time, roll, pitch.
            flight_state: Dict with roll, pitch, throttle, yaw (0-255), speed_mode, headless, light, flight_time.
            app_state: Dict with fps, recording, recording_duration, photo_count, autopilot_active,
                       autopilot_label, autopilot_progress, show_help, connected, status_text, status_color, tx, rx.
        Returns:
            New RGBA Image with HUD composited.
        """
        hud_canvas = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(hud_canvas, "RGBA")
        w, h = img.size

        # Core HUD elements
        self._draw_center_reticle(draw, w, h)
        self._draw_artificial_horizon(draw, w, h,
                                       telemetry.get("roll", 0),
                                       telemetry.get("pitch", 0))
        self._draw_compass(draw, w, h, telemetry.get("heading", 0))
        self._draw_altitude_ladder(draw, w, h, telemetry.get("altitude", 0))
        self._draw_speed_indicator(draw, w, h,
                                    flight_state.get("throttle", 128),
                                    flight_state.get("speed_mode", "MED"))
        self._draw_battery_gauge(draw, w, h,
                                  telemetry.get("battery", 100),
                                  telemetry.get("voltage", 0.0))
        self._draw_flight_time(draw, w, h, flight_state.get("flight_time", 0))
        self._draw_signal_strength(draw, w, h, telemetry.get("signal", 100))

        # FPS counter
        fps = app_state.get("fps", 0)
        draw.text((w - 120, h - 40), f"FPS: {fps}", fill=self.info_color, font=self.font_small)

        # Status bar
        status_text = app_state.get("status_text", "")
        status_color = app_state.get("status_color", "#00d4ff")
        if status_text:
            self._draw_status_bar(draw, w, h, status_text, status_color)

        # Stick indicators
        self._draw_stick_indicators(draw, w, h, flight_state)

        # Mode indicators
        self._draw_mode_indicators(draw, w, h, flight_state)

        # Indoor mode indicator
        if app_state.get("indoor_mode", False):
            cap = app_state.get("hover_throttle_cap", 30)
            draw.text((20, 80), f"INDOOR [{cap:.0f}%]", fill=self.warning_color, font=self.font_medium)

        # Packet counter
        self._draw_packet_counter(draw, w, h,
                                   app_state.get("tx", 0),
                                   app_state.get("rx", 0))

        # Recording indicator
        if app_state.get("recording", False):
            self._draw_recording_indicator(draw, w, h,
                                            app_state.get("recording_duration", 0))

        # Timelapse indicator
        if app_state.get("timelapse_active", False):
            tl_count = app_state.get("timelapse_count", 0)
            draw.text((w // 2 - 60, h // 10 + 25), f"TL: {tl_count} PHOTOS",
                      fill=self.primary_color, font=self.font_medium)

        # Autopilot indicator
        if app_state.get("autopilot_active", False):
            self._draw_autopilot_indicator(draw, w, h,
                                            app_state.get("autopilot_label", "--"),
                                            app_state.get("autopilot_progress", 0))

        # HUD buttons (clickable)
        if app_state.get("show_hud_buttons", True):
            self._draw_hud_buttons(draw, w, h)

        # Mini-map
        if app_state.get("show_minimap", True):
            self._draw_minimap(draw, w, h, app_state)

        # Geofence breach border
        if app_state.get("beyond_geofence", False):
            self._draw_geofence_border(draw, w, h)

        # Help overlay
        if app_state.get("show_help", False):
            self._draw_help_overlay(draw, w, h)

        # Connection status indicator
        if not app_state.get("connected", False):
            self._draw_disconnected(draw, w, h)

        return Image.alpha_composite(img.convert("RGBA"), hud_canvas)

    # ── Center Reticle ────────────────────────────────────────────────

    def _draw_center_reticle(self, draw, w, h):
        cx, cy = w // 2, h // 2
        size = min(w, h) // 40
        # Crosshair lines
        draw.line([(cx - size * 2, cy), (cx - size // 2, cy)], fill=self.primary_color, width=1)
        draw.line([(cx + size // 2, cy), (cx + size * 2, cy)], fill=self.primary_color, width=1)
        draw.line([(cx, cy - size * 2), (cx, cy - size // 2)], fill=self.primary_color, width=1)
        draw.line([(cx, cy + size // 2), (cx, cy + size * 2)], fill=self.primary_color, width=1)
        # Center circle
        r = size // 3
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=self.primary_color, width=1)

    # ── Artificial Horizon ────────────────────────────────────────────

    def _draw_artificial_horizon(self, draw, w, h, roll, pitch):
        cx, cy = w // 2, h // 2
        pitch_spacing = h / 50

        # Pitch ladder
        for p in range(-30, 31, 10):
            if p == 0:
                continue
            y_pos = cy - (pitch - p) * pitch_spacing
            line_len = w // 60 if abs(p) % 20 != 0 else w // 40
            draw.line([(cx - line_len, y_pos), (cx + line_len, y_pos)],
                      fill=self.primary_color, width=1)
            draw.text((cx + line_len + 5, y_pos - 8), str(p),
                      fill=self.primary_color, font=self.font_small)

        # Horizon line
        horizon_width = w // 4
        roll_rad = math.radians(roll)
        draw.line(
            (cx - horizon_width * math.cos(roll_rad),
             cy - horizon_width * math.sin(roll_rad) - (pitch * pitch_spacing),
             cx + horizon_width * math.cos(roll_rad),
             cy + horizon_width * math.sin(roll_rad) - (pitch * pitch_spacing)),
            fill=self.primary_color, width=2
        )

    # ── Compass ───────────────────────────────────────────────────────

    def _draw_compass(self, draw, w, h, heading):
        compass_w = w // 3
        cx = w // 2
        y_pos = h // 20
        draw.rectangle([(cx - compass_w / 2 - 10, y_pos - 15),
                         (cx + compass_w / 2 + 10, y_pos + 25)], fill=self.bg_color)

        for i in range(-40, 41, 10):
            angle = (heading + i) % 360
            x = cx + i * (compass_w / 80)
            if angle % 30 == 0:
                cardinal = {0: "N", 90: "E", 180: "S", 270: "W"}.get(int(angle), str(int(angle)))
                draw.line([(x, y_pos), (x, y_pos + 10)], fill=self.primary_color, width=2)
                draw.text((x - 8, y_pos + 12), cardinal, fill=self.primary_color, font=self.font_small)
            else:
                draw.line([(x, y_pos), (x, y_pos + 5)], fill=self.primary_color, width=1)

        # Current heading box
        draw.rectangle([(cx - 20, y_pos - 12), (cx + 20, y_pos + 10)], fill=self.primary_color)
        draw.text((cx - 15, y_pos - 10), f"{int(heading):03d}",
                  fill=(0, 0, 0, 255), font=self.font_medium)

    # ── Altitude Ladder ───────────────────────────────────────────────

    def _draw_altitude_ladder(self, draw, w, h, altitude):
        x_pos = w - w // 12
        ladder_h = h // 2
        cy = h // 2
        draw.rectangle([(x_pos - 20, cy - ladder_h / 2),
                         (x_pos + 50, cy + ladder_h / 2)], fill=self.bg_color)

        alt_step = 10
        for i in range(-5, 6):
            alt_val = int(altitude / alt_step) * alt_step + i * alt_step
            y = cy - (alt_val - altitude) * (ladder_h / (alt_step * 10))
            if cy - ladder_h / 2 < y < cy + ladder_h / 2:
                draw.line([(x_pos, y), (x_pos + 10, y)], fill=self.primary_color, width=1)
                draw.text((x_pos + 15, y - 8), str(alt_val),
                          fill=self.primary_color, font=self.font_small)

        # Current altitude box
        draw.rectangle([(x_pos - 10, cy - 12), (x_pos + 40, cy + 12)], fill=self.primary_color)
        alt_text = f"{altitude:.0f}m" if isinstance(altitude, float) else f"{altitude}m"
        draw.text((x_pos - 5, cy - 10), alt_text,
                  fill=(0, 0, 0, 255), font=self.font_medium)

    # ── Speed / Throttle Indicator ────────────────────────────────────

    def _draw_speed_indicator(self, draw, w, h, throttle, speed_mode):
        x_pos = w // 12
        ladder_h = h // 2
        cy = h // 2
        draw.rectangle([(x_pos - 50, cy - ladder_h / 2),
                         (x_pos + 20, cy + ladder_h / 2)], fill=self.bg_color)

        for i in range(0, 101, 10):
            y = (cy + ladder_h / 2) - (i / 100) * ladder_h
            draw.line([(x_pos - 10, y), (x_pos, y)], fill=self.primary_color, width=1)
            draw.text((x_pos - 40, y - 8), str(i), fill=self.primary_color, font=self.font_small)

        # Throttle position marker
        throttle_pct = max(0, min(100, (throttle / 255) * 100))
        throttle_y = (cy + ladder_h / 2) - throttle_pct * (ladder_h / 100)
        draw.line([(x_pos - 15, throttle_y), (x_pos, throttle_y)],
                  fill=self.info_color, width=2)

        # Speed mode box
        draw.rectangle([(x_pos - 45, cy - 12), (x_pos + 15, cy + 12)], fill=self.primary_color)
        draw.text((x_pos - 40, cy - 10), f"{speed_mode}",
                  fill=(0, 0, 0, 255), font=self.font_medium)

    # ── Battery Gauge ─────────────────────────────────────────────────

    def _draw_battery_gauge(self, draw, w, h, battery, voltage):
        x, y = 20, 20
        bar_w, bar_h = 150, 20
        color = (self.danger_color if battery < 15
                 else self.warning_color if battery < 30
                 else self.primary_color)
        draw.rectangle([(x, y), (x + bar_w, y + bar_h)], outline=self.primary_color, width=1)
        fill_w = max(0, bar_w * (battery / 100))
        draw.rectangle([(x, y), (x + fill_w, y + bar_h)], fill=color)
        text = f"BATT {battery}% [{voltage:.1f}V]"
        draw.text((x + 5, y + 2), text, fill=(255, 255, 255, 255), font=self.font_small)

    # ── Flight Time ───────────────────────────────────────────────────

    def _draw_flight_time(self, draw, w, h, flight_time):
        x, y = 20, 50
        minutes, seconds = divmod(int(flight_time), 60)
        text = f"TIME {minutes:02d}:{seconds:02d}"
        draw.text((x, y), text, fill=self.primary_color, font=self.font_medium)

    # ── Signal Strength ───────────────────────────────────────────────

    def _draw_signal_strength(self, draw, w, h, signal):
        x, y = w - 120, 20
        draw.text((x, y), f"SIG {signal}%", fill=self.primary_color, font=self.font_medium)

    # ── Status Bar ────────────────────────────────────────────────────

    def _draw_status_bar(self, draw, w, h, message, color="#00d4ff"):
        tw, th = self._text_size(self.font_medium, message)
        x = (w - tw) / 2
        y = h - 50
        draw.rectangle([(x - 10, y - 5), (x + tw + 10, y + th + 5)], fill=self.bg_color)
        # Parse hex color to RGBA tuple
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            fill_color = (r, g, b, 255)
        except (ValueError, IndexError):
            fill_color = self.info_color
        draw.text((x, y), message, fill=fill_color, font=self.font_medium)

    # ── Stick Indicators ──────────────────────────────────────────────

    def _draw_stick_indicators(self, draw, w, h, flight_state):
        size = 100
        pad = 30

        # Left Stick (THR/YAW)
        lx, ly = pad, h - size - pad - 20
        draw.rectangle([(lx, ly), (lx + size, ly + size)], outline=self.primary_color, width=1)
        # Grid lines
        draw.line([(lx + size // 2, ly), (lx + size // 2, ly + size)],
                  fill=(0, 255, 65, 80), width=1)
        draw.line([(lx, ly + size // 2), (lx + size, ly + size // 2)],
                  fill=(0, 255, 65, 80), width=1)
        # Label
        draw.text((lx, ly + size + 5), "THR / YAW", fill=self.primary_color, font=self.font_small)
        draw.text((lx, ly + size + 20), "W/S   A/D", fill=self.info_color, font=self.font_small)
        # Dot position
        yaw_val = flight_state.get("yaw", 128)
        thr_val = flight_state.get("throttle", 128)
        dot_x = lx + size / 2 + (yaw_val - 128) / 128 * (size / 2)
        dot_y = ly + size / 2 - (thr_val - 128) / 128 * (size / 2)
        dot_x = max(lx + 4, min(lx + size - 4, dot_x))
        dot_y = max(ly + 4, min(ly + size - 4, dot_y))
        draw.ellipse([(dot_x - 5, dot_y - 5), (dot_x + 5, dot_y + 5)],
                     fill=self.info_color, outline=self.primary_color)

        # Right Stick (PIT/ROL)
        rx, ry = w - size - pad, h - size - pad - 20
        draw.rectangle([(rx, ry), (rx + size, ry + size)], outline=self.primary_color, width=1)
        # Grid lines
        draw.line([(rx + size // 2, ry), (rx + size // 2, ry + size)],
                  fill=(0, 255, 65, 80), width=1)
        draw.line([(rx, ry + size // 2), (rx + size, ry + size // 2)],
                  fill=(0, 255, 65, 80), width=1)
        # Label
        draw.text((rx, ry + size + 5), "PIT / ROL", fill=self.primary_color, font=self.font_small)
        draw.text((rx, ry + size + 20), "Arrows", fill=self.info_color, font=self.font_small)
        # Dot position
        roll_val = flight_state.get("roll", 128)
        pitch_val = flight_state.get("pitch", 128)
        dot_x = rx + size / 2 + (roll_val - 128) / 128 * (size / 2)
        dot_y = ry + size / 2 - (pitch_val - 128) / 128 * (size / 2)
        dot_x = max(rx + 4, min(rx + size - 4, dot_x))
        dot_y = max(ry + 4, min(ry + size - 4, dot_y))
        draw.ellipse([(dot_x - 5, dot_y - 5), (dot_x + 5, dot_y + 5)],
                     fill=self.info_color, outline=self.primary_color)

    # ── Mode Indicators ───────────────────────────────────────────────

    def _draw_mode_indicators(self, draw, w, h, flight_state):
        x, y = w - 150, 50
        modes = [
            f"SPD: {flight_state.get('speed_mode', '--')}",
            f"HDLS: {'ON' if flight_state.get('headless', False) else 'OFF'}",
            f"LITE: {'ON' if flight_state.get('light', False) else 'OFF'}",
        ]
        for i, mode in enumerate(modes):
            draw.text((x, y + i * 20), mode, fill=self.primary_color, font=self.font_small)

    # ── Packet Counter ────────────────────────────────────────────────

    def _draw_packet_counter(self, draw, w, h, tx, rx):
        text = f"TX:{tx} RX:{rx}"
        draw.text((w - 120, h - 20), text, fill=self.info_color, font=self.font_small)

    # ── Recording Indicator ───────────────────────────────────────────

    def _draw_recording_indicator(self, draw, w, h, duration):
        cx = w // 2
        y = h // 10
        pulse = int(duration * 2) % 2 == 0
        if pulse:
            draw.ellipse([(cx - 60, y - 8), (cx - 44, y + 8)], fill=self.danger_color)
        mins, secs = divmod(int(duration), 60)
        draw.text((cx - 30, y - 10), f"REC {mins:02d}:{secs:02d}",
                  fill=self.danger_color, font=self.font_medium)

    # ── Autopilot Indicator ───────────────────────────────────────────

    def _draw_autopilot_indicator(self, draw, w, h, label, progress):
        cx = w // 2
        y = h - 80
        text = f"AP: {label}"
        tw, th = self._text_size(self.font_medium, text)
        x = (w - tw) / 2
        draw.rectangle([(x - 10, y - 5), (x + tw + 10, y + th + 5)], fill=self.bg_color)
        draw.text((x, y), text, fill=self.info_color, font=self.font_medium)
        # Progress bar
        bar_w = 200
        bar_y = y + th + 10
        draw.rectangle([(w / 2 - bar_w / 2, bar_y), (w / 2 + bar_w / 2, bar_y + 5)],
                       outline=self.info_color, width=1)
        draw.rectangle([(w / 2 - bar_w / 2, bar_y),
                         (w / 2 - bar_w / 2 + bar_w * progress, bar_y + 5)],
                       fill=self.info_color)

    # ── HUD Buttons ────────────────────────────────────────────────────

    def _draw_hud_buttons(self, draw, w, h):
        """Draw clickable HUD buttons on the right side below mode indicators."""
        self.button_rects.clear()

        btn_w, btn_h = 100, 28
        x = w - 160
        y_start = 120  # Below mode indicators
        spacing = 36

        buttons = [
            ("CALIBRATE", "calibrate"),
            ("CAM UP", "cam_up"),
            ("CAM DN", "cam_dn"),
            ("HOME RST", "home_rst"),
            ("TIMELAPSE", "timelapse"),
            ("INDOOR", "indoor"),
            ("TAKEOFF", "takeoff"),
            ("LAND", "land"),
        ]

        for i, (label, action) in enumerate(buttons):
            y = y_start + i * spacing
            x0, y0 = x, y
            x1, y1 = x + btn_w, y + btn_h

            # Semi-transparent background
            draw.rectangle([(x0, y0), (x1, y1)], fill=(0, 0, 0, 100))

            # Border with corner accents
            draw.rectangle([(x0, y0), (x1, y1)], outline=self.primary_color, width=1)

            # Corner accents (military HUD style)
            accent = 6
            for cx, cy in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:
                dx = accent if cx == x0 else -accent
                dy = accent if cy == y0 else -accent
                draw.line([(cx, cy), (cx + dx, cy)], fill=self.primary_color, width=2)
                draw.line([(cx, cy), (cx, cy + dy)], fill=self.primary_color, width=2)

            # Label text centered
            tw, th = self._text_size(self.font_small, label)
            tx = x0 + (btn_w - tw) // 2
            ty = y0 + (btn_h - th) // 2
            draw.text((tx, ty), label, fill=self.primary_color, font=self.font_small)

            # Register bounding box for click detection
            self.button_rects[action] = (x0, y0, x1, y1)

    # ── Mini-Map ───────────────────────────────────────────────────────

    def _draw_minimap(self, draw, w, h, app_state):
        """Draw circular radar-style mini-map with position and geofence."""
        radius = 80
        cx = w - radius - 30
        cy = h - radius - 80  # Above stick indicators

        pos_x = app_state.get("pos_x", 0.0)
        pos_y = app_state.get("pos_y", 0.0)
        distance = app_state.get("pos_distance", 0.0)
        heading = app_state.get("heading", 0.0)
        geofence_r = app_state.get("geofence_radius", 50.0)
        at_fence = app_state.get("at_geofence", False)
        beyond_fence = app_state.get("beyond_geofence", False)

        # Background circle
        draw.ellipse(
            [(cx - radius, cy - radius), (cx + radius, cy + radius)],
            fill=(0, 0, 0, 120)
        )

        # Boundary color based on geofence status
        if beyond_fence:
            ring_color = self.danger_color
        elif at_fence:
            ring_color = self.warning_color
        else:
            ring_color = self.primary_color

        # 50m boundary circle (outer)
        draw.ellipse(
            [(cx - radius, cy - radius), (cx + radius, cy + radius)],
            outline=ring_color, width=2
        )

        # 25m inner ring (half radius)
        inner_r = radius // 2
        draw.ellipse(
            [(cx - inner_r, cy - inner_r), (cx + inner_r, cy + inner_r)],
            outline=(ring_color[0], ring_color[1], ring_color[2], 100), width=1
        )

        # Crosshair lines through center
        draw.line([(cx - radius, cy), (cx + radius, cy)],
                  fill=(ring_color[0], ring_color[1], ring_color[2], 60), width=1)
        draw.line([(cx, cy - radius), (cx, cy + radius)],
                  fill=(ring_color[0], ring_color[1], ring_color[2], 60), width=1)

        # Home marker "H" at center
        tw, th = self._text_size(self.font_small, "H")
        draw.text((cx - tw // 2, cy - th // 2), "H",
                  fill=self.info_color, font=self.font_small)

        # Cardinal direction labels
        for label, dx, dy in [("N", 0, -radius + 5), ("S", 0, radius - 15),
                               ("E", radius - 12, -5), ("W", -radius + 3, -5)]:
            lw, _ = self._text_size(self.font_small, label)
            draw.text((cx + dx - lw // 2, cy + dy), label,
                      fill=ring_color, font=self.font_small)

        # Drone position as triangle pointing in heading direction
        if geofence_r > 0:
            # Scale: map geofence_radius meters to the radar circle radius
            scale = radius / geofence_r
            drone_px = cx + pos_x * scale
            drone_py = cy - pos_y * scale  # Y inverted (screen coords)

            # Clamp within circle
            dx = drone_px - cx
            dy = drone_py - cy
            dist_px = math.sqrt(dx * dx + dy * dy)
            if dist_px > radius - 5:
                drone_px = cx + dx / dist_px * (radius - 5)
                drone_py = cy + dy / dist_px * (radius - 5)

            # Triangle pointing in heading direction
            heading_rad = math.radians(heading)
            tri_size = 6
            tip_x = drone_px + math.sin(heading_rad) * tri_size
            tip_y = drone_py - math.cos(heading_rad) * tri_size
            left_x = drone_px + math.sin(heading_rad - 2.4) * tri_size * 0.7
            left_y = drone_py - math.cos(heading_rad - 2.4) * tri_size * 0.7
            right_x = drone_px + math.sin(heading_rad + 2.4) * tri_size * 0.7
            right_y = drone_py - math.cos(heading_rad + 2.4) * tri_size * 0.7

            draw.polygon(
                [(tip_x, tip_y), (left_x, left_y), (right_x, right_y)],
                fill=self.info_color
            )

        # Distance readout below
        dist_text = f"{distance:.1f}m"
        tw, _ = self._text_size(self.font_small, dist_text)
        draw.text((cx - tw // 2, cy + radius + 4), dist_text,
                  fill=ring_color, font=self.font_small)

    # ── Geofence Breach Border ─────────────────────────────────────────

    def _draw_geofence_border(self, draw, w, h):
        """Pulsing red border when beyond geofence."""
        pulse = int(time.time() * 3) % 2 == 0
        if pulse:
            border_w = 4
            color = self.danger_color
            # Top
            draw.rectangle([(0, 0), (w, border_w)], fill=color)
            # Bottom
            draw.rectangle([(0, h - border_w), (w, h)], fill=color)
            # Left
            draw.rectangle([(0, 0), (border_w, h)], fill=color)
            # Right
            draw.rectangle([(w - border_w, 0), (w, h)], fill=color)

    # ── Help Overlay ──────────────────────────────────────────────────

    def _draw_help_overlay(self, draw, w, h):
        panel_w, panel_h = int(w * 0.65), int(h * 0.75)
        x0, y0 = (w - panel_w) // 2, (h - panel_h) // 2
        draw.rectangle([(x0, y0), (x0 + panel_w, y0 + panel_h)], fill=(0, 0, 0, 220))
        draw.rectangle([(x0, y0), (x0 + panel_w, y0 + panel_h)],
                       outline=self.primary_color, width=2)

        # Title
        draw.text((x0 + 20, y0 + 15), "KEYBOARD CONTROLS",
                  font=self.font_large, fill=self.primary_color)

        # Divider
        draw.line([(x0 + 20, y0 + 50), (x0 + panel_w - 20, y0 + 50)],
                  fill=self.primary_color, width=1)

        controls_left = [
            ("", "-- LEFT STICK --"),
            ("W", "Throttle Up (Climb)"),
            ("S", "Throttle Down (Descend)"),
            ("A", "Yaw Left (Spin Left)"),
            ("D", "Yaw Right (Spin Right)"),
            ("", ""),
            ("", "-- RIGHT STICK --"),
            ("Up", "Pitch Forward"),
            ("Down", "Pitch Backward"),
            ("Left", "Roll Left (Strafe)"),
            ("Right", "Roll Right (Strafe)"),
        ]

        controls_right = [
            ("", "-- COMMANDS --"),
            ("T", "Takeoff"),
            ("L", "Land"),
            ("SPACE", "Emergency Stop"),
            ("C", "Calibrate + Reset Home"),
            ("X", "Flip"),
            ("Home", "Reset Home Position"),
            ("", ""),
            ("", "-- SETTINGS --"),
            ("1/2/3", "Speed Low/Med/High"),
            ("H", "Toggle Headless"),
            ("F", "Toggle Lights"),
            ("V", "Toggle Video"),
            ("P", "Take Photo"),
            ("R", "Record Video"),
            ("B", "Switch Camera"),
            ("G", "Rotate Camera 180"),
            ("Y", "Toggle Timelapse"),
            ("I", "Toggle Indoor Mode"),
            ("Tab", "Toggle HUD"),
            ("F11", "Fullscreen"),
            ("Q", "Quit"),
        ]

        col1_key = x0 + 30
        col1_desc = x0 + 100
        col2_key = x0 + panel_w // 2 + 10
        col2_desc = x0 + panel_w // 2 + 100
        y_start = y0 + 65

        for i, (key, desc) in enumerate(controls_left):
            y = y_start + i * 22
            if key:
                draw.text((col1_key, y), key, font=self.font_medium, fill=self.info_color)
                draw.text((col1_desc, y), desc, font=self.font_small, fill=self.primary_color)
            else:
                draw.text((col1_key, y), desc, font=self.font_small, fill=self.warning_color)

        for i, (key, desc) in enumerate(controls_right):
            y = y_start + i * 22
            if key:
                draw.text((col2_key, y), key, font=self.font_medium, fill=self.info_color)
                draw.text((col2_desc, y), desc, font=self.font_small, fill=self.primary_color)
            else:
                draw.text((col2_key, y), desc, font=self.font_small, fill=self.warning_color)

    # ── Disconnected Warning ──────────────────────────────────────────

    def _draw_disconnected(self, draw, w, h):
        """Pulsing disconnected warning."""
        pulse = int(time.time() * 2) % 2 == 0
        if pulse:
            tw, th = self._text_size(self.font_xl, "DISCONNECTED")
            x = (w - tw) // 2
            y = h // 3
            draw.rectangle([(x - 20, y - 10), (x + tw + 20, y + th + 10)],
                           fill=(0, 0, 0, 200))
            draw.text((x, y), "DISCONNECTED", fill=self.danger_color, font=self.font_xl)
