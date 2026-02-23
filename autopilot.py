'''
Autopilot module for automated flight patterns.

This module provides classes for defining and executing time-based flight patterns
for the Pallton X80 drone. Since the drone has no GPS, all patterns are
sequences of control inputs over time.
'''

import time
import threading
import math
from dataclasses import dataclass
from typing import List, Dict, Callable, Optional, Any


@dataclass
class FlightStep:
    """Represents a single step in an automated flight pattern."""
    roll: float = 0.0
    pitch: float = 0.0
    throttle: float = 0.0
    yaw: float = 0.0
    duration: float = 1.0
    label: str = ""


class FlightPattern:
    """
    Represents a named sequence of FlightSteps.

    Includes static factory methods to generate common flight patterns.
    Control values for roll, pitch, throttle, and yaw are from -100 to +100.
    """
    def __init__(self, name: str, steps: List[FlightStep], repeat: bool = False):
        self.name = name
        self.steps = steps
        self.repeat = repeat

    @staticmethod
    def circle(radius_time: float = 2.0, speed: float = 50) -> 'FlightPattern':
        """Creates a circular flight pattern."""
        steps = [
            FlightStep(pitch=speed, yaw=50, duration=radius_time * math.pi * 2, label="Circle")
        ]
        return FlightPattern("Circle", steps)

    @staticmethod
    def square(side_time: float = 2.0, speed: float = 50) -> 'FlightPattern':
        """Creates a square flight pattern."""
        turn_duration = 0.75  # Time to make a 90-degree turn
        steps = []
        for i in range(4):
            steps.append(FlightStep(pitch=speed, duration=side_time, label=f"Side {i+1}"))
            steps.append(FlightStep(yaw=75, duration=turn_duration, label=f"Turn {i+1}"))
        return FlightPattern("Square", steps)

    @staticmethod
    def figure_eight(duration: float = 3.0, speed: float = 50) -> 'FlightPattern':
        """Creates a figure-eight flight pattern."""
        steps = [
            FlightStep(pitch=speed, yaw=50, duration=duration, label="Right Loop"),
            FlightStep(pitch=speed, yaw=-50, duration=duration, label="Left Loop"),
        ]
        return FlightPattern("Figure Eight", steps)

    @staticmethod
    def zigzag(legs: int = 4, leg_time: float = 1.5, speed: float = 50) -> 'FlightPattern':
        """Creates a zigzag flight pattern."""
        steps = []
        for i in range(legs):
            roll_val = speed if i % 2 == 0 else -speed
            steps.append(FlightStep(pitch=speed, roll=roll_val, duration=leg_time, label=f"Leg {i+1}"))
        return FlightPattern("Zigzag", steps)

    @staticmethod
    def hover_rotate(duration: float = 8.0, speed: float = 40) -> 'FlightPattern':
        """Creates a 360-degree panoramic spin."""
        steps = [FlightStep(yaw=speed, duration=duration, label="Rotate")]
        return FlightPattern("Hover & Rotate", steps)

    @staticmethod
    def ascend_descend(height_time: float = 3.0, speed: float = 50) -> 'FlightPattern':
        """Ascends, hovers, and then descends."""
        steps = [
            FlightStep(throttle=speed, duration=height_time, label="Ascend"),
            FlightStep(duration=2.0, label="Hover"),
            FlightStep(throttle=-speed, duration=height_time, label="Descend"),
        ]
        return FlightPattern("Ascend & Descend", steps)

    @staticmethod
    def orbit(orbit_time: float = 10.0, speed: float = 40) -> 'FlightPattern':
        """Orbits a central point."""
        steps = [FlightStep(roll=speed, yaw=20, duration=orbit_time, label="Orbit")]
        return FlightPattern("Orbit", steps)

    @staticmethod
    def helix(duration: float = 6.0, speed: float = 40) -> 'FlightPattern':
        """Ascends in a circular path."""
        steps = [FlightStep(throttle=speed, pitch=speed, yaw=50, duration=duration, label="Helix")]
        return FlightPattern("Helix", steps)

    @staticmethod
    def pendulum(swings: int = 4, swing_time: float = 1.5, speed: float = 50) -> 'FlightPattern':
        """Swings left and right like a pendulum."""
        steps = []
        for i in range(swings):
            roll_val = speed if i % 2 == 0 else -speed
            steps.append(FlightStep(roll=roll_val, duration=swing_time, label=f"Swing {i+1}"))
        return FlightPattern("Pendulum", steps)

    @staticmethod
    def spiral_out(duration: float = 8.0, speed: float = 40) -> 'FlightPattern':
        """Flies in an expanding spiral."""
        # This is a simplified approximation
        steps = [FlightStep(pitch=speed, yaw=50, roll=20, duration=duration, label="Spiral Out")]
        return FlightPattern("Spiral Out", steps)


