# armteleop

Xreal One Pro hand-tracking teleop for LeRobot SO-101 (Zoe's architecture).

Pipeline: Eye camera (NCM TCP stream) → MediaPipe Gesture Recognizer (21
landmarks + fist clutch) → relative mapping → ikpy IK (SO-101 URDF, seeded
from servo encoders) → `SO101Follower.send_action`. Status HUD renders to the
glasses (plain DP monitor).

## Controls
- **Open hand** — control active (relative to where the arm is)
- **Fist** — clutch: freeze arm, reposition your hand, open to resume
- **Pinch** (thumb–index) — close/open gripper
- **Palm roll** — wrist_roll
- Keys: `ESC` e-stop · `H` home · `F` flag · `T` takeover · `R` resume · `Q` quit

## Run order
```powershell
cd C:\Users\ryker\hackathons\armteleop

# 0. One-time arm calibration (arm on wall power!)
lerobot-calibrate --robot.type=so101_follower --robot.port=COM5 --robot.id=follower

# 1. Arm hello world — verify connect/move + joint directions
python scripts/m0_arm_hello.py --port COM5

# 2. Hand tracking check (Spatial Anchor ON for eye)
python scripts/m1_hand_test.py --source eye     # or --source webcam

# 3. Hand → arm, no hardware motion (safe rehearsal)
python scripts/m2_hand_to_arm.py --source eye --sim

# 4. The real thing
python scripts/m2_hand_to_arm.py --source eye
```

Drag the "Operator HUD" window onto the glasses display (Win+Shift+Arrow).

## Fallbacks
| Problem | Fix |
|---------|-----|
| Eye stream down | `--source webcam` |
| ikpy misbehaving | `config.yaml → ik.tier: A` (analytic) |
| Joint moves wrong way | flip `ik.joint_sign.<joint>` to -1 |
| Anything scary | `ESC` (torque off) or pull arm power |

See `DESIGN.md` for the full system description.
