"""XREAL One Pro Eye camera over the Aloim TCP grayscale stream.

The Eye is NOT a UVC webcam. It exposes a raw TCP stream on the NCM virtual
ethernet adapter that Nebula (Windows beta) creates:

    host 169.254.2.1, port 52997

Each packet is 193862 bytes; the image payload starts at offset 0x140 and is
512x378 with the useful 4 bits in the high nibble of each byte.

Requirements for the stream to be live:
  * Nebula Windows beta installed, beta firmware on the glasses
  * Spatial Anchor mode ON (it resets after a glasses restart)
  * Glasses connected with video+data over USB-C DP alt mode

The TCP connection succeeds even when Spatial Anchor is off -- the stream is
just silent. open() waits briefly for a first frame and fails loudly if none
arrives. The recv loop auto-reconnects if the stream goes silent mid-session.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)


class XrealEyeCamera:
    """Captures grayscale frames from the Xreal One Pro Eye over TCP."""

    PACKET_SIZE = 193862
    HEADER_OFFSET = 0x140
    WIDTH = 512
    HEIGHT = 378
    IMAGE_SIZE = WIDTH * HEIGHT
    RECONNECT_AFTER_S = 4.0

    def __init__(
        self,
        host: str = "169.254.2.1",
        port: int = 52997,
        first_frame_timeout: float = 5.0,
        # accepted for Settings compatibility; the stream has a fixed size
        device_index: int = 0,
        resolution: tuple[int, int] | None = None,
    ):
        self.host = host
        self.port = port
        self.first_frame_timeout = first_frame_timeout
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._frames: deque[np.ndarray] = deque(maxlen=2)
        self._lock = threading.Lock()

    def open(self) -> bool:
        """Connects and waits for the first frame. False if stream is dead."""
        try:
            self._connect()
        except OSError as e:
            logger.error(
                "Cannot reach Eye stream at %s:%s (%s). Is the NCM adapter up "
                "and Nebula running?",
                self.host,
                self.port,
                e,
            )
            return False

        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

        deadline = time.time() + self.first_frame_timeout
        while time.time() < deadline:
            with self._lock:
                if self._frames:
                    logger.info("Eye stream live (%dx%d)", self.WIDTH, self.HEIGHT)
                    return True
            time.sleep(0.05)

        logger.error(
            "Connected to Eye but no video after %.1fs -- Spatial Anchor is "
            "probably OFF (it resets after a glasses restart). Toggle it on "
            "in the glasses menu.",
            self.first_frame_timeout,
        )
        self.close()
        return False

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
        return pixels.reshape((self.HEIGHT, self.WIDTH))

    def _recv_loop(self) -> None:
        buf = b""
        last_data = time.time()
        while self._running:
            if time.time() - last_data > self.RECONNECT_AFTER_S:
                logger.warning("Eye stream silent, reconnecting ...")
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

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Returns the latest grayscale frame (HxW uint8)."""
        with self._lock:
            if not self._frames:
                return False, None
            return True, self._frames[-1].copy()

    def close(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def is_opened(self) -> bool:
        return self._running and self._sock is not None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
