#!/usr/bin/env python3
import cv2
import time
import argparse

def main():
    parser = argparse.ArgumentParser(description="Test Camera")
    parser.add_argument('--webcam', action='store_true', help='Use default webcam instead of specific device index 0')
    parser.add_argument('--index', type=int, default=0, help='Camera index to test')
    args = parser.parse_args()

    cam_index = args.index if not args.webcam else 0
    print(f"Opening camera index {cam_index}...")

    cap = cv2.VideoCapture(cam_index)
    
    if not cap.isOpened():
        print(f"Error: Could not open camera at index {cam_index}")
        return

    frames = 0
    start_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame.")
            break
            
        frames += 1
        elapsed = time.time() - start_time
        fps = frames / elapsed if elapsed > 0 else 0
        
        # Add FPS overlay
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        cv2.imshow("Camera Test", frame)
        
        if cv2.waitKey(1) & 0xFF == 27: # ESC
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
