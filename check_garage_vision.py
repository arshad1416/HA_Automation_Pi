#!/usr/bin/env python3
"""Check garage door state via RTSP camera stream.
Returns 'open' or 'closed' for HA command_line sensor.

This is a stub that returns 'closed' until the garage camera RTSP stream
is reconfigured. The original script used OpenCV to analyze the camera feed.
To restore full functionality:
  1. Ensure rtsp://127.0.0.1:8554/garage stream is running (go2rtc)
  2. Install opencv: pip install opencv-python-headless
  3. Replace this stub with the vision analysis logic
"""
import sys

# Return 'closed' as safe default — the garage door template sensor
# will show 'closed' which is the safe state
print("closed")
sys.exit(0)
