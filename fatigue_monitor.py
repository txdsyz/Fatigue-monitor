import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import time
import numpy as np
from datetime import datetime
import pygame
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import ASYNCHRONOUS

#  Audio Setup (Warning & Critical Alarms)
pygame.mixer.init()

alarm_sound = pygame.mixer.Sound('critical_alarm.wav')
warning_sound = pygame.mixer.Sound('warning_beep.wav')



# InfluxDB Setup (Async Logging)



INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "Z7mSq2nmZS82qpL0gqVwsjgaigebbKEKPxDiaKMy4KL2_A4-aOTxlI8adyPWjnEDjUzFbY9JOZThlXiyU6NhZA=="
INFLUX_ORG = "Monitor"
INFLUX_BUCKET = "fatigue_data"

db_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = db_client.write_api(write_options=ASYNCHRONOUS)

log_sleep_done = False


# Utilities & Model Setup

def calculate_ear(face_landmarks, eye_indices, w, h):
    pts = np.array([[face_landmarks[i].x * w, face_landmarks[i].y * h] for i in eye_indices])
    A = np.linalg.norm(pts[1] - pts[5])
    B = np.linalg.norm(pts[2] - pts[4])
    C = np.linalg.norm(pts[0] - pts[3])
    return (A + B) / (2.0 * C) if C != 0 else 0

RIGHT_EYE = [33, 160, 158, 133, 153, 144]
LEFT_EYE = [362, 385, 387, 263, 373, 380]

# Simplified skeleton (arms and shoulders only)
UPPER_BODY_CONNECTIONS = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]

# Init MediaPipe Tasks API Models
pose_options = vision.PoseLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path='pose_landmarker.task'),
    running_mode=vision.RunningMode.VIDEO
)
detector = vision.PoseLandmarker.create_from_options(pose_options)

face_options = vision.FaceLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path='face_landmarker.task'),
    running_mode=vision.RunningMode.VIDEO, num_faces=1
)
face_detector = vision.FaceLandmarker.create_from_options(face_options)

# System states
current_step = 0
hold_start_time = None
HOLD_DURATION = 3
accumulated_time = 0
sleep_start_time = None
WORKER_ID = "worker_01" # Assign a unique number to each workstation

cap = cv2.VideoCapture(0)

window_name = 'Attention Detection'
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL) # change window size
#cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN) # FULLSCREEN