class Autopilot:
    """
    Manages the execution of automated flight patterns in a separate thread.
    Provides callbacks for state changes and progress updates.
    """
    def __init__(self, drone_state: Any):
        self._drone_state = drone_state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active = False
        self._current_step_label = ""
        self._progress = 0.0
        self.on_step_change: Optional[Callable[[str], None]] = None
        self.on_complete: Optional[Callable[[], None]] = None
        self.on_progress: Optional[Callable[[float], None]] = None

    @property
    def active(self) -> bool:
        """Returns True if the autopilot is currently executing a pattern."""
        return self._active

    @property
    def current_step_label(self) -> str:
        """Returns the label of the currently executing flight step."""
        return self._current_step_label

    @property
    def progress(self) -> float:
        """Returns the overall progress of the flight pattern (0.0 to 1.0)."""
        return self._progress

    def start(self, pattern: FlightPattern):
        """Starts executing a flight pattern in a background thread."""
        if self.active:
            self.stop()

        self._active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_pattern, args=(pattern,))
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        """Stops the currently executing flight pattern."""
        if not self.active:
            return

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()
        self._reset_controls()
        self._active = False
        self._current_step_label = ""
        self._progress = 0.0

    def _run_pattern(self, pattern: FlightPattern):
        """The main loop for executing a flight pattern."""
        total_duration = sum(step.duration for step in pattern.steps)
        elapsed_time = 0.0

        while not self._stop_event.is_set():
            for step in pattern.steps:
                if self._stop_event.is_set():
                    break

                self._current_step_label = step.label
                if self.on_step_change:
                    self.on_step_change(step.label)

                self._update_controls(step)

                step_start_time = time.time()
                while time.time() - step_start_time < step.duration:
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.05)
                    current_elapsed = elapsed_time + (time.time() - step_start_time)
                    self._progress = min(1.0, current_elapsed / total_duration)
                    if self.on_progress:
                        self.on_progress(self._progress)
                
                elapsed_time += step.duration

            if not pattern.repeat:
                break

        self._reset_controls()
        self._active = False
        if self.on_complete:
            self.on_complete()

    def _update_controls(self, step: FlightStep):
        """Updates the drone state with the control values from the flight step."""
        # This is a mock implementation. In a real scenario, this would
        # update a shared state object that the main control loop reads from.
        self._drone_state['roll'] = step.roll
        self._drone_state['pitch'] = step.pitch
        self._drone_state['throttle'] = step.throttle
        self._drone_state['yaw'] = step.yaw

    def _reset_controls(self):
        """Resets all control inputs to zero."""
        self._drone_state['roll'] = 0
        self._drone_state['pitch'] = 0
        self._drone_state['throttle'] = 0
        self._drone_state['yaw'] = 0

    @staticmethod
    def get_patterns() -> Dict[str, Callable[..., FlightPattern]]:
        """Returns a dictionary of available flight pattern factories."""
        return {
            "Circle": FlightPattern.circle,
            "Square": FlightPattern.square,
            "Figure Eight": FlightPattern.figure_eight,
            "Zigzag": FlightPattern.zigzag,
            "Hover & Rotate": FlightPattern.hover_rotate,
            "Ascend & Descend": FlightPattern.ascend_descend,
            "Orbit": FlightPattern.orbit,
            "Helix": FlightPattern.helix,
            "Pendulum": FlightPattern.pendulum,
            "Spiral Out": FlightPattern.spiral_out,
        }
