# Fatigue Detection & Safety Monitoring System

This system simulates an industrial tool-handling task — the operator raises their hand to mimic picking up a tool, holds for three seconds, then lowers it. At the same time, the system monitors eye closure using Eye Aspect Ratio (EAR) calculated from facial landmarks. A one-second closure triggers a warning beep; seven seconds triggers a full lockout requiring manual reset. If the operator closes their eyes mid-task, the hold timer pauses immediately to prevent unsafe completion. All fatigue events are logged to InfluxDB for shift-level trend analysis.

---

## System Architecture

<img width="350" height="550" alt="040dc3e6-3880-4da1-9842-4c0cd073939c" src="https://github.com/user-attachments/assets/60fd5746-3df6-4bc4-9e91-f2b2f1e89cc6" />






## Features

- **Eye Closure Detection** — Calculates Eye Aspect Ratio (EAR) in real time; eyes closed > 1s triggers a warning beep, > 7s triggers a critical alarm and system lock
- **Pose-Based Task Verification** — Tracks arm position to confirm the operator actively holds a tool through a 3-step workflow (Raise → Hold → Lower)
- **Timer Integrity** — The hold timer pauses and resets if the operator's eyes close mid-task, preventing unsafe completion
- **Persistent Data Logging** — Every fatigue event is written to InfluxDB with a precise timestamp, worker ID, and real eye-closure duration
- **Management Analytics** — Logged data supports daily/weekly trend queries, enabling informed shift scheduling

---


### Normal Operation — Task Complete

<img width="123" height="123" alt="1" src="https://github.com/user-attachments/assets/9875132d-5b2e-449a-a0e3-da4f8ec0101e" />


When the operator successfully completes the 3-step tool workflow (Raise Tool → Hold Position → Lower Tool) with eyes open throughout, the system confirms **"TASK COMPLETE"** in green. All three steps are highlighted, and status reads **"Working Safely"**.

---

### Critical Alert — Fatigue Detected

<img width="123" height="123" alt="2" src="https://github.com/user-attachments/assets/a88bd0fd-c11f-478f-b51e-2ed37a86b6f7" />


When eye closure exceeds 7 seconds, the entire screen turns red, the status switches to **"CRITICAL: SLEEPING!"**, and the display locks with **"FATIGUE DETECTED – SYSTEM LOCKED"**. A critical alarm sound plays. The system cannot be resumed until the operator manually presses `R` to reset, ensuring a conscious acknowledgement before work continues.

---

### InfluxDB Data Explorer — Event Log

<img width="231" height="123" alt="3" src="https://github.com/user-attachments/assets/1951b8a4-8262-4bcc-941e-0cc9f9226ac3" />


Every fatigue event is recorded in InfluxDB as a time-series data point. The graph shows fatigue events plotted over time — each point on the blue line represents one incident, with the Y-axis showing eye-closure duration in seconds. Management can query this data by worker, by hour, or aggregated by day.

---

## Requirements

### Python Dependencies

```bash
pip install opencv-python mediapipe pygame influxdb-client
```

### Model Files

