# Drone_Hunter
# 🚁 Drone Hunter — Drone Detection and Tracking

A full-stack web application for real-time drone detection and tracking in video footage. Powered by **YOLOv5** for object detection and a custom visual tracker, the system supports both **RGB** and **Infrared (IR)** video streams with a clean browser-based interface for upload, processing, and playback.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [Usage](#usage)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Demo Scripts](#demo-scripts)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**Drone Hunter** detects and tracks unmanned aerial vehicles (UAVs/drones) in uploaded video files. The backend processes each frame using a YOLOv5-based detector to locate drones, then hands off to a visual tracker for smooth continuous tracking across frames. Processed video is returned to the user with bounding boxes drawn around detected drones.

The system automatically determines whether a video is RGB or IR (infrared) and applies the appropriate pre-trained model weights for each modality.

---

## 🏗️ System Architecture

The application follows a layered full-stack architecture with four main components:

```
<img width="1872" height="798" alt="image" src="https://github.com/user-attachments/assets/4a199c4c-f3ec-4268-a5c7-9e5f1be9dd83" />

```

### Data Flow (8 Steps)

| Step | From | To | Action |
|:---:|---|---|---|
| 1 | React (Browser) | Node.js + Express | `POST /upload-video` — sends video sequences |
| 2 | Node.js + Express | FastAPI | `POST /process-video` — forwards video for ML processing |
| 3 | FastAPI | Drone Hunter Model | Runs the YOLOv5 detection + tracking model |
| 4 | Drone Hunter Model | FastAPI | Returns tracking data and detection bounding boxes |
| 5 | FastAPI | Node.js + Express | Returns JSON results (detections) |
| 6 | Node.js + Express | MongoDB | Stores job metadata and detection results |
| 7 | MongoDB | Node.js + Express | Returns stored JSON data |
| 8 | Node.js + Express | React (Browser) | `GET /detections/:id` — returns final detections to UI |

---

## ✨ Features

- **Dual-modality detection** — supports both RGB and Infrared video inputs
- **YOLOv5-based detector** — fast, accurate drone detection using custom-trained weights
- **Visual object tracker** — smooth frame-to-frame tracking after initial detection
- **Detection stability logic** — filters out false positives using a consecutive-detection threshold
- **Web interface** — drag-and-drop video upload, real-time progress polling, in-browser preview
- **Background processing** — video jobs run in separate threads; the UI polls for status
- **Seekable video streaming** — HTTP Range request support for smooth HTML5 video playback
- **On-screen annotation** — green bounding box + "Drone" label when detected; red "No Drone Detected" overlay otherwise
- **File cleanup** — API endpoint to remove uploaded and processed files after use
- **Large file support** — accepts video uploads up to 500 MB

---

## 📁 Project Structure

```
Drone_Detection_and_Tracking/
│
├── app.py                     # Main Flask web application
├── api.py                     # REST API layer
├── demo_detect_track.py       # Standalone CLI demo script
├── demo_detect_track1.py      # Alternate CLI demo variant
├── test_inference.py          # Inference testing script
│
├── detect_wrapper/            # Detection module
│   ├── Detectoruav.py         # DroneDetection class (RGB + IR forward passes)
│   └── weights/
│       └── best.pt            # Pre-trained YOLOv5 IR weights
│
├── tracking_wrapper/          # Tracking module
│   ├── dronetracker/          # Primary UAV tracker
│   │   └── trackinguav/
│   │       └── evaluation/
│   │           └── tracker.py # Tracker class
│   └── drtracker/             # Alternate tracker implementation
│
├── yolov5/                    # YOLOv5 submodule / source
│
├── frontend/                  # Frontend assets (TypeScript/JS)
├── templates/                 # Jinja2 HTML templates
│   └── index.html             # Main web UI
│
├── environment.yml            # Conda environment specification
├── requirements.txt           # pip dependencies
├── requirements1.txt          # Alternate dependency set
├── requirements_optimized.txt # Minimal/optimized dependencies
└── package.json               # Node.js dependencies (frontend tooling)
```

---

## ⚙️ How It Works

1. **Upload** — The user uploads a video file via the web UI (up to 500 MB).
2. **Job creation** — A unique job ID is generated; the file is saved and a background thread is started.
3. **Model initialization** — On the first request, YOLOv5 weights are loaded for both IR and RGB modalities, and the tracker is initialized.
4. **Frame-by-frame processing:**
   - The video type (RGB or IR) is detected automatically from the first frame's colorfulness metric.
   - A **detection phase** runs the appropriate YOLOv5 forward pass to locate a drone bounding box.
   - A **stability check** requires at least 2 of the last 3 frames to agree before changing detection state, reducing flickering from false positives.
   - Once a stable detection is confirmed, the **tracker is initialized** with that bounding box and takes over for up to 150 frames (`TRACK_MAX_COUNT`).
   - Each frame is annotated: green box + "Drone" label when a drone is present; a red centered "No Drone Detected" overlay otherwise.
5. **Status polling** — The frontend polls `/status/<job_id>` to show progress percentage.
6. **Preview & download** — Completed video is served via HTTP Range requests for seekable playback directly in the browser, or as a file download.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Browser) |
| Middleware / API Gateway | Node.js + Express |
| ML Service | Python 3, FastAPI |
| Detection | YOLOv5 (PyTorch) |
| Tracking | Custom UAV visual tracker (Drone Hunter Model) |
| Database | MongoDB |
| Video processing | OpenCV |
| Concurrency | Python `threading` |

