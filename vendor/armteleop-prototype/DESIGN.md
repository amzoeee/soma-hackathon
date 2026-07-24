# DESIGN — Locked for hackathon (2026-07-22)

> Source of truth for `armteleop`. Spec doc §12 build order still stands.
> **Done:** Eye stream + M1 landmarks. **Next hardware:** M0 arm hello (COM TBD).

---

## 0. Status

| Milestone | Status |
|-----------|--------|
| Eye feed (`169.254.2.1:52997`) | DONE |
| M1 hand landmarks (Eye + webcam) | DONE |
| M0 arm connect/move | TOMORROW (COM TBD) |
| M2 hand→arm | After M0 |
| M3–M7 | After M2 |

---

## 1. Verified facts (no longer open)

### Eye camera
- Protocol: TCP to `169.254.2.1:52997`
- Packet: `193862` bytes, header `0x2748`, image @ offset `0x140`
- Format: 512×378, 4-bit grayscale (high nibble) → BGR via `GRAY2BGR`
- Native ~30 FPS; Spatial Anchor must be ON
- MediaPipe: enhance always (denoise → gamma → CLAHE → unsharp → 2.5× upscale), conf ≈ 0.25

### LeRobot / SO-101 (installed `lerobot==0.4.1`)
```python
from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

cfg = SO101FollowerConfig(port="COMx", use_degrees=True, max_relative_target=5.0)
robot = SO101Follower(cfg)
robot.connect(calibrate=True)          # interactive if no calib file
obs = robot.get_observation()          # {"shoulder_pan.pos": deg, ..., "gripper.pos": 0..100}
robot.send_action({"shoulder_pan.pos": 10.0, ...})
robot.disconnect()                     # torque off if disable_torque_on_disconnect
```

| Joint | Motor ID | LeRobot units (`use_degrees=True`) | URDF limits (rad) |
|-------|----------|--------------------------------------|-------------------|
| shoulder_pan | 1 | degrees | ±1.92 |
| shoulder_lift | 2 | degrees | ±1.75 |
| elbow_flex | 3 | degrees | ±1.69 |
| wrist_flex | 4 | degrees | ±1.66 |
| wrist_roll | 5 | degrees | ±2.74 / +2.84 |
| gripper | 6 | **0..100** (always) | n/a for pose |

**Decision:** always set `use_degrees=True`. IK works in radians; convert with `math.degrees` before `send_action`. Gripper stays 0–100.

Load/current via bus (for FLAGGED + safety):
```python
robot.bus.sync_read("Present_Load")
robot.bus.sync_read("Present_Current")
```
Threshold: measure tomorrow under free motion vs light stall → set `load_flag_threshold`.

### URDF
- Canonical path: `robot/config/so101.urdf` (from repo root; same as SO-ARM100 `so101_new_calib.urdf`)
- Prototype config: `ik.urdf_path: "../../robot/config/so101.urdf"` (relative to this package)
- EE link for Tier B / twin: `gripper_frame_link`

### Analytic link lengths (Tier A) — from URDF joint origins
Treat as planar 2-link from shoulder_lift axis to wrist_flex axis:

| Segment | Length (m) | Source |
|---------|------------|--------|
| L1 (upper arm) | **0.1126** | `elbow_flex` origin ‖xy‖ ≈ 0.11257 |
| L2 (forearm) | **0.1349** | `wrist_flex` origin ‖x‖ ≈ 0.1349 |
| L3 (wrist→grip, fixed for MVP) | **0.098** | `gripper_frame_joint` ≈ 0.098 |

MVP IK targets the **wrist** (not fingertip): use L1+L2 only; hold wrist_flex at a fixed “look down” angle.

Shoulder height offset (pan axis above table): **z0 ≈ 0.0624 m** (`shoulder_pan` origin z). Tune live.

---

## 2. MVP control contract (LOCKED)

**What the operator controls tomorrow for M2:**
- Hand X → robot **Y** (left/right)
- Hand Y → robot **Z** (up/down, inverted)
- Reach **X fixed** at `fixed_reach_x = 0.20 m`
- Pinch → gripper
- SPACE held = clutch engaged (relative)
- ESC = e-stop (torque off)

**Not in MVP:** depth axis, wrist roll/pitch from palm, Tier B IK, load-based flag (use scripted/key until measured).

---

## 3. Module contracts

### `camera.py` — DONE
`CameraSource.read() → BGR | None`. Sources: `eye` | `webcam`.

### `hand_tracking.py` — DONE
`HandPose(present, x, y, depth_proxy, pinch, landmarks_px)`.

### `smoothing.py` — One Euro (per channel: x, y, depth_proxy)
```
min_cutoff = 1.0
beta = 0.007
```
Pinch: light EMA α=0.4 or none.

### `mapping.py` — HandToArmMapper
```python
@dataclass
class ArmTarget:
    x: float; y: float; z: float   # meters, robot base
    gripper: float                 # 0..100
    valid: bool

class HandToArmMapper:
    def map(self, pose: HandPose, *, engaged: bool) -> ArmTarget: ...
    # SPACE edge: on press → store hand_center = (pose.x, pose.y); freeze on release
```

**Relative clutched math (MVP, fixed X):**
```
if not engaged or not pose.present:
    return last_target  # freeze

dy = (pose.x - hand_center_x) * scale.y   # image x → robot Y
dz = -(pose.y - hand_center_y) * scale.z  # image y down → robot Z up

y = clamp(center.y + dy, workspace.y)
z = clamp(center.z + dz, workspace.z)
x = fixed_reach_x

gripper = 0 if pinch < close - hyst else 100 if pinch > close + hyst else hold
```

