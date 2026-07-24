"""Operator HUD for the XREAL glasses.

The One Pro is a plain USB-C DisplayPort monitor. This window auto-detects a
secondary monitor (the glasses) and fullscreens itself there — no dragging.
Camera view with the hand skeleton is embedded in the HUD, so the operator has
one surface: mode banner, camera, joints, warnings.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import cv2
import numpy as np

W, H = 1280, 720

# BGR palette
BG = (18, 14, 10)
FG = (230, 230, 230)
DIM = (140, 140, 140)
GOOD = (90, 200, 90)
WARN = (60, 170, 255)
BAD = (60, 60, 230)

MODE_COLORS = {
    "AUTONOMOUS": GOOD,
    "FLAGGED": BAD,
    "TAKEOVER": WARN,
    "ESTOP": BAD,
}

JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
JOINT_RANGE = {
    "shoulder_pan": (-110, 110),
    "shoulder_lift": (-100, 100),
    "elbow_flex": (-97, 97),
    "wrist_flex": (-95, 95),
    "wrist_roll": (-157, 163),
    "gripper": (0, 100),
}


def get_monitors() -> list[tuple[int, int, int, int]]:
    """Enumerate monitors as (left, top, width, height). Primary is at (0,0)."""
    monitors: list[tuple[int, int, int, int]] = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _cb(hmon, hdc, rect_ptr, lparam):
        r = rect_ptr.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)
    return monitors


def pick_glasses_monitor() -> tuple[int, int, int, int] | None:
    """Secondary monitor = the glasses. None if only one display."""
    mons = get_monitors()
    secondaries = [m for m in mons if not (m[0] == 0 and m[1] == 0)]
    return secondaries[0] if secondaries else None


class OperatorHUD:
    WINDOW = "Operator HUD"

    def __init__(self, on_glasses: bool = True):
        self._want_glasses = on_glasses
        self._on_glasses_now = False
        self._frame_count = 0
        cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
        self._place_window()

    def _place_window(self) -> None:
        """(Re)position: fullscreen on glasses if present, windowed on primary if not."""
        target = pick_glasses_monitor() if self._want_glasses else None
        if target is not None:
            left, top, w, h = target
            cv2.setWindowProperty(self.WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            cv2.moveWindow(self.WINDOW, left + 50, top + 50)
            cv2.setWindowProperty(self.WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            if not self._on_glasses_now:
                print(f"[hud] fullscreen on glasses monitor at ({left},{top}) {w}x{h}")
            self._on_glasses_now = True
        else:
            cv2.setWindowProperty(self.WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            cv2.moveWindow(self.WINDOW, 60, 60)
            cv2.resizeWindow(self.WINDOW, W, H)
            if self._on_glasses_now or self._frame_count == 0:
                print("[hud] glasses monitor not present — windowed on primary")
            self._on_glasses_now = False

    def _check_monitor(self) -> None:
        """Survive display hot-unplug: if the glasses monitor comes or goes,
        re-place the window instead of letting HighGUI die on a dead surface."""
        have_glasses = pick_glasses_monitor() is not None
        if have_glasses != self._on_glasses_now:
            self._place_window()

    def render(
        self,
        *,
        mode: str,
        engaged: bool,
        hand_present: bool,
        camera_bgr: np.ndarray | None = None,
        gesture: str = "",
        gripper_open: bool | None = None,
        fps: float = 0.0,
        source: str = "",
        arm_connected: bool = False,
        positions: dict[str, float] | None = None,
        commanded: dict[str, float] | None = None,
        stalled: dict[str, float] | None = None,
    ) -> None:
        self._frame_count += 1
        if self._frame_count % 60 == 0:  # ~2 s at 30 fps
            self._check_monitor()

        img = np.full((H, W, 3), BG, dtype=np.uint8)
        mode_color = MODE_COLORS.get(mode, WARN)

        # ── Camera panel (right side) ────────────────────────────────────
        if camera_bgr is not None:
            ph, pw = 480, 640
            panel = cv2.resize(camera_bgr, (pw, ph), interpolation=cv2.INTER_LINEAR)
            x0, y0 = W - pw - 30, 90
            img[y0:y0 + ph, x0:x0 + pw] = panel
            border = GOOD if (engaged and hand_present) else (BAD if not hand_present else WARN)
            cv2.rectangle(img, (x0 - 2, y0 - 2), (x0 + pw + 2, y0 + ph + 2), border, 2)

        # ── Mode banner ──────────────────────────────────────────────────
        if mode == "FLAGGED":
            cv2.rectangle(img, (0, 0), (W - 1, H - 1), BAD, 16)
            cv2.putText(img, "HELP NEEDED", (40, 70),
                        cv2.FONT_HERSHEY_DUPLEX, 1.8, BAD, 4, cv2.LINE_AA)
            cv2.putText(img, "open your hand to take over", (40, 110),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, FG, 2, cv2.LINE_AA)
        else:
            cv2.putText(img, mode, (40, 70), cv2.FONT_HERSHEY_DUPLEX, 1.6, mode_color, 3, cv2.LINE_AA)
            clutch_txt = "ENGAGED - hand controls arm" if engaged else "FROZEN - fist or no hand"
            cv2.putText(img, clutch_txt, (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        GOOD if engaged else DIM, 2, cv2.LINE_AA)

        # ── Status rows (left column) ────────────────────────────────────
        y = 170
        rows = [
            ("ARM", "connected" if arm_connected else "SIM / offline", GOOD if arm_connected else WARN),
            ("CAMERA", f"{source}  {fps:.0f} fps", FG),
            ("HAND", "tracking" if hand_present else "NOT VISIBLE", GOOD if hand_present else BAD),
        ]
        if gesture:
            rows.append(("GESTURE", gesture, FG))
        if gripper_open is not None:
            rows.append(("GRIPPER", "open" if gripper_open else "CLOSED",
                         FG if gripper_open else WARN))
        for label, value, color in rows:
            cv2.putText(img, label, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, DIM, 2, cv2.LINE_AA)
            cv2.putText(img, str(value), (210, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
            y += 40

        # ── Joint bars ───────────────────────────────────────────────────
        if positions:
            bx, bw = 40, 480
            by = y + 30
            for j in JOINT_ORDER:
                if j not in positions:
                    continue
                lo, hi = JOINT_RANGE[j]
                frac = min(max((positions[j] - lo) / (hi - lo), 0.0), 1.0)
                stall = stalled and j in stalled
                cv2.putText(img, j, (bx, by - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA)
                cv2.rectangle(img, (bx, by), (bx + bw, by + 12), (90, 90, 90), 1)
                cv2.rectangle(img, (bx, by), (bx + int(bw * frac), by + 12),
                              BAD if stall else GOOD, -1)
                if commanded and j in commanded:
                    cfrac = min(max((commanded[j] - lo) / (hi - lo), 0.0), 1.0)
                    cx = bx + int(bw * cfrac)
                    cv2.line(img, (cx, by - 4), (cx, by + 16), WARN, 2)
                by += 44

        if stalled:
            cv2.putText(img, f"STALL: {', '.join(stalled)}", (40, H - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, BAD, 2, cv2.LINE_AA)

        try:
            cv2.imshow(self.WINDOW, img)
        except cv2.error:
            # Window/monitor vanished — rebuild on whatever display exists
            cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
            self._place_window()
