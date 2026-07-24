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
├── config/
│   ├── __init__.py
│   └── settings.py              # All tunable params (dataclass + YAML/argparse)
├── src/
│   ├── main.py                  # Entry point, orchestrates full pipeline
│   ├── camera/
│   │   ├── xreal_eye.py         # Xreal One Pro Eye camera capture
│   │   └── webcam_fallback.py   # USB webcam fallback
│   ├── tracking/
│   │   ├── hand_tracker.py      # MediaPipe HandLandmarker
│   │   └── gesture.py           # MediaPipe GestureRecognizer (clutch)
│   ├── mapping/
│   │   ├── hand_to_ee.py        # Hand landmarks → EE target (x,y,z,roll,gripper)
│   │   ├── clutch.py            # Fist engage/disengage with delta offset
│   │   └── filters.py           # EMA, deadzone, rate limiter
│   ├── ik/
│   │   └── solver.py            # ikpy IK solver using SO-101 URDF
│   ├── robot/
│   │   ├── arm_controller.py    # LeRobot SO-101 send_action / get_observation
│   │   └── safety.py            # Joint clamping + stall detection
│   ├── overlay/
│   │   └── status_display.py    # OpenCV status overlay for glasses
│   └── linq/                    # Chat control: message → LangGraph → actions
│       ├── run.py               # Entry point (python -m src.linq.run)
│       ├── graph.py             # LangGraph wiring
│       ├── actions.py           # Action vocabulary + JSON schema
│       ├── nodes/               # understand → validate → execute → respond
│       ├── executor.py          # Actions → IK → safety → arm
│       └── channels/            # Inbound transports (CLI today)
├── scripts/
│   ├── calibrate.sh             # lerobot-calibrate wrapper
│   ├── download_models.sh       # Download MediaPipe model files
│   └── test_camera.py           # Quick camera test
├── models/                      # MediaPipe .task files (downloaded)
└── requirements.txt
```

## Setup

### 1. Install dependencies

```bash
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

Required before first use:

```bash
bash scripts/calibrate.sh
# or directly:
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/ttyACM0 --robot.id=follower
```

### 4. Xreal One Pro setup

- Install Nebula beta firmware on the glasses
- Enable Spatial Anchor mode
- Connect via USB-C -- the Eye camera appears as a device on NCM virtual Ethernet
- See: [Grayscale Feed community guide](https://github.com/Aloim/Grayscale-Feed-Xreal-One-Pro-Eye-Windows-Nebula-Beta-needed-)

## Usage

### Run the teleop pipeline

```bash
python -m src.main
```

### Common options

```bash
# Use a regular webcam instead of Xreal Eye camera
python -m src.main --use-webcam

# Specify robot port
python -m src.main --port /dev/ttyACM1

# Set target FPS
python -m src.main --fps 20

# Load from YAML config
python -m src.main --config config/my_settings.yaml
```

### Test camera only

```bash
python scripts/test_camera.py
python scripts/test_camera.py --webcam
```

Press **ESC** to quit.

## Messaging Linq (chat control)

A second control path, independent of hand tracking: message the arm in plain
language and a LangGraph pipeline turns it into a validated action plan.

```bash
export ANTHROPIC_API_KEY=...   # or: ant auth login
python -m src.linq.run         # dry-run — logs actions, arm never moves
python -m src.linq.run --live --port /dev/ttyACM0
```

```
you>  pick up the cube and lift it 10cm
linq> Reaching for it. [dry-run]
```

`understand` (Claude) → `validate` (envelope + limits) → `execute` (IK → safety
→ arm) → `respond`. Validation is deterministic and fails closed, so a bad plan
never reaches the motors. See [src/linq/README.md](src/linq/README.md).

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
