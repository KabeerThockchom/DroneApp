'''
This module provides the AppConfig dataclass for managing application settings,
as well as dictionaries for keyboard mappings and stick layouts.
'''

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple, Any

@dataclass
class AppConfig:
    """Manages all application configuration settings for the drone controller."""
    drone_ip: str = '192.168.28.1'
    rxtx_port: int = 7080
    video_port: int = 7070
    keyboard_sensitivity: float = 80.0
    throttle_ramp_speed: float = 4.0
    gamepad_deadzone: float = 0.1
    gamepad_invert_throttle: bool = True
    show_hud: bool = True
    hud_opacity: int = 120
    crosshair: bool = True
    auto_record: bool = False
    low_battery_warning: int = 20
    auto_land_battery: int = 10
    default_speed: int = 2
    fullscreen: bool = True
    geofence_radius: float = 50.0
    geofence_warning_radius: float = 45.0
    max_drone_speed: float = 5.0
    show_minimap: bool = True
    show_hud_buttons: bool = True

    def save(self, file_path: str = "config.json") -> None:
        """Saves the current configuration to a JSON file."""
        try:
            with open(file_path, 'w') as f:
                json.dump(asdict(self), f, indent=4)
        except IOError as e:
            print(f"Error saving configuration: {e}")

    def load(self, file_path: str = "config.json") -> None:
        """Loads configuration from a JSON file, updating the current object."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                for key, value in data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading configuration: {e}. Using default settings.")
            self.reset()

    def reset(self) -> None:
        """Resets the configuration to its default values."""
        default_config = AppConfig()
        for key, value in asdict(default_config).items():
            setattr(self, key, value)

# Part 2: Keyboard Mapping
KEYBOARD_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Flight": [
        ("W", "Throttle Up"),
        ("S", "Throttle Down"),
        ("A", "Yaw Left"),
        ("D", "Yaw Right"),
        ("Up", "Pitch Forward"),
        ("Down", "Pitch Backward"),
        ("Left", "Roll Left"),
        ("Right", "Roll Right"),
        ("Shift+Arrows", "Trim Flight Controls")
    ],
    "Commands": [
        ("T", "Takeoff"),
        ("L", "Land"),
        ("Space", "Emergency Stop"),
        ("C", "Calibrate Sensors"),
        ("X", "Execute Flip Maneuver")
    ],
    "Camera": [
        ("V", "Toggle Video Stream"),
        ("P", "Take Photo"),
        ("R", "Start/Stop Recording"),
        ("Prior", "Tilt Camera Up"), # Page Up
        ("Next", "Tilt Camera Down")   # Page Down
    ],
    "Settings": [
        ("1", "Set Speed to Low"),
        ("2", "Set Speed to Medium"),
        ("3", "Set Speed to High"),
        ("H", "Toggle Headless Mode"),
        ("F", "Toggle Lights"),
        ("Tab", "Toggle HUD Display"),
        ("?", "Show Help / Keyboard Map"),
        ("Q", "Quit Application"),
        ("F11", "Toggle Fullscreen")
    ],
    "Position": [
        ("Home", "Reset Home Position"),
    ],
    "Autopilot": [
        ("Control-1", "Execute Pattern 1 (Orbit)"),
        ("Control-2", "Execute Pattern 2 (Waypoint)"),
        ("Control-3", "Execute Pattern 3 (Follow Me)"),
        ("Control-4", "Execute Pattern 4 (Cable Cam)"),
        ("Control-5", "Execute Pattern 5 (Selfie)"),
        ("Control-6", "Execute Pattern 6"),
        ("Control-7", "Execute Pattern 7"),
        ("Control-8", "Execute Pattern 8"),
        ("Control-9", "Execute Pattern 9"),
        ("Control-0", "Execute Pattern 0"),
        ("Escape", "Stop Autopilot / Return to Manual")
    ]
}

# Part 3: Stick Layout
STICK_LAYOUT: Dict[str, Dict[str, str]] = {
    "left_stick": {
        "label": "THR / YAW",
        "up": "Climb",
        "down": "Descend",
        "left": "Spin Left",
        "right": "Spin Right",
        "keys": "W/S + A/D"
    },
    "right_stick": {
        "label": "PIT / ROL",
        "up": "Forward",
        "down": "Backward",
        "left": "Strafe Left",
        "right": "Strafe Right",
        "keys": "Arrows"
    }
}

if __name__ == '__main__':
    # Example Usage
    config = AppConfig()

    # 1. Print default config
    print("--- Default Configuration ---")
    print(config)

    # 2. Modify and save
    config.drone_ip = "192.168.28.100"
    config.keyboard_sensitivity = 95.5
    config.save("my_config.json")
    print("\n--- Saved Modified Configuration to my_config.json ---")

    # 3. Create a new config object and load from file
    new_config = AppConfig()
    print("\n--- New Config (default) ---")
    print(new_config)
    new_config.load("my_config.json")
    print("\n--- Loaded Configuration from my_config.json ---")
    print(new_config)

    # 4. Reset config
    new_config.reset()
    print("\n--- Reset Configuration ---")
    print(new_config)

    # 5. Print keyboard and stick layouts
    print("\n--- Keyboard Map ---")
    for category, mappings in KEYBOARD_MAP.items():
        print(f"  {category}:")
        for key, desc in mappings:
            print(f"    {key:<15} - {desc}")

    print("\n--- Stick Layout ---")
    print(f"Left Stick ({STICK_LAYOUT['left_stick']['label']}): {STICK_LAYOUT['left_stick']['keys']}")
    print(f"Right Stick ({STICK_LAYOUT['right_stick']['label']}): {STICK_LAYOUT['right_stick']['keys']}")