---

## ✅ Prerequisites

- Python 3.8 or higher
- `pip` or `conda`
- (Optional but recommended) CUDA-capable GPU for faster inference
- Node.js (only if building the frontend from source)

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/cheelavaishnavi123/Drone_Detection_and_Tracking.git
cd Drone_Detection_and_Tracking
```

### 2. Create and activate a virtual environment

**Using pip / venv:**
```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

**Using Conda (recommended):**
```bash
conda env create -f environment.yml
conda activate drone-hunter     # use the name defined in environment.yml
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

> If you encounter conflicts, try `requirements_optimized.txt` for a leaner install.

### 4. Add model weights

Place pre-trained YOLOv5 weights in the `detect_wrapper/weights/` directory:

```
detect_wrapper/weights/best.pt          # IR weights (required)
detect_wrapper/weights/drone_rgb_yolov5s.pt  # RGB weights (optional; falls back to IR)
```

---

## ▶️ Running the Application

```bash
python app.py
```

The server starts on **http://0.0.0.0:5000** by default. Open your browser and navigate to:

```
http://localhost:5000
```

---

## 🖥️ Usage

1. Open the web interface at `http://localhost:5000`.
2. Click **Upload Video** and select an `.mp4`, `.avi`, or other OpenCV-compatible video file.
3. Wait while the progress bar updates as frames are processed.
4. Once complete, use the **Preview** button to watch the annotated video in-browser, or **Download** to save it locally.
5. Optionally hit **Clean Up** to delete the temporary files from the server.

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serve the web UI |
| `POST` | `/upload` | Upload a video file; returns `job_id` |
| `GET` | `/status/<job_id>` | Poll processing progress and status |
| `GET` | `/download/<job_id>` | Download the processed video |
| `GET` | `/preview/<job_id>` | Stream processed video (supports Range requests) |
| `GET` | `/cleanup/<job_id>` | Delete uploaded and processed files for a job |

### Example: Upload a video

```bash
curl -X POST http://localhost:5000/upload \
  -F "video=@/path/to/your/drone_video.mp4"
```

**Response:**
```json
{
  "job_id": "1713870000",
  "message": "Video uploaded successfully. Processing started.",
  "status_url": "/status/1713870000"
}
```

### Example: Check status

```bash
curl http://localhost:5000/status/1713870000
```

**Response (in progress):**
```json
{
  "status": "processing",
  "progress": 42,
  "message": "Processing 1500 frames...",
  "drone_present": true
}
```

**Response (completed):**
```json
{
  "status": "completed",
  "progress": 100,
  "message": "Video processing completed successfully!",
  "output_path": "outputs/1713870000_processed_video.mp4",
  "drone_present": true
}
```

---

## 🔧 Configuration

Key settings in `app.py`:

| Variable | Default | Description |
|---|---|---|
| `MAX_CONTENT_LENGTH` | 500 MB | Maximum upload file size |
| `UPLOAD_FOLDER` | `uploads/` | Directory for raw uploaded files |
| `OUTPUT_FOLDER` | `outputs/` | Directory for processed output files |
| `TRACK_MAX_COUNT` | 150 | Frames the tracker runs before re-detecting |
| `DETECTION_THRESHOLD` | 3 | Consecutive frames required to confirm/deny a detection |

---

## 🧪 Demo Scripts

Run detection and tracking directly from the command line without the web server:

```bash
# Basic demo
python demo_detect_track.py

# Alternate demo variant
python demo_detect_track1.py

# Test model inference
python test_inference.py
```

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

This project does not currently specify a license. Please contact the repository owner before using it in production or distributing derived works.

---

> **Note:** Ensure that `detect_wrapper/weights/best.pt` exists before starting the server. Without model weights, the application will fail to initialize.
