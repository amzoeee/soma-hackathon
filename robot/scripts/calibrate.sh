#!/bin/bash

# Default port
PORT="/dev/ttyACM0"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --port) PORT="$2"; shift ;;
        --port=*) PORT="${1#*=}" ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "Calibrating SO-101 on port $PORT"

lerobot-calibrate \
    --robot.type=so101_follower \
    --robot.port="$PORT" \
    --robot.id=follower