while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    timestamp_ms = int(time.time() * 1000)

    # Process both models
    result = detector.detect_for_video(mp_image, timestamp_ms)
    face_result = face_detector.detect_for_video(mp_image, timestamp_ms)

    head_status, head_color = "Working Safely", (0, 255, 0)
    is_sleeping = False
    is_eyes_closed_for_pause = False
    is_drowsy_waiting = False

    # Core Defense: Eye Closure Detection
    # Core Defense: Eye Closure Detection
    if face_result.face_landmarks:
        face_lm = face_result.face_landmarks[0]
        avg_ear = (calculate_ear(face_lm, LEFT_EYE, w, h) + calculate_ear(face_lm, RIGHT_EYE, w, h)) / 2.0

        if avg_ear < 0.20:
            if sleep_start_time is None:
                sleep_start_time = time.time()

            closed_duration = time.time() - sleep_start_time

            if closed_duration > 1.5:
                is_eyes_closed_for_pause = True


            if current_step != 1 and closed_duration > 3.0 and closed_duration <= 7.0:
                is_drowsy_waiting = True
                if warning_sound and not pygame.mixer.get_busy():
                    warning_sound.play()

            if closed_duration > 7.0:
                is_sleeping = True
                pygame.mixer.stop()
                if alarm_sound and not pygame.mixer.get_busy():
                    alarm_sound.play()
        else:
            is_eyes_closed_for_pause = False
            is_drowsy_waiting = False
            sleep_start_time = None
            log_sleep_done = False

            if current_step != -1:
                pygame.mixer.stop()

    # Pose Detection (Arms)
    arm_up, arm_down = False, True
    if result.pose_landmarks:
        lm = result.pose_landmarks[0]
        for c in UPPER_BODY_CONNECTIONS:
            cv2.line(frame, (int(lm[c[0]].x * w), int(lm[c[0]].y * h)), (int(lm[c[1]].x * w), int(lm[c[1]].y * h)), (255, 255, 255), 2)
            cv2.circle(frame, (int(lm[c[0]].x * w), int(lm[c[0]].y * h)), 4, (0, 255, 255), -1)

        arm_up = (lm[15].y < lm[11].y) or (lm[16].y < lm[12].y)
        arm_down = not arm_up


    # State Machine & Task Logic
    if current_step >= 0:
        if is_sleeping:
            current_step = -1
            hold_start_time, accumulated_time = None, 0

            if not log_sleep_done:
                real_duration = time.time() - sleep_start_time
                point = (
                    Point("fatigue_event")
                    .tag("worker_id", WORKER_ID)
                    .field("duration_seconds", round(real_duration, 1))
                    .field("event_count", 1)   # 方便以后按天 sum()
                )
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
                log_sleep_done = True
                print(f"[{datetime.now()}] logged in DB: worker={WORKER_ID}, Duration of eye closure={real_duration:.1f}s")

    if current_step == -1:
        head_status, head_color = "CRITICAL: SLEEPING!", (0, 0, 255)

    elif current_step == 0:
        if arm_up:
            current_step, hold_start_time, accumulated_time = 1, time.time(), 0

    elif current_step == 1:
        if arm_up:
            # The progress bar only moves forward when you are awake and have your eyes open
            if not is_sleeping and not is_eyes_closed_for_pause:
                now = time.time()
                accumulated_time += (now - hold_start_time)
                hold_start_time = now
                cv2.putText(frame, f"Processing... {max(0, HOLD_DURATION - accumulated_time):.1f}s", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

                if accumulated_time >= HOLD_DURATION:
                    current_step = 2
            else:
                # Reset the timestamp for a single frame
                hold_start_time = time.time()

                # If eye closure is detected (using a 0.5-second filter)
                if is_eyes_closed_for_pause:

                    # Not just paused—the total time has been reset to zero
                    accumulated_time = 0

                    cv2.putText(frame, "Eyes Closed! Timer Reset...", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 3)

                    # Sound alarm
                    if warning_sound and not pygame.mixer.get_busy():
                        warning_sound.play()
        else:
            # If you take your hand off, the timer resets
            hold_start_time, accumulated_time = time.time(), 0

    elif current_step == 2:
        if arm_down:
            current_step = 3

    # UI Rendering
    cv2.rectangle(frame, (0, 0), (w, 40), (30, 30, 30), -1)
    cv2.putText(frame, f"Status: {head_status}", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, head_color, 2)

    if is_drowsy_waiting and current_step != -1:
        cv2.putText(frame, "WARNING: WAKE UP!", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 3)

    if current_step == -1:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 255), -1)
        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
        cv2.putText(frame, "FATIGUE DETECTED - SYSTEM LOCKED", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 3)
    else:
        steps = ["1. Raise Tool", "2. Hold Position", "3. Lower Tool"]
        for i, s in enumerate(steps):
            color = (0, 255, 0) if i < current_step else (100, 100, 100)
            thickness = 2 if i == current_step else 1
            cv2.putText(frame, s, (50, 80 + i * 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, thickness)
        if current_step == 3:
            cv2.putText(frame, "TASK COMPLETE", (50, 220), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # Persistent UI Instructions
    cv2.putText(frame, "[Q] Quit System   [R] Reset Task", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

    cv2.imshow('Attention Detection', frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'): break
    if key == ord('r'):
        current_step, accumulated_time = 0, 0
        sleep_start_time, hold_start_time = None, None
        log_sleep_done = False
        pygame.mixer.stop()

write_api.close()
db_client.close()
cap.release()
cv2.destroyAllWindows()
