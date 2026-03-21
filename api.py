import os
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass
import json
import shutil
import subprocess
from datetime import datetime
import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from typing import Optional
from google import genai
from google.genai import types

# Optional MongoDB / GridFS
MONGODB_URI = os.environ.get('MONGODB_URI')
MONGODB_DB = os.environ.get('MONGODB_DB', 'droneTracking')
mongo_client = None
grid_fs = None
mongo_collection = None
try:
    if MONGODB_URI:
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
        import gridfs
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        # ping to verify connection
        try:
            mongo_client.admin.command('ping')
            print("✅ Connected to MongoDB Atlas successfully!")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"❌ Could not connect to MongoDB Atlas: {e}")
            mongo_client = None
        if mongo_client is not None:
            mongo_db = mongo_client[MONGODB_DB]
            grid_fs = gridfs.GridFS(mongo_db)
            mongo_collection = mongo_db["processingVideos"]
    else:
        print("ℹ️ MONGODB_URI not set; skipping MongoDB Atlas connection.")
except Exception as e:
    print(f"❌ MongoDB initialization error: {e}")
    mongo_client = None
    grid_fs = None
    mongo_collection = None
from fastapi.middleware.cors import CORSMiddleware
from threading import Lock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')
PROGRESS_SUFFIX = '.progress.json'

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Drone Detection & Tracking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROCESS_MAP = {}
PROCESS_LOCK = Lock()


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".mp4", ".avi", ".mov"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed: MP4, AVI, MOV")

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    saved_name = f"video_{ts}{ext}"
    save_path = os.path.join(UPLOAD_DIR, saved_name)

    with open(save_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # Store in GridFS if configured
    input_grid_id: Optional[str] = None
    if grid_fs is not None:
        try:
            # re-open to stream from disk to GridFS
            with open(save_path, 'rb') as fh:
                grid_id = grid_fs.put(
                    fh,
                    filename=saved_name,
                    content_type='video/mp4' if ext == '.mp4' else 'application/octet-stream',
                    metadata={"type": "input"}
                )
                input_grid_id = str(grid_id)
        except Exception:
            input_grid_id = None

    return {"filename": saved_name, "path": save_path, "input_id": input_grid_id}


@app.post("/process")
async def process_video(filename: str = Form(...), input_id: str = Form(None)):
    input_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(input_path):
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    out_name = os.path.splitext(filename)[0] + "_processed.mp4"
    output_path = os.path.join(OUTPUT_DIR, out_name)

    script_path = os.path.join(BASE_DIR, 'demo_detect_track.py')
    if not os.path.isfile(script_path):
        raise HTTPException(status_code=500, detail="Processing script not found")

    # Build a deterministic progress file path based on input -> output mapping
    input_base, _ = os.path.splitext(filename)
    expected_out = f"{input_base}_processed.mp4"
    progress_path = os.path.join(OUTPUT_DIR, expected_out + PROGRESS_SUFFIX)

    # Ensure any stale progress file is reset
    try:
        if os.path.isfile(progress_path):
            os.remove(progress_path)
    except Exception:
        pass

    # Start the script and return immediately; frontend will poll progress and finalize later
    try:
        python_exec = os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe') if os.name == 'nt' else 'python'
        cmd = [
            python_exec,
            script_path,
            '--input', input_path,
            '--output', output_path,
            '--no-gui',
            '--progress', progress_path
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with PROCESS_LOCK:
            PROCESS_MAP[filename] = proc
        # write initial progress file if not exists
        try:
            if not os.path.isfile(progress_path):
                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump({"percent": 0, "processed": 0}, f)
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start processing: {e}")

    return JSONResponse({"started": True, "output": out_name})


@app.post("/finalize")
async def finalize_video(filename: str = Form(...), input_id: str = Form(None)):
    input_path = os.path.join(UPLOAD_DIR, filename)
    out_name = os.path.splitext(filename)[0] + "_processed.mp4"
    output_path = os.path.join(OUTPUT_DIR, out_name)
    metrics_path = output_path + '.json'

    if not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Output not ready")

    response = {
        "output": out_name,
        "metrics": None,
        "stdout": "",
        "stderr": "",
        "drone_detected": False,
        "detection_probability": 0,
        "alert": False
    }
    mode = "Unknown"
    if os.path.isfile(metrics_path):
        response["metrics"] = os.path.basename(metrics_path)
        try:
            with open(metrics_path, 'r', encoding='utf-8') as f:
                m = json.load(f)
            alert = False
            alert_reason = None
            mode = m.get('video_type', "Unknown") if isinstance(m, dict) else "Unknown"
            drone_detected = m.get("drone_detected", False)
            detection_probability = m.get("detection_probability", 0)
            if detection_probability > 20:
                alert = True
                alert_reason = f"Drone detected with {detection_probability}% probability"
            response["alert"] = alert
            if alert_reason:
                response["alert_reason"] = alert_reason
            response["metrics_obj"] = m
            response["video_type"] = mode
            response["drone_detected"] = drone_detected
            response["detection_probability"] = detection_probability
        except Exception:
            pass

    # Save processed video to GridFS if configured
    if grid_fs is not None:
        try:
            with open(output_path, 'rb') as fh:
                out_id = grid_fs.put(
                    fh,
                    filename=out_name,
                    content_type='video/mp4',
                    metadata={"type": "output", "source": filename, "video_type": mode}
                )
                response["output_id"] = str(out_id)
        except Exception:
            pass

    # Persist a record linking input/output in collection
    if mongo_collection is not None:
        try:
            from bson import ObjectId
            doc = {
                "createdAt": datetime.utcnow(),
                "input": {
                    "filename": filename,
                    "id": ObjectId(input_id) if input_id else None
                },
                "output": {
                    "filename": out_name,
                    "id": ObjectId(response.get("output_id")) if response.get("output_id") else None
                },
                "metrics": response.get("metrics_obj"),
                "alert": response.get("alert", False),
                "alert_reason": response.get("alert_reason"),
                "video_type": mode
            }
            if doc["input"]["id"] is None:
                del doc["input"]["id"]
            if doc["output"]["id"] is None:
                del doc["output"]["id"]
            inserted = mongo_collection.insert_one(doc)
            response["record_id"] = str(inserted.inserted_id)
        except Exception:
            pass

    return JSONResponse(response)


@app.get("/download/video/{name}")
async def download_video(name: str, request: Request):
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    range_header = request.headers.get('range')
    file_size = os.path.getsize(path)
    if range_header is None:
        # No range requested; serve full file
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"inline; filename=\"{name}\"",
        }
        return FileResponse(path, media_type="video/mp4", filename=name, headers=headers)

    # Parse Range: bytes=start-end
    try:
        units, _, rng = range_header.partition("=")
        if units != "bytes":
            raise ValueError("Invalid units")
        start_str, _, end_str = rng.partition("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        start = max(0, start)
        end = min(end, file_size - 1)
        if start > end:
            raise ValueError("Invalid range")
    except Exception:
        # Malformed Range header
        raise HTTPException(status_code=416, detail="Invalid range header")

    chunk_size = (end - start) + 1

    def iter_file(file_path: str, offset: int, length: int, block_size: int = 1024 * 1024):
        with open(file_path, 'rb') as f:
            f.seek(offset)
            remaining = length
            while remaining > 0:
                read_size = min(block_size, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": "video/mp4",
        "Content-Disposition": f"inline; filename=\"{name}\"",
    }
    return StreamingResponse(iter_file(path, start, chunk_size), status_code=206, headers=headers)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from bson import ObjectId

@app.get("/download/video/byid/{file_id}")
async def download_video_by_id(file_id: str, request: Request):
    if grid_fs is None:
        raise HTTPException(status_code=503, detail="GridFS not configured")

    try:
        f = grid_fs.get(ObjectId(file_id))
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    size = f.length
    range_header = request.headers.get("range")

    # Serve full video if no Range header
    if not range_header:
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{f.filename or "video.mp4"}"',
        }
        def full_iter():
            f.seek(0)
            chunk = f.read(1024 * 1024)
            while chunk:
                yield chunk
                chunk = f.read(1024 * 1024)
        return StreamingResponse(full_iter(), media_type=f.content_type or "video/mp4", headers=headers)

    # Serve partial content for range requests
    try:
        units, _, rng = range_header.partition("=")
        if units != "bytes":
            raise ValueError("Only bytes range supported")
        start_str, _, end_str = rng.partition("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else size - 1
        start = max(0, start)
        end = min(end, size - 1)
        if start > end:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    length = end - start + 1
    f.seek(start)

    def iter_bytes():
        remaining = length
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": f.content_type or "video/mp4",
        "Content-Disposition": f'inline; filename="{f.filename or "video.mp4"}"',
    }

    return StreamingResponse(iter_bytes(), status_code=206, headers=headers)



@app.get("/videos")
async def list_videos(limit: int = 20):
    if mongo_collection is None:
        return []
    try:
        items = []
        for d in mongo_collection.find({}, sort=[("createdAt", -1)]).limit(max(1, min(100, limit))):
            input_id = d.get("input", {}).get("id")
            output_id = d.get("output", {}).get("id")
            items.append({
                "id": str(d.get("_id")),
                "createdAt": d.get("createdAt").isoformat() if d.get("createdAt") else None,
                "input": {
                    "filename": d.get("input", {}).get("filename"),
                    "id": str(input_id) if input_id else None
                },
                "output": {
                    "filename": d.get("output", {}).get("filename"),
                    "id": str(output_id) if output_id else None
                },
                "alert": d.get("alert", False),
                "alert_reason": d.get("alert_reason"),
                "video_type": d.get("video_type", "Unknown")
            })
        return items
    except Exception:
        return []


@app.get("/download/metrics/{name}")
async def download_metrics(name: str):
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/json", filename=name)

@app.get("/video/{file_id}")
async def get_video(file_id: str, request: Request):
    # Just call your existing byid endpoint logic
    return await download_video_by_id(file_id, request)


@app.get("/progress/{input_name}")
async def get_progress(input_name: str):
    """
    Report analysis progress for a given uploaded input filename.
    Computes the expected output name and looks for a corresponding progress file.
    """
    try:
        base, _ = os.path.splitext(input_name)
        out_name = f"{base}_processed.mp4"
        progress_file = os.path.join(OUTPUT_DIR, out_name + PROGRESS_SUFFIX)
        if not os.path.isfile(progress_file):
            return {"percent": 0}
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Ensure we return a sane integer percentage
        pct = int(max(0, min(100, int(data.get('percent', 0)))))
        return {"percent": pct, **({k: v for k, v in data.items() if k != 'percent'})}
    except Exception:
        return {"percent": 0}


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/status")
async def status():
    return {
        "gridfs_connected": bool(grid_fs),
        "collection_connected": bool(mongo_collection),
        "db": MONGODB_DB,
    }


@app.post("/cancel")
async def cancel_processing(filename: str = Form(...)):
    """Terminate an in-flight processing job for a given uploaded filename."""
    with PROCESS_LOCK:
        proc = PROCESS_MAP.get(filename)
    if not proc:
        return {"cancelled": False, "reason": "no running job"}
    try:
        proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    with PROCESS_LOCK:
        PROCESS_MAP.pop(filename, None)
    try:
        base, _ = os.path.splitext(filename)
        out_name = f"{base}_processed.mp4"
        progress_file = os.path.join(OUTPUT_DIR, out_name + PROGRESS_SUFFIX)
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump({"percent": 0, "cancelled": True}, f)
    except Exception:
        pass
    return {"cancelled": True}


# -------- Gemini Drone Description Endpoint --------
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# Initialize Gemini client (lazy initialization)
_gemini_client = None

def get_gemini_client():
    """Get or create the Gemini client instance."""
    global _gemini_client
    if _gemini_client is None and GOOGLE_API_KEY:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
    return _gemini_client


def _normalize_drone_name(raw: str) -> str:
    n = (raw or "").replace("\n", " ").strip()
    n = n.replace("_", " ").replace("-", " ")
    while "  " in n:
        n = n.replace("  ", " ")
    # drop leading numeric ids like "21 "
    if n and n[0].isdigit():
        parts = n.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            n = parts[1]
    # common tidy
    if n.lower().endswith(" pro"):
        n = n[:-4] + " Pro"
    return n.strip()


def _build_drone_prompt(drone_name: str) -> str:
    """Build the prompt text for drone description."""
    instructions = (
        "You are a safety-focused assistant. Provide neutral, general, non-sensitive public information. "
        "Write exactly 5 concise sentences about the given consumer/commercial drone model or type. "
        "Cover: what it is, typical uses, where it is used, potential risks or misuse considerations, and high-level legal/regulatory notes. "
        "Avoid instructions, schematics, or guidance enabling harm. No code, no lists—just five plain sentences. "
        "If the exact model is unknown, say so and provide general guidance for similar drones. "
        f"Drone: {drone_name}."
    )
    return instructions


def _extract_text_from_response(response) -> str:
    """Extract text from the new SDK response object."""
    try:
        if hasattr(response, 'text'):
            return response.text.strip()
        elif hasattr(response, 'candidates') and response.candidates:
            # Fallback for structured response
            texts = []
            for candidate in response.candidates:
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'text'):
                            texts.append(part.text)
            return "\n".join(texts).strip()
        return ""
    except Exception:
        return ""