Default scales (tune live): `scale.y = 0.45`, `scale.z = 0.35` (meters per normalized image unit).  
Workspace box (safe, inside reach — tune after M0):
```
x: [0.15, 0.28]   # fixed 0.20 for MVP
y: [-0.18, 0.18]
z: [0.08, 0.28]
```

### `ik.py` — Tier A only until M2 solid

```
Input:  ArmTarget (x,y,z) in meters
Output: dict[str, float] joint degrees (+ gripper passthrough)

shoulder_pan = atan2(y, x)

# planar reach in the arm's vertical plane
r = hypot(x, y)
z_rel = z - z0
# 2-link law of cosines, elbow-UP:
c2 = (r² + z_rel² - L1² - L2²) / (2 L1 L2)
c2 = clamp(c2, -1, 1)
elbow = -acos(c2)                         # elbow-up = negative
shoulder_lift = atan2(z_rel, r) - atan2(L2*sin(elbow), L1 + L2*cos(elbow))

wrist_flex = wrist_fixed_deg              # e.g. -20° tip slightly down
wrist_roll = 0

# reject if unreachable (c2 was clamped hard / r too small) → return None → hold last
```

Convert: `math.degrees(q)` for body joints. Clamp to URDF limits in degrees.

**Sign convention risk:** SO-101 joint zero / URDF may disagree with “elbow-up” sign.  
**M0 ritual:** after connect, jog each joint ±10° and label the physical direction in `config.yaml` `joint_sign: {shoulder_lift: ±1, ...}`. Apply signs in `ik.solve` / `arm.write`.

### `arm.py` — ArmController
Wraps `SO101Follower`. Responsibilities:
1. `connect` / `disconnect` / `home`
2. `read_positions() → dict[str,float]` (degrees / gripper 0–100)
3. `read_load() → dict[str,float]`
4. `write_positions(goals)` with:
   - joint limit clamp
   - **velocity clamp:** `|goal-current| ≤ max_delta_deg` per tick (default **3°** @ 30 Hz)
   - optional `max_relative_target` also set on LeRobot config
5. `set_torque(False)` on ESC via `bus.disable_torque()` / disconnect path
6. Dry-run mode: `arm.sim=true` prints goals, no serial (develop without COM)

### `state_machine.py`
```
AUTONOMOUS → FLAGGED → TAKEOVER → AUTONOMOUS
ESTOP from anywhere

Triggers (MVP demo):
  AUTONOMOUS: play scripted waypoints OR hold home
  → FLAGGED: key F  OR  (later) load > threshold
  → TAKEOVER: SPACE pressed while FLAGGED (or always allow TAKEOVER key T)
  → AUTONOMOUS: key R after operator opens gripper / places

While FLAGGED: hold last pose, HUD screams HELP
While TAKEOVER: mapping+IK+arm if SPACE
While ESTOP: torque off until manual reset key
```

### `demo.py` loop @ 30 Hz
```
frame → hand → smooth → mode = sm.update(keys, load)
if mode == TAKEOVER and space:
    target = mapper.map(hand, engaged=True)
    goals = ik.solve(target)
    if goals: arm.write(goals)
elif mode == AUTONOMOUS:
    arm.write(script.next())
# else hold
hud.render(...)
```

### Deferred (after M2)
- `twin.py` pybullet + URDF
- `display.py` glasses monitor fullscreen
- Tier B numerical IK
- depth_proxy → X
- load-based flag

---

## 4. Safety (non-negotiable, in `arm.py`)

1. Velocity clamp every write  
2. Workspace clamp in mapper  
3. Joint limit clamp  
4. ESC → torque off  
5. `max_relative_target` on LeRobot config as second belt  
6. Intentional stall for load demo ≤ 1–2 s  
7. Arm wall PSU on; USB = data only  

---

## 5. Keys

| Key | Action |
|-----|--------|
| SPACE (hold) | Clutch engaged |
| ESC | E-STOP |
| H | Home |
| F | Flag (→ FLAGGED) |
| T | Force TAKEOVER |
| R | Resume AUTONOMOUS |
| Q | Quit |

---

## 6. File ownership (build tomorrow)

| File | Owner | When |
|------|-------|------|
| `scripts/m0_arm_hello.py` | Ryker+Jerry | First thing with COM |
| `arm.py` | Ryker | With M0 |
| `ik.py` | Ryker | Before M2 |
| `mapping.py` + `smoothing.py` | Zoe/Ryker | Before M2 |
| `scripts/m2_hand_to_arm.py` | Ryker | Integration |
| `state_machine.py` + `demo.py` | Ryker | After M2 feels good |

---

## 7. Tomorrow M0 checklist (print this)

- [ ] Arm wall power ON  
- [ ] Bus board on powered hub (not glasses hub)  
- [ ] Find COM: Device Manager / `python -m serial.tools.list_ports`  
- [ ] Set `arm.port` in config  
- [ ] `python scripts/m0_arm_hello.py` → print all `.pos`  
- [ ] Nudge `shoulder_pan` +5° — confirm direction → fill `joint_sign`  
- [ ] Record free-motion `Present_Load` baseline vs light push → `load_flag_threshold`  
- [ ] Then M2  

---

## 8. Fallbacks (unchanged, locked)

| Fail | Fallback |
|------|----------|
| Eye flaky | `--source webcam` |
| Tracking bad in venue | keyboard jog of same IK targets |
| Load trigger flaky | key `F` |
| Arm dies on stage | backup video |
| Glasses display | laptop monitor |

---

## 9. Out of scope until M2 works

Full 6-DOF orientation, stereo depth, Nebula RGB camera experiments, electrochromic API, LLM anything.
