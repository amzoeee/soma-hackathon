# Xreal One Pro Hand-Tracking Teleop for LeRobot SO-101

Control a LeRobot SO-101 robot arm (5-DOF + gripper) using hand tracking from the Xreal One Pro Eye camera, with a live status overlay displayed on the glasses.

## Hardware

- **Xreal One Pro** + Eye attachment (monocular grayscale camera, USB-C to host PC)
- **LeRobot SO-101** follower arm (Feetech STS3215 servos, USB serial to host PC)
- Single host PC drives both devices

## Architecture

```
Xreal Eye Camera ──► Hand Tracking (MediaPipe) ──► Hand-to-EE Mapping ──► IK Solver (ikpy) ──► Robot Command
       │                     │                            │                                         │
       │              Gesture Recognition                Clutch Logic                        Safety Clamp
       │              (fist = clutch)              (freeze/resume delta)              (max_relative_target)
       │                                                                                         │
       └──────────────────── Status Overlay (OpenCV window on glasses) ◄── Servo Observations ◄──┘
```

### Pipeline

1. **Camera feed** -- Eye camera streams grayscale frames to host PC via USB-C NCM virtual Ethernet
2. **Hand tracking** -- MediaPipe HandLandmarker extracts 21 landmarks per hand
3. **Gesture recognition** -- MediaPipe GestureRecognizer detects fist (clutch)
4. **Mapping** -- Hand X/Y/Z scaled into robot workspace; wrist roll from landmark geometry; pinch distance to gripper
5. **Clutch** -- Fist freezes arm target; release resumes with delta offset (avoids running out of reach)
6. **IK** -- ikpy solves shoulder_pan, shoulder_lift, elbow_flex, wrist_flex from (x,y,z) target
7. **Safety** -- Per-step joint movement clamped; stall detection from commanded vs actual divergence
8. **Command** -- 6-key action dict sent to robot via LeRobot SDK
9. **Overlay** -- Status window renders on glasses (standard DisplayPort monitor)

## Project Structure

```
soma-hackathon/
├── agent/                       # Linq agent / LLM robot demo (Zoe)
├── robot/                       # Hand-tracking teleop pipeline (this package)
│   ├── config/
│   │   ├── settings.py          # Tunable params
│   │   └── so101.urdf           # IK URDF
│   ├── src/
│   │   ├── main.py              # Full pipeline entry
│   │   ├── camera/
│   │   │   ├── xreal_eye.py     # Aloim TCP grayscale Eye stream (NOT VideoCapture)
│   │   │   └── webcam_fallback.py
│   │   ├── tracking/
│   │   │   ├── enhance.py       # CLAHE/gamma for grayscale MediaPipe
│   │   │   ├── hand_tracker.py
│   │   │   └── gesture.py       # Closed_Fist = clutch
│   │   ├── mapping/             # hand → EE + clutch
│   │   ├── ik/                  # ikpy, degrees out
│   │   ├── robot/               # LeRobot SO-101 wrapper
│   │   └── overlay/             # glasses HUD
│   ├── scripts/
│   │   ├── test_hand_tracking.py  # landmark + pos/roll/pinch/fist view
│   │   ├── test_camera.py
│   │   ├── calibrate.sh
│   │   └── download_models.sh
│   ├── models/                  # MediaPipe .task files
│   └── requirements.txt
└── docs/
```

## Setup

### 1. Install dependencies

```bash
cd robot
pip install -r requirements.txt
```

LeRobot must be installed separately (from source or pip):
```bash
pip install lerobot
```

### 2. Download MediaPipe models

```bash
bash scripts/download_models.sh
```

This downloads `hand_landmarker.task` and `gesture_recognizer.task` into `models/`.

### 3. Calibrate the SO-101

Required before first use (Windows example — change port on Linux):

```bash
lerobot-calibrate --robot.type=so101_follower --robot.port=COM5 --robot.id=follower
```

### 4. Xreal One Pro setup

- Install Nebula beta firmware on the glasses
- Enable Spatial Anchor mode (resets after glasses restart — stream is silent without it)
- Connect via USB-C — Eye stream is TCP on `169.254.2.1:52997`, not a UVC webcam
- See: [Grayscale Feed community guide](https://github.com/Aloim/Grayscale-Feed-Xreal-One-Pro-Eye-Windows-Nebula-Beta-needed-)

## Usage

### Test hand tracking first (recommended)

```bash
cd robot
python scripts/test_hand_tracking.py          # Eye grayscale + landmarks
python scripts/test_hand_tracking.py --webcam # USB fallback
```

Shows position, wrist roll, pinch, and fist/clutch on screen. Press **q** to quit.

### Run the full teleop pipeline

```bash
cd robot
python -m src.main
```

### Common options

```bash
# Use a regular webcam instead of Xreal Eye camera
python -m src.main --use-webcam

# Specify robot port (Windows)
python -m src.main --port COM5

# Set target FPS
python -m src.main --fps 20

# Load from YAML config
python -m src.main --config config/my_settings.yaml
```

## Controls

| Gesture | Action |
|---|---|
| Open hand | Track hand position → move arm |
| Pinch (thumb + index) | Close gripper proportionally |
| Closed fist | **Clutch** -- freeze arm, reposition hand freely |
| Release fist | Resume tracking relative to current arm position |

## Known Limitations

- **Eye camera stream is beta/reverse-engineered** -- may produce black frames on first connect or have USB re-enumeration issues. Use `--use-webcam` as a fallback.
- **MediaPipe Z depth is monocular** -- treat as coarse. The system relies primarily on X/Y + pinch.
- **Grayscale input** may slightly reduce MediaPipe detection confidence vs. RGB.
- The SO-101 URDF is needed for IK -- place it at `config/so101.urdf` (extract from LeRobot or create from spec).
