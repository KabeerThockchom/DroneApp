# Pallton X80 DRONE APK — Complete Reverse-Engineering Documentation

**APK Package:** `com.guanxu.X80_Drone` v1.0.1  
**Developer:** Shantou Xintuo Intelligent Technology Co., Ltd. (branded as GuanXu / 冠旭)  
**SDK Provider:** Shenzhen NetOpSun Technology Co., Ltd. (深圳网日科技)  
**Date:** February 22, 2026  

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Device Selection & Initialization](#2-device-selection--initialization)
3. [XR872 Device Layer — The Core Protocol](#3-xr872-device-layer--the-core-protocol)
4. [Control Protocol — OpticalFlowDroneProtocol](#4-control-protocol--opticalflowdroneprotocol)
5. [Video Streaming — Frame Extraction](#5-video-streaming--frame-extraction)
6. [Command Communicator — Camera & Settings](#6-command-communicator--camera--settings)
7. [Telemetry — Receive Data Analyzer](#7-telemetry--receive-data-analyzer)
8. [Feature Implementations](#8-feature-implementations)
9. [Complete Packet Reference](#9-complete-packet-reference)
10. [Ideas for New Features](#10-ideas-for-new-features)

---

## 1. Architecture Overview

The APK is built on a modular SDK architecture by NetOpSun that supports multiple drone hardware platforms. The app selects the correct device driver at runtime based on the drone's WiFi subnet.

### Module Hierarchy

```
com.guanxu.X80_Drone          ← App shell (branding, R.java)
com.netopsun.drone             ← App logic (activities, UI, settings)
com.netopsun.xr872devices      ← XR872 device driver (YOUR DRONE)
com.netopsun.mr100devices      ← MR100 device driver (different drones)
com.netopsun.jllwdevices        ← JLLW device driver (different drones)
com.netopsun.fhdevices          ← FH device driver (different drones)
com.netopsun.rxtxprotocol       ← Flight control protocols
com.netopsun.deviceshub         ← Base interfaces & abstract classes
com.netopsun.ijkvideoview       ← Video player (modified IJKPlayer)
com.netopsun.gesturerecognition ← Hand gesture detection (OpenCV + Caffe)
com.netopsun.humanoidfollower   ← Human body tracking (OpenCV KCF)
com.netopsun.opencvapi          ← Native OpenCV JNI bridge
com.netopsun.live555            ← RTSP client (used by MR100, not XR872)
```

### Key Design Pattern

Every device driver implements three communicators:

| Communicator | Purpose | Transport |
|---|---|---|
| `RxTxCommunicator` | Flight control data (send) + telemetry (receive) | UDP port 7080 |
| `VideoCommunicator` | Video frame reception | UDP port 7070 |
| `CMDCommunicator` | Camera commands, settings, SSID/firmware queries | Piggybacks on RxTx socket |

The `RxTxProtocol` layer sits on top of `RxTxCommunicator` and handles the actual packet encoding/decoding. For the X80, this is `OpticalFlowDroneProtocol`.

---

## 2. Device Selection & Initialization

### Source: `DevicesUtil.java`

The app determines which device driver to use based on the local IP address assigned by the drone's DHCP server:

```java
public static Devices getDevices(Context context) {
    String localIpAddress = getLocalIpAddress(context);
    
    if (localIpAddress.contains("192.168.28.")) {
        // YOUR X80 DRONE
        currentConnectDevices = DevicesHub.open("xr872://");
    }
    else if (localIpAddress.contains("192.168.0.")) {
        currentConnectDevices = DevicesHub.open("mr100://");
    }
    else if (localIpAddress.contains("192.168.201.")) {
        currentConnectDevices = DevicesHub.open("jllw://");
    }
    else if (localIpAddress.contains("192.168.218.")) {
        currentConnectDevices = DevicesHub.open("fh://");
    }
    else if (localIpAddress.contains("192.168.208.")) {
        currentConnectDevices = DevicesHub.open("fh://");
    }
    else if (localIpAddress.contains("172.19.10.")) {
        currentConnectDevices = DevicesHub.open("mr100://");
    }
    // ...
}
```

**Critical finding:** The `192.168.28.x` subnet maps to the `XR872` device class. This is why our initial probe on ports 8800/50000 failed — those are MR100/JLLW ports.

### Protocol Selection

After the device is selected, the control protocol is chosen in `ControlActivity.onCreate()`:

```java
// For XR872 devices, the protocol is "OpticalFlowDroneProtocol"
String protocolName = "OpticalFlowDroneProtocol";
rxTxProtocol = RxTxProtocolFactory.createByName(protocolName, devices.getRxTxCommunicator());
```

The `RxTxProtocolFactory` supports 8 protocol variants:

| Protocol Name | Used By | Description |
|---|---|---|
| **OpticalFlowDroneProtocol** | **XR872 (X80)** | **20-byte packet, optical flow drones** |
| SimpleDroneProtocol | Various | Simpler packet format |
| BlueLightGPSProtocol | GPS drones | Includes GPS coordinates |
| HYBlueLightGPSProtocol | HY GPS drones | Variant of BlueLightGPS |
| SnapBlueLightGPSProtocol | Snap drones | Another GPS variant |
| LWGPSProtocol | LW GPS drones | LongWei GPS protocol |
| DFSGPSProtocol | DFS drones | DFS-specific GPS |
| F200GPSProtocol | F200 drones | F200-specific GPS |

---

## 3. XR872 Device Layer — The Core Protocol

### Source: `XR872Devices.java`

The XR872 device class defines the core network parameters:

```java
public class XR872Devices extends Devices {
    private String devicesIP = "192.168.28.1";   // Drone IP
    private int videoPort = 7070;                 // Video receive port
    private final int rxtxPort = 7080;            // Control/telemetry port
    
    // Device flag used for analytics/logging
    public String getDevicesFlag() { return "w37"; }
}
```

### Connection Sequence

The full connection sequence, in order:

1. **RxTx Connect** → Opens UDP socket, binds to port 7080, starts receive thread
2. **CMD Connect** → Reuses the RxTx socket, sets up data filter for SSID/firmware responses
3. **Heartbeat Start** → Sends `0x00` byte every 1000ms to keep connection alive
4. **Control Data Start** → Sends 20-byte control packets every 140ms
5. **Video Connect** → Opens separate UDP socket on port 7070, sends video start command to port 7080
6. **Video Receive** → Receives 1472-byte UDP packets, reassembles into JPEG frames

### Source: `XR872RxTxCommunicator.java`

The RxTx communicator handles the UDP socket for flight control:

```java
public int connectInternal() {
    DatagramSocket socket = new DatagramSocket(null);
    socket.setReuseAddress(true);
    socket.bind(new InetSocketAddress(xr872Devices.getRxtxPort())); // Bind to 7080
    inetAddress = InetAddress.getByName(xr872Devices.getDevicesIP()); // 192.168.28.1
    
    // Start receive thread
    // Receive buffer: 2048 bytes
    // Receive loop: reads packets, passes to onReceiveCallback
    
    // Start heartbeat: sends 0x00 every 1000ms
    startSendHeartBeatPackage(1000, new byte[]{0});
}
```

**Key detail:** The socket is bound to local port 7080 and sends to remote port 7080. Both control packets and heartbeats go to the same remote port.

### Reconnection Logic

The communicator has automatic reconnection:

- Checks every 1 second if data has been received
- If no data received for `revTimeoutSecond` seconds (configurable), triggers reconnect
- If send fails for 3+ seconds, triggers reconnect
- If receive stops for 3+ seconds after previously working, triggers reconnect

---

## 4. Control Protocol — OpticalFlowDroneProtocol

### Source: `OpticalFlowDroneProtocol.java`

This is the most critical class — it defines the exact 20-byte packet that controls the drone.

### Packet Structure (20 bytes)

| Byte | Name | Value/Formula | Description |
|---|---|---|---|
| 0 | Header | `0x66` (102) | Fixed header byte |
| 1 | Length | `0x14` (20) | Packet length |
| 2 | Roll | `(roll/100 * 128) + 128` | Left/Right strafe. Center=128, Left=0, Right=255 |
| 3 | Pitch | `(pitch/100 * 128) + 128` | Forward/Backward. Center=128, Forward=0, Back=255 |
| 4 | Throttle | `(accelerator/100 * 128) + 128` | Up/Down. Center=128, Down=0, Up=255 |
| 5 | Yaw | `(yaw/100 * 128) + 128` | Spin Left/Right. Center=128, Left=0, Right=255 |
| 6 | Command Flags | Bitfield (see below) | Action commands |
| 7 | Mode Flags | Bitfield (see below) | Mode settings |
| 8 | Follow Mode X | `0x00` or `0xFF` | Follow mode enable (X) |
| 9 | Follow Mode Y | `0x00` or `0xFF` | Follow mode enable (Y) |
| 10 | Follow Dir Y | `(followDirY/100 * 128) + 128` | Follow mode direction rocker Y |
| 11 | Follow Accel X | `(followAccelX/100 * 128) + 128` | Follow mode accelerator rocker X |
| 12 | Follow Accel Y | `(followAccelY/100 * 128) + 128` | Follow mode accelerator rocker Y |
| 13 | Follow Dir X | `(followDirX/100 * 128) + 128` | Follow mode direction rocker X |
| 14-17 | Custom | `0x00` | Reserved for `onCustomControlData` callback |
| 18 | Checksum | XOR of bytes 2-17 | XOR checksum |
| 19 | Tail | `0x99` (-103) | Fixed tail byte |

### Stick Value Encoding

All stick values use the same formula:

```
encoded = (percentage / 100.0) * 128 + 128
```

Where `percentage` ranges from `-99.99` to `+99.99`:

| Stick Position | Percentage | Encoded Value |
|---|---|---|
| Full negative | -99.99 | 0 (0x00) |
| Center/neutral | 0.0 | 128 (0x80) |
| Full positive | +99.99 | 255 (0xFF) |

### Command Flags (Byte 6) — Bitfield

| Bit | Mask | Name | Description |
|---|---|---|---|
| 0 | `0x01` | Takeoff/Land | Set to 1 for takeoff OR landing (context-dependent) |
| 1 | `0x02` | Emergency Stop | Immediately kills all motors |
| 2 | `0x04` | Calibration | Gyroscope calibration (drone must be on flat surface) |
| 3 | `0x08` | 360 Flip | Triggers a 360-degree flip/roll |
| 4 | `0x10` | Light Toggle | Toggles the LED lights on/off |

**Important timing behavior:** Each command flag is set to 1 and then automatically reset to 0 after 1 second via an RxJava timer. This means you send the command for ~7 packets (1000ms / 140ms interval) and then it auto-clears.

### Mode Flags (Byte 7) — Bitfield

| Bit | Mask | Name | Description |
|---|---|---|---|
| 0 | `0x01` | Headless Mode | When set, forward is always away from pilot regardless of drone orientation |
| 1 | `0x02` | Always Set | This bit is always OR'd in — always 1 |

So byte 7 is either `0x02` (headless off) or `0x03` (headless on).

### Send Timing

The control packet is sent every **140 milliseconds** via `startAutomaticTimingSend(140)`:

```java
// In ControlActivity.checkIfNeedSendControlData():
rxTxProtocol.startAutomaticTimingSend(140);
```

This means the drone expects ~7 packets per second. If it stops receiving packets, it will hover/auto-land.

### Heartbeat

In addition to control packets, a separate heartbeat is sent:

```java
devices.getRxTxCommunicator().startSendHeartBeatPackage(1000, new byte[]{0});
```

This sends a single `0x00` byte to port 7080 every 1000ms.

---

## 5. Video Streaming — Frame Extraction

### Source: `XR872VideoCommunicator.java` + `XR872VideoFrameDataExtractor.java`

### Video Start Command

To start the video stream, the app sends a 7-byte packet to port 7080:

```java
// Video START command
byte[] videoStart = {0xCC, 0x5A, 0x01, 0x82, 0x02, 0x36, 0xB7};
//                   -52   90    1    -126   2     54   -73  (signed)

socket.send(new DatagramPacket(videoStart, 7, inetAddress, devices.getRxtxPort()));
```

### Video Stop Command

When disconnecting, a stop command is sent:

```java
// Video STOP command
byte[] videoStop = {0xCC, 0x5A, 0x01, 0x82, 0x02, 0x37, 0xB6};
//                  -52   90    1    -126   2     55   -74  (signed)
```

### Video Packet Format

Video data arrives as UDP packets on port 7070. Each packet is up to **1472 bytes** with a 4-byte header:

| Byte | Name | Description |
|---|---|---|
| 0 | Frame ID | Identifies which frame this packet belongs to (0-255, wraps) |
| 1 | Last Packet Flag | `0x01` if this is the last packet of the current frame, `0x00` otherwise |
| 2 | Packet Number | Sequential packet number within the frame (1-based, wraps at 256) |
| 3 | Reserved | Unused |
| 4+ | Payload | JPEG data (up to 1468 bytes) |

### Frame Reassembly Algorithm

```python
# Pseudocode from XR872VideoFrameDataExtractor
def on_video_data(packet, length):
    is_last_packet = (packet[1] == 1)
    
    # Only process standard-size packets or last packets
    if length != 1472 and not is_last_packet:
        return
    
    frame_id = packet[0] & 0xFF
    packet_num = packet[2] & 0xFF
    
    if packet_num == 1:
        # First packet of new frame
        frame_buffer_pos = 0
        current_frame_id = frame_id
        last_packet_num = 1
    elif (last_packet_num + 1) % 256 != packet_num:
        # Out of sequence — drop
        return
    
    last_packet_num = packet_num
    
    if current_frame_id != frame_id:
        # Frame ID mismatch — drop
        return
    
    # Copy payload (skip 4-byte header)
    payload_len = length - 4
    frame_buffer[frame_buffer_pos : frame_buffer_pos + payload_len] = packet[4:]
    frame_buffer_pos += payload_len
    
    # Check if frame is complete
    if is_last_packet and frame_buffer_pos >= 2:
        # Verify JPEG markers: starts with FF D8, ends with FF D9
        if (frame_buffer[0] == 0xFF and frame_buffer[1] == 0xD8 and
            frame_buffer[-2] == 0xFF and frame_buffer[-1] == 0xD9):
            # Valid JPEG frame!
            emit_frame(frame_buffer, frame_buffer_pos)
```

### Video Format Details

- **Format:** MJPEG (Motion JPEG)
- **Resolution:** 1920x1080 (when `is1080p` setting is true) or 800x600
- **Frame buffer:** 300,000 bytes max per frame (~300KB)
- **UDP packet size:** 1472 bytes (standard MTU minus headers)
- **Typical frame size:** ~30-35KB (about 22-24 packets per frame)
- **Frame rate:** ~8 FPS (observed in probe test)
- **Double buffering:** Two frame buffers are used in a producer-consumer pattern

---

## 6. Command Communicator — Camera & Settings

### Source: `XR872CMDCommunicator.java`

The CMD communicator sends camera control commands by piggybacking on the RxTx UDP socket. All commands use a 7-byte packet format.

### Command Packet Format

```
[0xCC] [0x5A] [sequence] [command] [0x02] [param] [checksum]
```

| Byte | Name | Description |
|---|---|---|
| 0 | Header 1 | Always `0xCC` (-52 signed) |
| 1 | Header 2 | Always `0x5A` (90 signed) |
| 2 | Sequence | Packet sequence: 1, 2, or 3 (commands are sent in triples) |
| 3 | Command ID | The command type |
| 4 | Fixed | Always `0x02` |
| 5 | Parameter | Command-specific parameter |
| 6 | Checksum | XOR checksum of bytes 2 through (length-2) |

### Camera Rotation Commands

Each rotation command is sent as a **triple** (3 packets in sequence):

**Rotate Video ON (flip 180°):**
```
CC 5A 01 01 02 01 03
CC 5A 02 01 02 01 00
CC 5A 03 01 02 01 01
```

**Rotate Video OFF (normal):**
```
CC 5A 01 01 02 00 02
CC 5A 02 01 02 00 01
CC 5A 03 01 02 00 00
```

### Switch Camera Command

Switches between front and bottom camera:

```
CC 5A 01 04 02 00 07
CC 5A 02 04 02 00 04
CC 5A 03 04 02 00 05
```

### Video Start/Stop Commands

```
Video START: CC 5A 01 82 02 36 B7
Video STOP:  CC 5A 01 82 02 37 B6
```

### Get SSID Response

The drone responds with its SSID when queried. Response format:

```
CC 5A [seq] A2 [length] [SSID bytes...] [checksum]
```

Where `0xA2` (-94 signed) is the SSID response command ID. The SSID string starts at byte 5 and has length `(byte[4] & 0xFF) - 1`.

### Get Firmware Version Response

```
CC 5A [seq] 30 [length] [version bytes...] [checksum]
```

Where `0x30` (48) is the firmware version response command ID.

### Checksum Calculation

All checksums use XOR:

```python
def get_checksum(data, start, end):
    result = data[start]
    for i in range(start + 1, end + 1):
        result ^= data[i]
    return result
```

### Remote CMD Listener

The drone can send commands back to the app (e.g., from a physical remote control button). These are detected by scanning the received data stream for 7-byte patterns matching `CC 5A xx xx xx xx xx`.

The `onRemoteCMD` method processes these and can trigger:
- Take photo
- Start/stop recording
- Other remote-initiated actions

---

## 7. Telemetry — Receive Data Analyzer

### Source: `OpticalFlowReceiveDataAnalyzer.java`

The drone sends telemetry data back on the same UDP port 7080. The analyzer uses a sliding window approach — it maintains a 15-byte buffer and checks for valid packets on every received byte.

### Telemetry Packet Format 1 (Short — 10 bytes)

```
[0x66] [voltage] [...6 bytes...] [checksum]
```

| Byte (from end) | Name | Description |
|---|---|---|
| -10 | Header | `0x66` (102) — same as control packet header |
| -9 | Voltage | Raw voltage * 10 (e.g., 37 = 3.7V) — NOT `0x0F` |
| -8 | Status Flags | Bit 0: take photo CMD, Bit 1: record CMD |
| -7 to -2 | Reserved | Additional telemetry data |
| -1 | Checksum | XOR of bytes -9 to -2 |

**Battery Level Calculation:**

```python
voltage = (raw_byte & 0xFF) / 10.0  # e.g., 37 → 3.7V
battery_percent = int((voltage * 160.7142) - 517.8571)
battery_percent = max(0, min(100, battery_percent))
```

This maps approximately:
- 3.2V → 0% (empty)
- 3.7V → 77% 
- 4.2V → 100% (full)

### Telemetry Packet Format 2 (Long — 15 bytes)

```
[0x66] [0x0F] [...11 bytes...] [checksum] [0x99]
```

| Byte (from end) | Name | Description |
|---|---|---|
| -15 | Header | `0x66` (102) |
| -14 | Type ID | `0x0F` (15) — identifies this as the long format |
| -12 | Battery % | Direct battery percentage (0-100) |
| -11 | Status Flags | Bit 1: take photo CMD, Bit 2: record CMD |
| -2 | Checksum | XOR of bytes -13 to -3 |
| -1 | Tail | `0x99` (-103) |

### Remote Photo/Record Trigger

When the drone's physical button is pressed:
- **Take Photo:** Status bit is set, app detects the transition (edge-triggered), requires 2 consecutive detections within 1 second
- **Record Toggle:** Status bit is set, app detects transition, requires 2 consecutive detections within 2 seconds, toggles start/stop

---

## 8. Feature Implementations

### 8.1 Gesture Recognition

**Source:** `GestureReconizer.java`, `GestureReconizerHelper.java`

Uses a **Caffe neural network** (via OpenCV DNN) for hand gesture detection:

- **Model:** `5objs_img17219_iter60000_batchsize8_lr0.005_negpos5.0_1.caffemodel`
- **Config:** `5objs.prototxt`
- **Input:** 640x480 video frames from the drone camera
- **Confidence threshold:** 0.2 (20%)
- **Restart delay:** 2500ms between detections
- **Animation delay:** 500ms

**Detected gestures and actions:**
- **Open palm** → Take photo
- **Victory/peace sign** → Start/stop video recording

**How it works:**
1. Video frames are captured from the IJKVideoView render pipeline
2. Frames are mirrored and rotated (-180°) to match the model's expected orientation
3. The Caffe model runs inference on a background thread (priority 3 = low)
4. Results are dispatched to the main thread to trigger photo/record

**To replicate in Python:** You would need to use OpenCV's DNN module with a similar hand gesture model. MediaPipe Hands is a modern alternative that's easier to use.

### 8.2 Human Body Following (Humanoid Follower)

**Source:** `HumanoidFollowerHelper.java`, `HumanBodyReconizer.java`, `KcfDroneController.java`

This is a sophisticated 3-stage tracking system:

**Stage 1: Human Body Detection**
- Uses OpenCV's built-in human body detector (HOG + SVM or DNN-based)
- Runs on 320x240 frames for performance
- Confidence threshold: 0.72 (72%)
- Draws bounding boxes around detected humans on the `HumanoidFollowerView`

**Stage 2: Target Selection (KCF Init)**
- User taps on a detected human to select them as the tracking target
- Initializes a **KCF (Kernelized Correlation Filter) tracker** via OpenCV
- KCF is fast and works well for real-time tracking

**Stage 3: Active Tracking (KCF Update)**
- KCF tracker updates every frame
- Confidence threshold: 0.07 (7%) — very permissive to avoid losing target
- Every 90 frames, re-verifies the tracked region contains a human (anti-drift)
- If confidence drops below threshold OR bounding box becomes too large (>60% of frame) OR goes off-screen, tracking is lost

**Drone Control During Tracking (`KcfDroneController`):**

The controller translates the tracked bounding box into yaw and pitch commands:

```
Rotation (Yaw):
  - Target center X vs frame center (0.5)
  - If offset > centerLineAllowableVariation (0.2): rotate toward target
  - Speed: rotationAxisSpeed (20)
  - Duration: proportional to offset (offset * 3000ms)

Forward/Backward (Pitch):
  - Target bounding box width vs referenceRectSize (0.3)
  - If too small: fly forward (target is far)
  - If too large: fly backward (target is close)
  - Allowable variation: 0.07
  - Speed: forwardAndBackwardSpeed (25)
  - Duration: proportional to size difference (diff * 12000ms)

Update rate: every 25ms (40 Hz)
```

**To replicate in Python:** Use OpenCV's `cv2.TrackerKCF_create()` for KCF tracking, and MediaPipe or YOLO for human detection. The drone control logic from `KcfDroneController` can be directly ported.

### 8.3 Trajectory Drawing (Sketchpad)

**Source:** `DroneTrajectorySketchpad` (in `com.guanxukeji.drone_rocker`)

Allows the user to draw a flight path on screen, which the drone follows. The path is drawn as a series of touch points, converted to direction/speed commands.

### 8.4 Sensor Control (Accelerometer)

**Source:** `ControlActivity.onCheckedChanged()` → `control_bar_sensor_control`

When enabled, the phone's accelerometer controls the drone's direction:
- Tilt phone forward → drone flies forward
- Tilt phone left → drone strafes left
- The virtual joystick becomes locked and shows a sensor icon

### 8.5 360° Flip

**Source:** `RxTxProtocol.setTurnOver360()`

Triggers a 360-degree flip by setting bit 3 (mask `0x08`) in the command flags byte. The command is sent for 1 second then auto-clears.

### 8.6 Speed Control

**Source:** `ControlActivity.switchSpeed()`

Two speed levels (0 and 1). The speed state is cycled on button press. The `speedLevel` is set on the protocol via `rxTxProtocol.setSpeedLevel()`.

### 8.7 Video Filters & Effects

**Source:** `FilterChoosePopupWindows`, `ParticleEffectsChoosePopupWindows`

The app applies GPU-based image filters to the video feed using GPUImage:
- Various color filters (sepia, grayscale, etc.)
- Particle effects overlay
- These are purely client-side — they don't affect the drone's camera

### 8.8 VR Mode

**Source:** `ControlActivity.onCheckedChanged()` → `control_bar_vr_mode`

Splits the video feed into a side-by-side stereoscopic view for VR headsets. This is a client-side rendering feature using `IjkVideoView.setVRMode()`.

### 8.9 Photo Capture

**Source:** `ControlActivity.takePhoto()`

Photos are captured client-side from the video feed:
- For XR872 devices: captures at **1920x1080** resolution
- Saved as JPEG with 90% quality
- File naming: `pic_YYYYMMDD_HHmmss_RANDOM.jpg`
- Saved to `X80/Photo/` directory

### 8.10 Video Recording

**Source:** `ControlActivity.toggleRecord()`

Video is recorded client-side using `EncodeBitmapAndMux2Mp4`:
- Captures frames from the video renderer
- Encodes to MP4 using Android's MediaCodec
- Supports background music overlay (BGM mode)
- File naming: `video_YYYYMMDD_HHmmss_RANDOM.mp4`
- Saved to `X80/Video/` directory

### 8.11 Camera Tilt Control

**Source:** `ControlActivity` → `controlBarTopmv` / `controlBarBottommv`

Touch-and-hold buttons that adjust the camera tilt:
- Hold "up" button → `isTouchCameraUp = true` → camera tilts up
- Hold "down" button → `isTouchCameraDown = true` → camera tilts down
- Release → stops tilting

The camera position is sent via `rxTxProtocol.setCameraPositionValue()`.

### 8.12 Right-Hand / Left-Hand Mode

**Source:** `Constants.getIsRightHandMode()`

Swaps the left and right virtual joysticks for left-handed pilots. Stored in SharedPreferences.

### 8.13 Remote Photo from Drone

**Source:** `ControlActivity.receivePhoto()`

Some drones can capture photos on their internal SD card and transmit them back to the app. The `CMDCommunicator.sendReceiveRemotePhotoCMD()` triggers this. For MR100 devices, photos are resized to 4096x2160. This feature may or may not be active on the XR872.

---

## 9. Complete Packet Reference

### Control Packet (Sent every 140ms to port 7080)

```
Offset  Hex    Description
------  ----   -----------
0       66     Header
1       14     Length (20)
2       80     Roll (128 = center)
3       80     Pitch (128 = center)
4       80     Throttle (128 = center)
5       80     Yaw (128 = center)
6       00     Command flags (takeoff|estop|cal|flip|light)
7       02     Mode flags (headless | 0x02)
8       00     Follow mode X enable
9       00     Follow mode Y enable
10      80     Follow direction Y
11      80     Follow accelerator X
12      80     Follow accelerator Y
13      80     Follow direction X
14      00     Custom data 1
15      00     Custom data 2
16      00     Custom data 3
17      00     Custom data 4
18      XX     Checksum (XOR of bytes 2-17)
19      99     Tail
```

### Heartbeat (Sent every 1000ms to port 7080)

```
00
```

### Video Start (Sent once to port 7080)

```
CC 5A 01 82 02 36 B7
```

### Video Stop (Sent once to port 7080)

```
CC 5A 01 82 02 37 B6
```

### Camera Rotate ON (3 packets to port 7080)

```
CC 5A 01 01 02 01 03
CC 5A 02 01 02 01 00
CC 5A 03 01 02 01 01
```

### Camera Rotate OFF (3 packets to port 7080)

```
CC 5A 01 01 02 00 02
CC 5A 02 01 02 00 01
CC 5A 03 01 02 00 00
```

### Switch Camera (3 packets to port 7080)

```
CC 5A 01 04 02 00 07
CC 5A 02 04 02 00 04
CC 5A 03 04 02 00 05
```

### Takeoff Example

```
66 14 80 80 80 80 01 02 00 00 80 80 80 80 00 00 00 00 [checksum] 99
                       ^^ takeoff bit set
```

### Emergency Stop Example

```
66 14 80 80 80 80 02 02 00 00 80 80 80 80 00 00 00 00 [checksum] 99
                       ^^ emergency stop bit set
```

### Calibration Example

```
66 14 80 80 80 80 04 02 00 00 80 80 80 80 00 00 00 00 [checksum] 99
                       ^^ calibration bit set
```

### 360 Flip Example

```
66 14 80 80 80 80 08 02 00 00 80 80 80 80 00 00 00 00 [checksum] 99
                       ^^ flip bit set
```

---

## 10. Ideas for New Features

Based on the APK analysis, here are features you can build that go beyond what the stock app offers:

### Already Possible (Protocol Supports It)

| Feature | How | Notes |
|---|---|---|
| **Flight recording/playback** | Log all control packets with timestamps, replay them | Record a flight, replay it exactly |
| **Programmable waypoints** | Send timed sequences of pitch/yaw/throttle | No GPS, but timed maneuvers work |
| **Custom autopilot patterns** | Circle, figure-8, orbit via calculated stick inputs | Already in our app |
| **Keyboard macros** | Map complex maneuvers to single keys | E.g., "barrel roll" = flip + yaw |
| **Dual camera view** | Switch cameras rapidly for picture-in-picture | Send switch command, capture frame, switch back |
| **Panorama capture** | Slow yaw rotation + periodic photo capture | Stitch with OpenCV |
| **Timelapse** | Periodic photo capture at configurable intervals | Easy to implement |
| **Follow mode** | Bytes 8-13 in the control packet | The protocol has built-in follow mode support |

### New Features (Client-Side Processing)

| Feature | How | Difficulty |
|---|---|---|
| **Object tracking** | OpenCV KCF/CSRT tracker on video frames → yaw/pitch control | Medium — port the KcfDroneController logic |
| **Hand gesture control** | MediaPipe Hands → map gestures to commands | Medium |
| **Face tracking** | OpenCV Haar cascades or MediaPipe Face → auto-center on face | Easy |
| **Line following** | OpenCV edge detection on video → auto-pilot along lines | Medium |
| **Color tracking** | HSV color filtering → follow colored objects | Easy |
| **Optical flow analysis** | OpenCV calcOpticalFlowFarneback → motion detection/stabilization | Medium |
| **Video stabilization** | Client-side frame alignment using feature matching | Hard |
| **AR overlay** | Draw 3D objects on the video feed | Medium (with OpenGL) |
| **Collision warning** | Analyze video for approaching obstacles | Hard (needs depth estimation) |
| **Map/minimap** | Track drone position via dead reckoning from control inputs | Medium |
| **Voice control** | Speech-to-text → command mapping | Easy (use Whisper or similar) |
| **Multi-drone** | Connect to multiple drones (different SSIDs) | Hard (need multiple WiFi adapters) |
| **FPV goggles** | Split-screen VR mode (already in stock app) | Easy — render two viewports |
| **Flight simulator** | Offline mode with simulated physics | Medium |

### Protocol Extensions to Investigate

| Area | What to Try | Why |
|---|---|---|
| **Resolution switching** | Send `is1080p` equivalent command | The app has a 1080p toggle in settings |
| **SD card access** | `getRemoteSDCardStatus` command | The app queries SD card status every 5 seconds |
| **Firmware query** | Send SSID/firmware request packets | Get device info programmatically |
| **Camera position** | `setCameraPositionValue` in control packet | May control camera tilt angle |
| **Custom bytes 14-17** | Experiment with non-zero values | The `onCustomControlData` callback suggests these are extensible |

---

## Appendix: File Reference

| File | Lines | Purpose |
|---|---|---|
| `XR872Devices.java` | 126 | Device class, IP/port config, open/close |
| `XR872CMDCommunicator.java` | 283 | Camera commands, SSID/firmware queries |
| `XR872RxTxCommunicator.java` | 201 | UDP socket, send/receive, heartbeat |
| `XR872VideoCommunicator.java` | 213 | Video socket, frame buffering |
| `XR872VideoFrameDataExtractor.java` | 70 | JPEG frame reassembly from UDP packets |
| `OpticalFlowDroneProtocol.java` | 139 | 20-byte control packet encoding |
| `OpticalFlowReceiveDataAnalyzer.java` | 262 | Telemetry parsing, battery, remote CMDs |
| `RxTxProtocol.java` | 729 | Base protocol class, all settable fields |
| `RxTxProtocolFactory.java` | 90 | Protocol selection by name |
| `ControlActivity.java` | 1634 | Main UI, all feature orchestration |
| `Constants.java` | 127 | Settings, paths, preferences |
| `DevicesUtil.java` | 125 | Device selection by IP subnet |
| `GestureReconizer.java` | 108 | Caffe DNN gesture detection |
| `HumanoidFollowerHelper.java` | 268 | Human body detection + KCF tracking |
| `KcfDroneController.java` | 114 | Tracking → drone control translation |
| `HumanBodyReconizer.java` | 78 | OpenCV human body detector |

---

*This document was generated by reverse-engineering the X80 DRONE APK v1.0.1 using JADX decompiler. All byte values, packet formats, and algorithms were extracted directly from the decompiled Java source code.*
