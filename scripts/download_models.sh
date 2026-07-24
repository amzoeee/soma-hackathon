#!/bin/bash

# Get the directory of the project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Create models directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/models"

echo "Downloading MediaPipe hand tracking and gesture recognition models..."

# Hand Landmarker
wget -q --show-progress -O "$PROJECT_ROOT/models/hand_landmarker.task" "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

# Gesture Recognizer
wget -q --show-progress -O "$PROJECT_ROOT/models/gesture_recognizer.task" "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"

echo "Download complete. Models saved to models/ directory."
