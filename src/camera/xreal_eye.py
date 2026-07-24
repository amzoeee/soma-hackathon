import cv2
import logging
import numpy as np
import time

logger = logging.getLogger(__name__)

class XrealEyeCamera:
    """
    Captures grayscale frames from the Xreal One Pro Eye camera over USB-C NCM virtual Ethernet.
    """
    def __init__(self, device_index: int = 0, resolution: tuple[int, int] = (640, 480)):
        self.device_index = device_index
        self.resolution = resolution
        self.cap = None
        self._skip_frames = 10  # Skip initial frames to avoid black frames on start

    def open(self) -> bool:
        """Opens the video capture device."""
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            logger.error(f"Failed to open Xreal camera at device index {self.device_index}")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        
        # Skip initial frames
        for i in range(self._skip_frames):
            ret, _ = self.cap.read()
            if not ret:
                logger.warning(f"Failed to read initial frame {i}")
                
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Reads a frame and returns it as a grayscale numpy array."""
        if not self.is_opened():
            return False, None
            
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return False, None
            
        # Ensure frame is grayscale. OpenCV might read it as BGR even if it's a grayscale feed.
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
        return True, frame

    def close(self):
        """Releases the video capture device."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def is_opened(self) -> bool:
        """Checks if the video capture device is open."""
        return self.cap is not None and self.cap.isOpened()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
