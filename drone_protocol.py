'''
Module: drone_protocol.py
Description: Handles all UDP communication with the Pallton X80 drone using the XR872 protocol.
'''

import socket
import threading
import time
import platform
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List

# Constants
DRONE_IP = "192.168.28.1"
CONTROL_PORT = 7080
VIDEO_PORT = 7070
CONTROL_INTERVAL = 0.140  # 140ms
HEARTBEAT_INTERVAL = 1.0

# XR872 Protocol Constants
CONTROL_HEADER = 0x66
CONTROL_TAIL = 0x99
CONTROL_LEN = 20
HEARTBEAT_PACKET = b'\x00'
CMD_PREFIX = b'\xcc\x5a'

# Commands
CMD_VIDEO_START = CMD_PREFIX + b'\x01\x82\x02\x36\xb7'
CMD_VIDEO_STOP = CMD_PREFIX + b'\x01\x82\x02\x37\xb6'

@dataclass
class Telemetry:
    battery_pct: int = 0
    battery_voltage: float = 0.0
    altitude: int = 0
    speed_x: int = 0
    speed_y: int = 0
    is_flying: bool = False
    is_calibrating: bool = False
    signal_strength: int = 0
    drone_ssid: str = ""
    firmware_ver: str = ""
    flight_time: int = 0
    last_update: float = 0.0
    heading: int = 0 # 0-359 degrees

@dataclass
class FlightState:
    roll: int = 0  # -100 to 100
    pitch: int = 0 # -100 to 100
    throttle: int = 0 # -100 to 100
    yaw: int = 0 # -100 to 100
    takeoff: bool = False
    landing: bool = False
    emergency_stop: bool = False
    calibration: bool = False
    flip: bool = False
    light: bool = False
    headless: bool = False
    cam_up: bool = False
    cam_down: bool = False
    speed: float = 0.5 # 0.0 to 1.0
    trim_roll: int = 0
    trim_pitch: int = 0
    trim_yaw: int = 0

