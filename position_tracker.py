"""
Dead-reckoning position tracker for the Pallton X80 drone.
Estimates X/Y position from stick inputs and heading since there is no GPS.
"""

import math
import time
from dataclasses import dataclass


@dataclass
class Position:
    """Current estimated position relative to home."""
    x: float = 0.0          # meters, positive = East
    y: float = 0.0          # meters, positive = North
    distance: float = 0.0   # meters from home
    bearing: float = 0.0    # degrees from home (0=N, 90=E)


class PositionTracker:
    """
    Dead-reckoning position estimator.

    Converts stick pitch/roll inputs + heading into world-frame velocity,
    then integrates over time to estimate displacement from home.

    Limitations:
    - No GPS correction — error accumulates over time.
    - Speed estimate (~5 m/s max) is approximate.
    - Only tracks X/Y, not altitude.
    """

    def __init__(self, max_speed: float = 5.0,
                 geofence_radius: float = 50.0,
                 geofence_warning_radius: float = 45.0):
        self.max_speed = max_speed
        self.geofence_radius = geofence_radius
        self.geofence_warning_radius = geofence_warning_radius

        self.position = Position()
        self._last_time = time.time()

    def update(self, pitch: float, roll: float, heading: float,
               speed_mode: str = "MED", is_flying: bool = False):
        """
        Update estimated position based on current stick inputs.

        Args:
            pitch: -100 to +100 (negative = forward)
            roll: -100 to +100 (positive = right)
            heading: 0-359 degrees (from telemetry)
            speed_mode: "LOW", "MED", or "HIGH"
            is_flying: whether the drone is airborne
        """
        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        # Clamp dt to avoid huge jumps (e.g. after pause)
        dt = min(dt, 0.5)

        if not is_flying or dt <= 0:
            return

        # Speed multiplier based on mode
        mode_mult = {"LOW": 0.5, "MED": 0.75, "HIGH": 1.0}.get(speed_mode, 0.75)

        # Body-frame velocities (m/s) from stick inputs
        # pitch: negative = forward (positive Y in body frame)
        # roll: positive = right (positive X in body frame)
        vx_body = (roll / 100.0) * self.max_speed * mode_mult
        vy_body = (-pitch / 100.0) * self.max_speed * mode_mult

        # Rotate body frame to world frame using heading
        heading_rad = math.radians(heading)
        cos_h = math.cos(heading_rad)
        sin_h = math.sin(heading_rad)

        # World frame: X = East, Y = North
        vx_world = vx_body * cos_h + vy_body * sin_h
        vy_world = -vx_body * sin_h + vy_body * cos_h

        # Integrate position
        self.position.x += vx_world * dt
        self.position.y += vy_world * dt

        # Update distance and bearing
        self.position.distance = math.sqrt(
            self.position.x ** 2 + self.position.y ** 2
        )
        if self.position.distance > 0.01:
            self.position.bearing = (
                math.degrees(math.atan2(self.position.x, self.position.y)) % 360
            )

    def reset_home(self):
        """Re-zero position to current location."""
        self.position = Position()
        self._last_time = time.time()

    @property
    def at_geofence(self) -> bool:
        """True when within warning zone (45-50m by default)."""
        return (self.position.distance >= self.geofence_warning_radius
                and self.position.distance < self.geofence_radius)

    @property
    def beyond_geofence(self) -> bool:
        """True when past the geofence boundary."""
        return self.position.distance >= self.geofence_radius
