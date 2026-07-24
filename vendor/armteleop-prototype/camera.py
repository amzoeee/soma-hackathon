"""Camera sources: webcam and XREAL Eye grayscale stream."""

from __future__ import annotations

import socket
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

import cv2
import numpy as np


class CameraSource(ABC):
    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return an HxWx3 BGR frame, or None if unavailable."""

    @abstractmethod
    def release(self) -> None:
        ...


class WebcamSource(CameraSource):
    def __init__(self, index: int = 0):
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            # Fallback without CAP_DSHOW for non-Windows / some devices
            self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam index {index}")

    def read(self) -> np.ndarray | None:
        ok, frame = self.cap.read()
        return frame if ok else None

    def release(self) -> None:
        self.cap.release()


class XrealEyeSource(CameraSource):
    """Pull grayscale SLAM frames from the Aloim Eye TCP stream, emit BGR."""

    PACKET_SIZE = 193862
    HEADER_OFFSET = 0x140
    WIDTH = 512
    HEIGHT = 378
    IMAGE_SIZE = WIDTH * HEIGHT

    def __init__(self, host: str = "169.254.2.1", port: int = 52997):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._frames: deque[np.ndarray] = deque(maxlen=2)
        self._lock = threading.Lock()
        self._connect()
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((self.host, self.port))
        sock.settimeout(1)
        self._sock = sock

    def _decode(self, packet: bytes) -> np.ndarray | None:
        if len(packet) < self.HEADER_OFFSET + self.IMAGE_SIZE:
            return None
        data = packet[self.HEADER_OFFSET : self.HEADER_OFFSET + self.IMAGE_SIZE]
        pixels = np.frombuffer(data, dtype=np.uint8)
        pixels = ((pixels >> 4) & 0x0F) * 17
        gray = pixels.reshape((self.HEIGHT, self.WIDTH))
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    RECONNECT_AFTER_S = 4.0

    def _recv_loop(self) -> None:
        buf = b""
        last_data = time.time()
        while self._running:
            # Silent-stream recovery: the port accepts connections even when
            # no video is flowing; a fresh connection often restarts the feed.
            if time.time() - last_data > self.RECONNECT_AFTER_S:
                print("[eye] stream silent, reconnecting ...")
                try:
                    if self._sock is not None:
                        self._sock.close()
                except OSError:
                    pass
                try:
                    self._connect()
                    buf = b""
                except OSError:
                    time.sleep(1.0)
                last_data = time.time()
            if self._sock is None:
                time.sleep(0.1)
                continue
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    time.sleep(0.01)
                    continue
                last_data = time.time()
                buf += chunk
                while len(buf) >= self.PACKET_SIZE:
                    packet = buf[: self.PACKET_SIZE]
                    buf = buf[self.PACKET_SIZE :]
                    frame = self._decode(packet)
                    if frame is not None:
                        with self._lock:
                            self._frames.append(frame)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                time.sleep(0.5)

    def read(self) -> np.ndarray | None:
        with self._lock:
            if not self._frames:
                return None
            return self._frames[-1].copy()

    def release(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


def make_camera(config: dict[str, Any]) -> CameraSource:
    cam = config.get("camera", config)
    source = cam.get("source", "webcam")
    if source == "eye":
        stream = cam.get("eye_stream", {})
        return XrealEyeSource(
            host=stream.get("host", "169.254.2.1"),
            port=int(stream.get("port", 52997)),
        )
    if source == "webcam":
        return WebcamSource(index=int(cam.get("webcam_index", 0)))
    raise ValueError(f"Unknown camera.source: {source!r} (use 'eye' or 'webcam')")
