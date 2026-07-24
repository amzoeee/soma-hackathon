"""Preprocessing for the noisy 4-bit grayscale Eye frames.

MediaPipe's models are trained on RGB webcam imagery; the Eye's low-contrast
grayscale barely registers without this. Tuned empirically on the real feed:
denoise -> gamma lift -> CLAHE -> unsharp -> upscale.
"""

import cv2
import numpy as np

_GAMMA = 0.65
_UPSCALE = 2.5

_gamma_table = np.array(
    [((i / 255.0) ** (1.0 / _GAMMA)) * 255 for i in range(256)], dtype=np.uint8
)
_clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))


def enhance_grayscale(frame: np.ndarray, upscale: float = _UPSCALE) -> np.ndarray:
    """Takes a grayscale (HxW) or BGR frame, returns an enhanced RGB frame
    ready for MediaPipe. Landmark coords are normalized, so the upscale does
    not affect downstream mapping."""
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    gray = cv2.LUT(gray, _gamma_table)
    gray = _clahe.apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    gray = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    if upscale and upscale != 1.0:
        rgb = cv2.resize(rgb, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return rgb