@app.post("/describe-drone")
async def describe_drone(name: str = Form(...)):
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not configured on server")
    name_clean = _normalize_drone_name(name or "")
    if not name_clean:
        raise HTTPException(status_code=400, detail="Drone name required")

    client = get_gemini_client()
    if not client:
        raise HTTPException(status_code=500, detail="Failed to initialize Gemini client")

    model_name = GEMINI_MODEL
    text = ""
    response_first = None
    last_error = None

    # Retry logic for 503 errors and other transient failures
    for attempt in range(3):
        try:
            # First attempt with main prompt
            prompt = _build_drone_prompt(name_clean)
            response_first = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=220,
                )
            )
            text = _extract_text_from_response(response_first)
            if text:
                break
        except Exception as e:
            last_error = e
            error_str = str(e)
            # Check if it's a 503 or overloaded error - retry with backoff
            if "503" in error_str or "overloaded" in error_str.lower() or "UNAVAILABLE" in error_str:
                if attempt < 2:  # Don't sleep on last attempt
                    time.sleep(0.5 * (2 ** attempt))  # Exponential backoff: 0.5s, 1s
                    continue
            # If not a retryable error, try simpler prompt
            try:
                retry_prompt = (
                    "Provide neutral, public, non-sensitive background about this drone model or family "
                    "in exactly 5 short sentences. Avoid instructions or enabling harm. "
                    f"Name: {name_clean}."
                )
                response_retry = client.models.generate_content(
                    model=model_name,
                    contents=retry_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=180,
                    )
                )
                text = _extract_text_from_response(response_retry)
                if text:
                    break
            except Exception as retry_error:
                # If retry also fails and it's not a 503, raise immediately
                if "503" not in str(retry_error) and "overloaded" not in str(retry_error).lower():
                    detail = {"message": f"Gemini request failed: {str(e)}", "model": model_name}
                    if response_first and hasattr(response_first, 'prompt_feedback') and response_first.prompt_feedback:
                        if hasattr(response_first.prompt_feedback, 'block_reason'):
                            detail["blockReason"] = str(response_first.prompt_feedback.block_reason)
                    raise HTTPException(status_code=502, detail=detail)
                last_error = retry_error
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    continue

    # If we exhausted all retries
    if not text and last_error:
        detail = {"message": f"Gemini request failed after retries: {str(last_error)}", "model": model_name}
        if response_first and hasattr(response_first, 'prompt_feedback') and response_first.prompt_feedback:
            if hasattr(response_first.prompt_feedback, 'block_reason'):
                detail["blockReason"] = str(response_first.prompt_feedback.block_reason)
        raise HTTPException(status_code=502, detail=detail)

    if not text:
        detail = {"message": "Empty response from Gemini", "model": model_name}
        if response_first and hasattr(response_first, 'prompt_feedback') and response_first.prompt_feedback:
            if hasattr(response_first.prompt_feedback, 'block_reason'):
                detail["blockReason"] = str(response_first.prompt_feedback.block_reason)
        raise HTTPException(status_code=502, detail=detail)

    # Normalize to exactly 5 sentences
    # Split naive by period/line breaks; then join first 5 trimmed sentences ending with '.'
    raw = text.replace("\n", " ").strip()
    # Ensure periods are preserved for splitting
    sentences = [s.strip() for s in raw.split(".") if s.strip()]
    if len(sentences) == 0 and raw:
        # Fallback: split by semicolons or commas if no periods present
        for sep in [";", ","]:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            if parts:
                sentences = parts
                break
    normalized = []
    for s in sentences[:5]:
        if not s.endswith("."):
            s = s + "."
        normalized.append(s)
    # If fewer than 5 came back, pad with generic guidance
    while len(normalized) < 5:
        normalized.append("No further specific information available; exercise caution and follow local regulations.")

    return {"drone_name": name_clean, "sentences": normalized, "text": " ".join(normalized), "model": model_name}