class DroneProtocol:
    '''Handles the XR872 drone communication protocol.'''

    def __init__(self):
        self.control_socket: Optional[socket.socket] = None
        self.video_socket: Optional[socket.socket] = None
        self.is_connected = False
        self.flight_state = FlightState()
        self.telemetry = Telemetry()

        self.on_video_frame: Optional[Callable[[bytes], None]] = None
        self.on_telemetry: Optional[Callable[[Telemetry], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None

        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._video_frames: Dict[int, Dict[int, bytes]] = {}
        self._last_yaw_time = time.time()
        self._start_time = 0

    def connect(self):
        '''Establishes UDP connection and starts communication loops.'''
        if self.is_connected:
            return

        try:
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.control_socket.bind(("", CONTROL_PORT))
            self.video_socket.bind(("", VIDEO_PORT))

            # Windows-specific socket option to prevent ICMP errors
            if platform.system() == "Windows":
                try:
                    SIO_UDP_CONNRESET = -1744830452
                    self.control_socket.ioctl(SIO_UDP_CONNRESET, 0)
                    self.video_socket.ioctl(SIO_UDP_CONNRESET, 0)
                except Exception as e:
                    if self.on_status: self.on_status(f"Warning: Failed to set SIO_UDP_CONNRESET: {e}")

            self.is_connected = True
            self._stop_event.clear()
            self._start_time = time.time()

            self._threads = [
                threading.Thread(target=self._control_loop, daemon=True),
                threading.Thread(target=self._heartbeat_loop, daemon=True),
                threading.Thread(target=self._receive_loop, daemon=True),
                threading.Thread(target=self._video_loop, daemon=True),
                threading.Thread(target=self._watchdog_loop, daemon=True)
            ]
            for t in self._threads: t.start()

            if self.on_status: self.on_status("Connection established.")

        except socket.error as e:
            if self.on_status: self.on_status(f"Connection failed: {e}")
            self.disconnect()

    def disconnect(self):
        '''Stops communication and closes sockets.'''
        if not self.is_connected:
            return

        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=1.0)

        if self.control_socket: self.control_socket.close()
        if self.video_socket: self.video_socket.close()

        self.is_connected = False
        if self.on_status: self.on_status("Connection closed.")

    def _build_control_packet(self) -> bytes:
        packet = bytearray(CONTROL_LEN)
        packet[0] = CONTROL_HEADER
        packet[1] = CONTROL_LEN

        # Scale -100..100 to 0..255
        packet[2] = int((self.flight_state.roll + 100) / 200 * 255)
        packet[3] = int((self.flight_state.pitch + 100) / 200 * 255)
        packet[4] = int((self.flight_state.throttle + 100) / 200 * 255)
        packet[5] = int((self.flight_state.yaw + 100) / 200 * 255)

        # Flags1
        flags1 = 0
        if self.flight_state.takeoff: flags1 |= 1 << 0
        if self.flight_state.emergency_stop: flags1 |= 1 << 1
        if self.flight_state.calibration: flags1 |= 1 << 2
        if self.flight_state.flip: flags1 |= 1 << 3
        if self.flight_state.light: flags1 |= 1 << 4
        if self.flight_state.landing: flags1 |= 1 << 7
        packet[6] = flags1

        # Flags2
        flags2 = 1 << 1 # Always set
        if self.flight_state.headless: flags2 |= 1 << 0
        if self.flight_state.cam_up: flags2 |= 1 << 4
        if self.flight_state.cam_down: flags2 |= 1 << 5
        packet[7] = flags2

        # Bytes 8-17 are reserved (0)

        # Checksum
        checksum = 0
        for i in range(2, 18):
            checksum ^= packet[i]
        packet[18] = checksum

        packet[19] = CONTROL_TAIL
        return bytes(packet)

    def _control_loop(self):
        while not self._stop_event.is_set():
            if self.control_socket:
                try:
                    packet = self._build_control_packet()
                    self.control_socket.sendto(packet, (DRONE_IP, CONTROL_PORT))
                    self._update_heading()
                except socket.error as e:
                    if self.on_status: self.on_status(f"Control loop error: {e}")
                    time.sleep(1)
            time.sleep(CONTROL_INTERVAL)

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            if self.control_socket:
                try:
                    self.control_socket.sendto(HEARTBEAT_PACKET, (DRONE_IP, CONTROL_PORT))
                except socket.error as e:
                    if self.on_status: self.on_status(f"Heartbeat error: {e}")
            time.sleep(HEARTBEAT_INTERVAL)

    def _receive_loop(self):
        # This is a placeholder for telemetry parsing. The XR872 spec is incomplete on this.
        # In a real scenario, we would parse telemetry packets here.
        while not self._stop_event.is_set():
            try:
                if self.control_socket:
                    data, _ = self.control_socket.recvfrom(1024)
                    # Assuming a simple key-value string format for now
                    # e.g., "bat:80;alt:10;spd_x:2;..."
                    self._parse_telemetry(data)
            except (socket.error, BlockingIOError) as e:
                if isinstance(e, socket.error) and e.winerror == 10054:
                    pass # Ignore connection reset by peer on Windows
                else:
                    if self.on_status: self.on_status(f"Receive loop error: {e}")
                    time.sleep(1)

    def _parse_telemetry(self, data: bytes):
        try:
            # This is a mock parser. Replace with actual protocol parsing.
            parts = data.decode('utf-8').strip().split(';')
            for part in parts:
                key, value = part.split(':')
                if key == 'bat': self.telemetry.battery_pct = int(value)
                elif key == 'alt': self.telemetry.altitude = int(value)
            self.telemetry.last_update = time.time()
            if self.on_telemetry: self.on_telemetry(self.telemetry)
        except Exception:
            pass # Ignore malformed packets

    def _video_loop(self):
        while not self._stop_event.is_set():
            try:
                if self.video_socket:
                    data, _ = self.video_socket.recvfrom(65536)
                    if len(data) > 4:
                        frame_id = data[0]
                        is_last = data[1]
                        packet_num = data[2]
                        payload = data[4:]

                        if frame_id not in self._video_frames: self._video_frames[frame_id] = {}
                        self._video_frames[frame_id][packet_num] = payload

                        if is_last == 1:
                            self._reassemble_frame(frame_id)
            except (socket.error, BlockingIOError) as e:
                if isinstance(e, socket.error) and e.winerror == 10054:
                    pass # Ignore connection reset by peer on Windows
                else:
                    if self.on_status: self.on_status(f"Video loop error: {e}")
                    time.sleep(1)

    def _reassemble_frame(self, frame_id: int):
        if frame_id not in self._video_frames: return
        frame_packets = self._video_frames[frame_id]
        sorted_packets = sorted(frame_packets.items())
        
        full_frame = b''.join([p[1] for p in sorted_packets])

        # Find JPEG start marker
        jpeg_start = full_frame.find(b'\xff\xd8')
        if jpeg_start != -1:
            if self.on_video_frame:
                self.on_video_frame(full_frame[jpeg_start:])
        
        # Clean up old frames
        del self._video_frames[frame_id]
        for fid in list(self._video_frames.keys()):
            if fid < frame_id: del self._video_frames[fid]

    def _watchdog_loop(self):
        while not self._stop_event.is_set():
            if self.is_connected and (time.time() - self.telemetry.last_update > 5.0):
                if self.on_status: self.on_status("Connection may be lost (no telemetry).")
                # Consider attempting a reconnect here
            time.sleep(5.0)

    def _update_heading(self):
        now = time.time()
        dt = now - self._last_yaw_time
        self._last_yaw_time = now
        # Assuming max yaw rate of 90 deg/s at full stick
        yaw_rate = (self.flight_state.yaw / 100.0) * 90
        self.telemetry.heading = (self.telemetry.heading + yaw_rate * dt) % 360

    def send_cmd(self, cmd: bytes):
        '''Sends a raw command to the drone's control port.'''
        if self.control_socket and self.is_connected:
            try:
                self.control_socket.sendto(cmd, (DRONE_IP, CONTROL_PORT))
            except socket.error as e:
                if self.on_status: self.on_status(f"Command send error: {e}")

    # --- Public Flight Commands ---
    def takeoff(self): self.flight_state.takeoff = True
    def land(self): self.flight_state.landing = True
    def emergency_stop(self): self.flight_state.emergency_stop = True
    def calibrate(self): self.flight_state.calibration = True
    def flip(self): self.flight_state.flip = True
    def toggle_light(self): self.flight_state.light = not self.flight_state.light
    def toggle_headless(self): self.flight_state.headless = not self.flight_state.headless
    def set_speed(self, level: float): self.flight_state.speed = max(0.0, min(1.0, level))

    # --- Public Camera Commands ---
    def start_video(self): self.send_cmd(CMD_VIDEO_START)
    def stop_video(self): self.send_cmd(CMD_VIDEO_STOP)
    def take_photo(self): pass # Protocol for this is not defined in the spec
    def camera_up(self): self.flight_state.cam_up = True; self.flight_state.cam_down = False
    def camera_down(self): self.flight_state.cam_down = True; self.flight_state.cam_up = False
    def camera_stop(self): self.flight_state.cam_up = False; self.flight_state.cam_down = False
    def switch_camera(self): pass # Protocol for this is not defined in the spec

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time if self.is_connected else 0

    @property
    def speed_name(self) -> str:
        if self.flight_state.speed < 0.33: return "LOW"
        if self.flight_state.speed < 0.66: return "MED"
        return "HIGH"

if __name__ == '__main__':
    # Example Usage
    def handle_video(frame: bytes):
        print(f"Received video frame of size {len(frame)}")

    def handle_telemetry(telemetry: Telemetry):
        print(f"Telemetry update: {telemetry}")

    def handle_status(status: str):
        print(f"Status: {status}")

    drone = DroneProtocol()
    drone.on_video_frame = handle_video
    drone.on_telemetry = handle_telemetry
    drone.on_status = handle_status

    print("Connecting to drone...")
    drone.connect()
    drone.start_video()

    try:
        # Simulate flight controls
        print("Simulating flight for 10 seconds...")
        drone.flight_state.throttle = 20 # Gentle climb
        time.sleep(2)
        drone.flight_state.yaw = 50 # Gentle turn
        time.sleep(3)
        drone.flight_state.yaw = 0
        drone.flight_state.pitch = 10 # Move forward
        time.sleep(5)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        drone.disconnect()
        print("Disconnected.")

