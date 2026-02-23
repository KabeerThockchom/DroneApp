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
        self._command_timers: Dict[str, float] = {}
        self._last_video_time = 0.0
        self._send_errors = 0
        self.packets_sent = 0
        self.packets_received = 0

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

    def reconnect(self):
        '''Tear down and re-establish connection.'''
        # Stop all threads
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=1.0)

        # Close sockets
        for sock in (self.control_socket, self.video_socket):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self.control_socket = None
        self.video_socket = None
        self.is_connected = False
        self._send_errors = 0
        self._video_frames.clear()

        # Re-connect
        time.sleep(0.5)
        self.connect()

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

    def _clear_expired_commands(self):
        '''Auto-clear one-shot command flags after ~1 second.'''
        now = time.time()
        flag_map = {
            'takeoff': 'takeoff',
            'landing': 'landing',
            'emergency_stop': 'emergency_stop',
            'calibration': 'calibration',
            'flip': 'flip',
        }
        for timer_key, state_attr in flag_map.items():
            if timer_key in self._command_timers:
                if now - self._command_timers[timer_key] > 1.0:
                    setattr(self.flight_state, state_attr, False)
                    del self._command_timers[timer_key]

    def _control_loop(self):
        while not self._stop_event.is_set():
            if self.control_socket:
                try:
                    self._clear_expired_commands()
                    packet = self._build_control_packet()
                    self.control_socket.sendto(packet, (DRONE_IP, CONTROL_PORT))
                    self._update_heading()
                    self.packets_sent += 1
                    self._send_errors = 0
                except socket.error:
                    self._send_errors += 1
                    time.sleep(0.5)
            time.sleep(CONTROL_INTERVAL)

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            if self.control_socket:
                try:
                    self.control_socket.sendto(HEARTBEAT_PACKET, (DRONE_IP, CONTROL_PORT))
                except socket.error:
                    pass  # Errors tracked by watchdog, don't spam status
            time.sleep(HEARTBEAT_INTERVAL)

    def _receive_loop(self):
        buf = bytearray()
        while not self._stop_event.is_set():
            try:
                if self.control_socket:
                    data, _ = self.control_socket.recvfrom(1024)
                    buf.extend(data)
                    # Process all complete packets in the buffer
                    while len(buf) >= 10:
                        # Look for 0x66 header
                        header_idx = -1
                        for i in range(len(buf)):
                            if buf[i] == 0x66:
                                header_idx = i
                                break
                        if header_idx == -1:
                            buf.clear()
                            break
                        # Discard bytes before header
                        if header_idx > 0:
                            del buf[:header_idx]
                        # Try Format 2 (15 bytes): 0x66, 0x0F, ..., 0x99
                        if len(buf) >= 15 and buf[1] == 0x0F and buf[14] == 0x99:
                            self._parse_telemetry_format2(bytes(buf[:15]))
                            del buf[:15]
                            continue
                        # Try Format 1 (10 bytes): 0x66, voltage (not 0x0F), ...
                        if len(buf) >= 10 and buf[1] != 0x0F:
                            self._parse_telemetry_format1(bytes(buf[:10]))
                            del buf[:10]
                            continue
                        # Not enough data yet for either format; wait for more
                        if len(buf) < 15:
                            break
                        # Unrecognized — skip this header byte and try again
                        del buf[:1]
            except OSError as e:
                if platform.system() == "Windows" and getattr(e, 'winerror', None) == 10054:
                    pass
                else:
                    time.sleep(1)  # Back off on errors, don't spam status

    def _parse_telemetry_format1(self, data: bytes):
        '''Parse 10-byte telemetry packet (Format 1).'''
        try:
            # Verify checksum: XOR of bytes 1-8 should equal byte 9
            checksum = 0
            for i in range(1, 9):
                checksum ^= data[i]
            if checksum != data[9]:
                return

            voltage_raw = data[1]
            voltage = voltage_raw / 10.0
            battery_pct = int((voltage * 160.7142) - 517.8571)
            battery_pct = max(0, min(100, battery_pct))

            status_flags = data[2]
            # bit 0: take photo, bit 1: record (informational, not stored yet)

            self.telemetry.battery_voltage = voltage
            self.telemetry.battery_pct = battery_pct
            self.telemetry.last_update = time.time()
            if self.on_telemetry:
                self.on_telemetry(self.telemetry)
        except Exception:
            pass

    def _parse_telemetry_format2(self, data: bytes):
        '''Parse 15-byte telemetry packet (Format 2).'''
        try:
            # Verify checksum: XOR of bytes 2-12 should equal byte 13
            checksum = 0
            for i in range(2, 13):
                checksum ^= data[i]
            if checksum != data[13]:
                return

            battery_pct = data[3]
            battery_pct = max(0, min(100, battery_pct))

            status_flags = data[4]
            # bit 1: photo, bit 2: record (informational)

            self.telemetry.battery_pct = battery_pct
            self.telemetry.last_update = time.time()
            if self.on_telemetry:
                self.on_telemetry(self.telemetry)
        except Exception:
            pass

    def _video_loop(self):
        while not self._stop_event.is_set():
            try:
                if self.video_socket:
                    data, _ = self.video_socket.recvfrom(65536)
                    self.packets_received += 1
                    if len(data) > 4:
                        frame_id = data[0]
                        is_last = data[1]
                        packet_num = data[2]
                        payload = data[4:]

                        if frame_id not in self._video_frames: self._video_frames[frame_id] = {}
                        self._video_frames[frame_id][packet_num] = payload

                        if is_last == 1:
                            self._last_video_time = time.time()
                            self._reassemble_frame(frame_id)
            except OSError as e:
                if platform.system() == "Windows" and getattr(e, 'winerror', None) == 10054:
                    pass
                else:
                    time.sleep(1)  # Back off on errors, don't spam status

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
        _warned = False
        while not self._stop_event.is_set():
            if self.is_connected:
                no_telemetry = (self.telemetry.last_update > 0 and
                                time.time() - self.telemetry.last_update > 5.0)
                no_video = (self._last_video_time > 0 and
                            time.time() - self._last_video_time > 5.0)
                send_failing = self._send_errors > 10

                if (no_telemetry or no_video) and send_failing:
                    # Sustained connection loss — mark disconnected
                    self.is_connected = False
                    if self.on_status:
                        self.on_status("CONNECTION LOST")
                    _warned = False
                elif (no_telemetry or no_video) and not _warned:
                    if self.on_status:
                        self.on_status("CONNECTION UNSTABLE")
                    _warned = True
                elif not no_telemetry and not no_video:
                    _warned = False
            time.sleep(3.0)

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
    def takeoff(self):
        self.flight_state.takeoff = True
        self._command_timers['takeoff'] = time.time()

    def land(self):
        self.flight_state.landing = True
        self._command_timers['landing'] = time.time()

    def emergency_stop(self):
        self.flight_state.emergency_stop = True
        self._command_timers['emergency_stop'] = time.time()

    def calibrate(self):
        self.flight_state.calibration = True
        self._command_timers['calibration'] = time.time()

    def flip(self):
        self.flight_state.flip = True
        self._command_timers['flip'] = time.time()
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

    def switch_camera(self):
        self.send_cmd(b'\xcc\x5a\x01\x04\x02\x00\x07')
        self.send_cmd(b'\xcc\x5a\x02\x04\x02\x00\x04')
        self.send_cmd(b'\xcc\x5a\x03\x04\x02\x00\x05')

    def camera_rotate(self, on: bool = True):
        if on:
            self.send_cmd(b'\xcc\x5a\x01\x01\x02\x01\x03')
            self.send_cmd(b'\xcc\x5a\x02\x01\x02\x01\x00')
            self.send_cmd(b'\xcc\x5a\x03\x01\x02\x01\x01')
        else:
            self.send_cmd(b'\xcc\x5a\x01\x01\x02\x00\x02')
            self.send_cmd(b'\xcc\x5a\x02\x01\x02\x00\x01')
            self.send_cmd(b'\xcc\x5a\x03\x01\x02\x00\x00')

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