Download and place in the project root:
- [`pose_landmarker.task`](https://developers.google.com/mediapipe/solutions/vision/pose_landmarker)
- [`face_landmarker.task`](https://developers.google.com/mediapipe/solutions/vision/face_landmarker)

### Audio Files (Optional)

Place in the project root:
- `critical_alarm.wav` — plays on fatigue detection
- `warning_beep.wav` — plays on eye closure during task

---

## InfluxDB Setup

This system uses **InfluxDB OSS** as a local time-series database to persist all fatigue events.

### 1. Install & Start InfluxDB (Windows)

Download InfluxDB 2.x from the official site and extract the zip. Then open Command Prompt and navigate to the extracted folder:

```cmd
cd /d D:\your-path\influxdb2-2.x.x-windows
influxd.exe
```

Keep this window open — closing it stops the database. Then open your browser at:

```
http://localhost:8086
```

### 2. Initial Setup

On first launch, InfluxDB will ask you to create an account. Fill in:

| Field | Recommended Value |
|-------|------------------|
| Username | `admin` |
| Password | (your choice) |
| Organization | e.g. `my-org` |
| Bucket | `fatigue_data` |

### 3. Get Your API Token

1. In the left sidebar, click **API Tokens**
2. Click **Generate API Token → All Access Token**
3. Copy the token string

### 4. Configure the Python Script

At the top of `detection.py`, fill in your values:

```python
INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "paste-your-token-here"
INFLUX_ORG    = "my-org"          # must match exactly
INFLUX_BUCKET = "fatigue_data"    # must match exactly
WORKER_ID     = "worker_01"       # change per workstation
```

### 5. Verify Data is Flowing

Run the detection script and trigger a fatigue event (close your eyes for 7+ seconds). Then in InfluxDB:

1. Click **Data Explorer** in the left sidebar
2. Select bucket: `fatigue_data`
3. Select measurement: `fatigue_event`
4. Set time range to **Past 1h**
5. You should see a data point appear

---

## Data Model

Each fatigue event is stored with the following structure:

| Field | Type | Description |
|-------|------|-------------|
| `_measurement` | string | Always `fatigue_event` |
| `worker_id` | tag | Workstation identifier |
| `duration_seconds` | float | Actual eye-closure duration |
| `event_count` | integer | Always `1` — used for counting aggregations |
| `_time` | timestamp | Auto-assigned by InfluxDB at write time |

---

## Useful Queries (Flux)

**How many fatigue events happened today?**
```flux
from(bucket: "fatigue_data")
  |> range(start: today())
  |> filter(fn: (r) => r._measurement == "fatigue_event")
  |> filter(fn: (r) => r._field == "event_count")
  |> sum()
```

**Daily fatigue count over the past 30 days:**
```flux
from(bucket: "fatigue_data")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "fatigue_event")
  |> filter(fn: (r) => r._field == "event_count")
  |> aggregateWindow(every: 1d, fn: sum, createEmpty: true)
```

**Compare fatigue incidents across all workstations this week:**
```flux
from(bucket: "fatigue_data")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "fatigue_event")
  |> filter(fn: (r) => r._field == "event_count")
  |> group(columns: ["worker_id"])
  |> aggregateWindow(every: 1d, fn: sum)
```

---

## Manage by InfluxDB 

Standard relational databases (MySQL, SQLite) store rows and columns. InfluxDB is a **time-series database** — every record is automatically indexed by time, making it extremely efficient for questions like:

- *"How many incidents happened between 13:00 and 15:00 this week?"*
- *"Which workstation has the most fatigue events on Monday mornings?"*
- *"Is fatigue increasing or decreasing over the past month?"*

These queries would require complex SQL joins and aggregations in a traditional database. In InfluxDB they are a few lines of Flux.

---

## Management Use Case

The data logging layer is designed for operational decision-making. Example workflow:

1. **Detection** — AI detects a fatigue event and logs it instantly without interrupting the program
2. **Review** — At end of shift, a supervisor opens InfluxDB Data Explorer or a Grafana dashboard
3. **Pattern Recognition** — If fatigue events cluster around 14:00–15:00 every day, that signals a post-lunch alertness dip
4. **Action** — Schedule a mandatory break or shift rotation at that time window

> For production deployments, connecting InfluxDB to **Grafana** is recommended. Grafana can display fatigue trends as live dashboards with threshold alerts — for example, turning a panel red when a workstation exceeds 5 fatigue events in a single shift.

---

## Keyboard Controls

| Key | Action |
|-----|--------|
| `R` | Reset task state and clear fatigue lock |
| `Q` | Quit the program |

---

## Acknowledgements

This project is built on the following open-source tools and frameworks:

- **[MediaPipe](https://developers.google.com/mediapipe)** (Google) — Face Landmarker and Pose Landmarker models used for real-time facial landmark detection and body pose estimation. MediaPipe is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
- **[OpenCV](https://opencv.org/)** — Used for camera capture, frame processing, and UI rendering. OpenCV is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
- **[InfluxDB](https://www.influxdata.com/)** — Open-source time-series database used for persistent fatigue event logging. InfluxDB OSS is licensed under the [MIT License](https://opensource.org/licenses/MIT).
- **[Pygame](https://www.pygame.org/)** — Used for audio playback of warning and alarm sounds. Pygame is licensed under the [LGPL License](https://www.gnu.org/licenses/lgpl-3.0.html).

Audio files (`critical_alarm.wav`, `warning_beep.wav`) are original assets generated for this project and are free to use and distribute.

