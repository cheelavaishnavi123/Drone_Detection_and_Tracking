#both rgb and ir
from __future__ import division  # Must be first
from inference_sdk import InferenceHTTPClient

# Initialize Roboflow Classification Client
CLIENT = InferenceHTTPClient(
    api_url="https://classify.roboflow.com",
    api_key="oo64LiCRWeP5aY7CKU27"  # Your API key
)


import sys
import os
import time
import warnings
warnings.filterwarnings("ignore")


# -------------------- Add parent folder to sys.path --------------------
project_root = os.path.dirname(os.path.abspath(__file__))  # Codes folder
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# -------------------- Add YOLOv5 folder to sys.path --------------------
yolov5_path = os.path.join(project_root, 'yolov5')
if yolov5_path not in sys.path:
    sys.path.insert(0, yolov5_path)

# -------------------- Add Tracking Wrapper folders --------------------
tracking_wrapper_path1 = os.path.join(project_root, 'tracking_wrapper', 'dronetracker')
tracking_wrapper_path2 = os.path.join(project_root, 'tracking_wrapper', 'drtracker')
if tracking_wrapper_path1 not in sys.path:
    sys.path.append(tracking_wrapper_path1)
if tracking_wrapper_path2 not in sys.path:
    sys.path.append(tracking_wrapper_path2)

# -------------------- Standard Imports --------------------
import queue
import pdb
import datetime
import argparse
import struct
import socket
import json
import threading
from PIL import Image
import cv2
import torch
from torch.utils.data import DataLoader
from torchvision import datasets
from torch.autograd import Variable
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.ticker import NullLocator
from collections import deque
import numpy as np

# -------------------- Custom Imports --------------------
from detect_wrapper.Detectoruav import DroneDetection
from detect_wrapper.utils.datasets import LoadStreams, LoadImages
from tracking_wrapper.dronetracker.trackinguav.evaluation.tracker import Tracker

# -------------------- Video Path & Settings --------------------
video_path = os.path.join(project_root, 'testvideo', 'multi_drone.mp4')
magnification = 1  # ✅ Keep original video size
print("Project root:", project_root)
print("Video path:", video_path)

# -------------------- Helper Function --------------------
def lefttop2center(bbx):
    obbx = [0, 0, bbx[2], bbx[3]]
    obbx[0] = bbx[0] + bbx[2] / 2
    obbx[1] = bbx[1] + bbx[3] / 2
    return obbx

# -------------------- Alert Function --------------------
class ContinuousBeep:
    """Manages continuous beeping while drone is detected"""
    def __init__(self):
        self.beeping = False
        self.beep_thread = None
        self.stop_event = threading.Event()
    
    def start_beep(self):
        """Start continuous beeping"""
        if self.beeping:
            return  # Already beeping
        self.beeping = True
        self.stop_event.clear()
        self.beep_thread = threading.Thread(target=self._beep_loop, daemon=True)
        self.beep_thread.start()
    
    def stop_beep(self):
        """Stop continuous beeping"""
        if not self.beeping:
            return  # Not beeping
        self.beeping = False
        self.stop_event.set()
        if self.beep_thread:
            self.beep_thread.join(timeout=0.5)
    
    def _beep_loop(self):
        """Continuous beep loop"""
        try:
            if os.name == 'nt':  # Windows
                import winsound
                while not self.stop_event.is_set():
                    winsound.Beep(800, 300)  # Lower frequency, longer beep
                    if self.stop_event.wait(timeout=0.1):
                        break
            else:  # Linux/Mac
                while not self.stop_event.is_set():
                    print('\a', end='', flush=True)
                    try:
                        os.system('beep -f 800 -l 300 2>/dev/null')
                    except:
                        pass
                    if self.stop_event.wait(timeout=0.4):
                        break
        except Exception:
            pass

# Global beep manager instance
_beep_manager = ContinuousBeep()

def alert_drone_detected(confidence=None, frame_num=None, start_continuous=False):
    """
    Alert function that triggers when a drone is detected.
    Plays a beep sound and prints an alert message.
    
    Args:
        confidence: Detection confidence value (optional)
        frame_num: Current frame number (optional)
        start_continuous: If True, start continuous beeping (default: False)
    """
    try:
        # Print alert message (only on first detection)
        if start_continuous:
            alert_msg = "\n" + "="*60
            alert_msg += "\n🚨 ALERT: DRONE DETECTED! 🚨"
            if confidence is not None:
                alert_msg += f"\nConfidence: {confidence:.2%}"
            if frame_num is not None:
                alert_msg += f"\nFrame: {frame_num}"
            alert_msg += "\n" + "="*60 + "\n"
            print(alert_msg)
            
            # Start continuous beeping
            _beep_manager.start_beep()
        else:
            # Single beep for non-continuous alerts
            try:
                if os.name == 'nt':  # Windows
                    import winsound
                    winsound.Beep(1000, 200)
                else:  # Linux/Mac
                    print('\a', end='', flush=True)
            except Exception:
                pass
    except Exception as e:
        # If alert fails, just print a simple message
        print(f"[ALERT] Drone detected! (confidence: {confidence})")

def stop_alert():
    """Stop continuous beeping"""
    _beep_manager.stop_beep()

# -------------------- BBox Utilities --------------------
def bbox_is_valid(bbx, frame_shape):
    if bbx is None:
        return False
    x, y, w, h = [int(v) for v in bbx]
    if w <= 0 or h <= 0:
        return False
    H, W = frame_shape[:2]
    if x >= W or y >= H:
        return False
    # allow partial out-of-bounds but not completely out
    if x + w <= 0 or y + h <= 0:
        return False
    return True

def bbox_iou(a, b):
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    inter_x1, inter_y1 = max(ax, bx), max(ay, by)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0, inter_x2 - inter_x1), max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0, aw) * max(0, ah)
    area_b = max(0, bw) * max(0, bh)
    union = area_a + area_b - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union

# -------------------- Simple Video Type Detection --------------------
def detect_video_type(frame):
    """
    Improved video type detection - check if it's grayscale or color
    """
    # Check if grayscale (1 channel)
    if len(frame.shape) == 2 or frame.shape[2] == 1:
        return "IR"
    
    # Check color variance - if all channels are very similar, it's likely IR
    mean_bgr = np.mean(frame, axis=(0, 1))
    diff_bgr = np.max(mean_bgr) - np.min(mean_bgr)
    
    # Check standard deviation of color channels
    std_bgr = np.std(frame, axis=(0, 1))
    std_diff = np.max(std_bgr) - np.min(std_bgr)
    
    # If color channels are almost identical in both mean and std, likely IR
    if diff_bgr < 15 and std_diff < 20:
        return "IR"
    
    # Additional check: if the image is mostly monochromatic
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(frame)
    
    # Calculate correlation between channels
    corr_bg = np.corrcoef(b.flatten(), g.flatten())[0, 1]
    corr_br = np.corrcoef(b.flatten(), r.flatten())[0, 1]
    corr_gr = np.corrcoef(g.flatten(), r.flatten())[0, 1]
    
    avg_corr = (corr_bg + corr_br + corr_gr) / 3
    
    # If channels are highly correlated, it's likely IR
    if avg_corr > 0.95:
        return "IR"
    
    return "RGB"

# -------------------- Main Test Function --------------------
def test(input_path=None, output_path=None, no_gui=False, progress_path=None):
    # Define both weight paths
    IRweights_path = os.path.join(project_root, 'detect_wrapper', 'weights', 'best.pt')
    RGBweights_path = os.path.join(project_root, 'detect_wrapper', 'weights', 'drone_rgb_yolov5s.pt')
    # RGBweights_path = os.path.join(os.path.dirname(project_root), 'checkpoints', 'drone_rgb_yolov5s.pt')
    
    time_record = []  # tracking time per frame
    det_time = []     # detection time per frame
    classification_results = []  # store (class_name, confidence)
    all_detection_confidences = []  # store all detection confidences for probability calculation
    drone_detected = False  # flag indicating if drone was detected at least once
    interval = 50
    vid_path = input_path if input_path is not None else video_path
    cap = cv2.VideoCapture(vid_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    processed_frames = 0
    # Dynamic estimate for sources where total_frames is unknown (0)
    estimated_total = total_frames if total_frames > 0 else 1000
    start_time = time.time()

    def write_progress(current_frames):
        if not progress_path:
            return
        try:
            nonlocal estimated_total
            # If we don't know total frames, grow a moving estimate so percent increases smoothly
            if total_frames <= 0:
                # Keep a buffer ahead so percent grows but does not reach 100 prematurely
                buffer_ahead = 200
                estimated_total = max(estimated_total, current_frames + buffer_ahead)
                denom = max(1, estimated_total)
            else:
                denom = total_frames
            percent = int(min(99 if current_frames < denom else 100,
                              max(0, round((current_frames / denom) * 100))))
            elapsed = max(0.0, time.time() - start_time)
            fps_est = (current_frames / elapsed) if elapsed > 0 else 0.0
            eta_sec = None
            if fps_est > 0 and percent < 100:
                remaining = max(0, denom - current_frames)
                eta_sec = int(round(remaining / fps_est))
            payload = {
                "percent": percent,
                "processed": int(current_frames),
                "total": int(total_frames if total_frames > 0 else estimated_total)
            }
            if eta_sec is not None:
                payload["eta_seconds"] = eta_sec
            with open(progress_path, 'w', encoding='utf-8') as pf:
                json.dump(payload, pf)
        except Exception:
            pass
    
    ret, frame = cap.read()
    if not ret:
        print("Error: Cannot read video file.")
        return

    oframe = frame.copy()
    processed_frames = 1
    write_progress(processed_frames)
    # Optional video writer if output_path provided
    writer = None
    out_path = output_path
    if out_path is not None:
        # Prefer H.264 ('avc1') for browser compatibility; fall back to 'mp4v'
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        height, width = frame.shape[:2]
        try:
            fourcc_avc1 = cv2.VideoWriter_fourcc(*'avc1')
            test_writer = cv2.VideoWriter(out_path, fourcc_avc1, fps, (width, height))
            if test_writer.isOpened():
                writer = test_writer
            else:
                raise RuntimeError('avc1 not available')
        except Exception:
            fourcc_mp4v = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(out_path, fourcc_mp4v, fps, (width, height))
    # Initialize detection and tracking
    drone_det = DroneDetection(IRweights_path=IRweights_path, RGBweights_path=RGBweights_path)
    drone_tracker = Tracker()
    first_track = True
    last_detect_box = None
    frames_since_last_detection = 0
    classified_once = False  # ensure we classify only once at first detection
    alert_triggered = False  # flag to track if alert has been triggered

    # Agent policy parameters
    iou_threshold = 0.3       # if detector vs tracker IOU below this, reinit
    min_tracking_confidence = 0.4  # minimum confidence to keep tracking
    max_frames_without_detection = 30  # max frames to track without re-checking
    
    # Agent decides video type from first frame
    mode = detect_video_type(frame)
    print(f"[INFO] Detected video type: {mode}")
    
    # Manual override option - uncomment and set to "RGB" or "IR" if auto-detection fails
    # mode = "RGB"  # Force RGB mode
    # mode = "IR"   # Force IR mode

    exit_flag = False
    while ret and not exit_flag:
        t1 = time.time()
        # Use appropriate weights based on video type
        if mode == "RGB":
            detections = drone_det.forward_RGB(frame)
        else:
            detections = drone_det.forward_IR(frame)
        t2 = time.time()
        det_time.append(t2 - t1)

        # Process all detections
        visuframe = oframe.copy()
        valid_detections = []
        drone_in_current_frame = False  # Track if drone is detected in this frame
        
        for init_box, det_conf in detections:
            if det_conf > 0.4:  # Lower threshold for better detection
                valid_detections.append((init_box, det_conf))
                all_detection_confidences.append(det_conf)  # Track all detection confidences
                was_detected_before = drone_detected
                drone_detected = True  # Mark that drone was detected
                drone_in_current_frame = True  # Drone is in current frame
                bbx = [int(x) for x in init_box]
                print(f"Detection BB: {bbx} (conf: {det_conf:.2f})")
                
                # Start continuous beep on first detection
                if not was_detected_before:
                    alert_drone_detected(confidence=det_conf, frame_num=processed_frames, start_continuous=True)
                    alert_triggered = True
                
                # Draw bounding box for each detection
                cv2.rectangle(visuframe, (bbx[0], bbx[1]), 
                              (bbx[0] + bbx[2], bbx[1] + bbx[3]), (0, 255, 0), 2)
                cv2.putText(visuframe, f'Drone {det_conf:.2f}', (bbx[0], bbx[1] - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                # Classification: only once at first detection (no on-frame display)
                if not classified_once:
                    try:
                        x1, y1, w, h = bbx
                        x2, y2 = x1 + w, y1 + h
                        H, W = frame.shape[:2]
                        # clamp crop to frame bounds
                        x1c = max(0, min(W - 1, x1))
                        y1c = max(0, min(H - 1, y1))
                        x2c = max(0, min(W, x2))
                        y2c = max(0, min(H, y2))
                        if x2c > x1c and y2c > y1c:
                            crop = frame[y1c:y2c, x1c:x2c]
                            temp_path = "drone_crop.jpg"
                            cv2.imwrite(temp_path, crop)
                            result = CLIENT.infer(temp_path, model_id="drone-fsixa/2")
                            if "predictions" in result and len(result["predictions"]) > 0:
                                pred = result["predictions"][0]
                                class_name = pred.get("class", "unknown")
                                confidence = float(pred.get("confidence", 0.0))
                                classification_results.append((class_name, confidence))
                                print(f"[CLASSIFY] Stored result: {class_name} ({confidence:.2f})")
                            else:
                                print("[CLASSIFY] No predictions returned from Roboflow")
                        else:
                            print("[CLASSIFY] Skipped crop: invalid bbox after clamping")
                        classified_once = True
                    except Exception as e:
                        print(f"[CLASSIFY] Error during classification: {e}")
                   
        
        # Use the highest confidence detection for tracking
        if valid_detections:
            # Ensure beeping continues while drone is detected
            if not _beep_manager.beeping:
                best_conf = max(valid_detections, key=lambda x: x[1])[1]
                alert_drone_detected(confidence=best_conf, frame_num=processed_frames, start_continuous=True)
            
            # Sort by confidence and use the best one for tracking
            best_detection = max(valid_detections, key=lambda x: x[1])
            init_box, det_conf = best_detection
            
            if first_track:
                drone_tracker.init_track(init_box, frame)
                first_track = False
            else:
                drone_tracker.change_state(init_box)

            last_detect_box = [int(x) for x in init_box]
            last_det_conf = det_conf
            frames_since_last_detection = 0
            
            if writer is not None:
                writer.write(visuframe)
            if not no_gui:
                cv2.imshow("tracking", visuframe)
                key = cv2.waitKey(30) & 0xFF  # Increased wait time for better video playback
                if key == ord('q') or key == 27:  # 'q' or ESC to quit
                    exit_flag = True
                    break
        else:
            # No drone detected in this frame - stop beeping
            stop_alert()
            # Add "No Drone Detected" caption when no drone is found
            visuframe = oframe.copy()
            text = "No Drone Detected"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 1.0
            color = (0, 0, 255)  # Red color
            thickness = 2
            
            # Get text size for centering
            (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            frame_height, frame_width = visuframe.shape[:2]
            
            # Center the text
            x = (frame_width - text_width) // 2
            y = (frame_height + text_height) // 2
            
            # Add background rectangle for better visibility
            padding = 10
            cv2.rectangle(visuframe, 
                        (x - padding, y - text_height - padding), 
                        (x + text_width + padding, y + baseline + padding), 
                        (255, 255, 255), -1)
            
            # Add the text
            cv2.putText(visuframe, text, (x, y), font, font_scale, color, thickness)
            if writer is not None:
                writer.write(visuframe)
            if not no_gui:
                cv2.imshow("tracking", visuframe)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # 'q' or ESC to quit
                    exit_flag = True
                    break

        # Read next frame for main loop
        ret, frame = cap.read()
        if not ret:
            break
        processed_frames += 1
        write_progress(processed_frames)
            
        # Only do tracking if a drone was detected and tracker was initialized
        if not first_track and not exit_flag:
            num = 0
            force_redetect = False
            while num < interval and not exit_flag and not force_redetect:
                num += 1
                frames_since_last_detection += 1
                ret, frame = cap.read()
                if not ret:
                    exit_flag = True
                    break
                oframe = frame.copy()
                visuframe = oframe.copy()
                processed_frames += 1
                write_progress(processed_frames)
                t1 = time.time()
                try:
                    outputs = drone_tracker.on_track(frame)
                    t2 = time.time()
                    time_record.append(t2 - t1)

                    bbx = [int(i) for i in outputs]
                    if not bbox_is_valid(bbx, frame.shape):
                        # invalid tracking -> trigger re-detect, stop beeping
                        force_redetect = True
                        stop_alert()
                        print("[AGENT] Tracker bbox invalid, switching to detection")
                        break

                    # Drone is being tracked successfully - ensure beep continues
                    if not _beep_manager.beeping:
                        _beep_manager.start_beep()
                    
                    print("Tracking BB:", bbx)
                    cv2.rectangle(visuframe, (bbx[0], bbx[1]),
                                  (bbx[0] + bbx[2], bbx[1] + bbx[3]), (0, 255, 0), 2)
                    cv2.putText(visuframe, 'Drone', (bbx[0], bbx[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Add model indicator
                    model_text = f"Weights: {mode}"
                    cv2.putText(visuframe, model_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    cv2.putText(visuframe, model_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

                    # Dynamic confidence-based switching - only check when needed
                    should_check_detector = (
                        frames_since_last_detection >= max_frames_without_detection or  # Too long without detection
                        last_det_conf < min_tracking_confidence  # Last detection was low confidence
                    )
                    
                    if should_check_detector:
                        try:
                            detections = (drone_det.forward_RGB(frame) if mode == "RGB" else drone_det.forward_IR(frame))
                        except Exception:
                            detections = []
                        
                        # Find the best detection that overlaps with current tracking
                        best_detection = None
                        best_iou = 0
                        for det_box, det_conf in detections:
                            if bbox_is_valid(det_box, frame.shape) and det_conf > 0.4:
                                all_detection_confidences.append(det_conf)  # Track all detection confidences
                                was_detected_before = drone_detected
                                drone_detected = True  # Mark that drone was detected
                                # Ensure beeping continues if drone is re-detected
                                if not _beep_manager.beeping:
                                    alert_drone_detected(confidence=det_conf, frame_num=processed_frames, start_continuous=True)
                                    alert_triggered = True
                                elif not was_detected_before:
                                    # First time detecting - start beep
                                    alert_drone_detected(confidence=det_conf, frame_num=processed_frames, start_continuous=True)
                                    alert_triggered = True
                                iou = bbox_iou(bbx, det_box)
                                if iou > best_iou:
                                    best_iou = iou
                                    best_detection = (det_box, det_conf)
                        
                        if best_detection is not None:
                            det_box, det_conf = best_detection
                            # Switch to detection if: high confidence OR poor IOU OR very low tracking confidence
                            if det_conf >= 0.7 or best_iou < iou_threshold or last_det_conf < 0.2:
                                print(f"[AGENT] Switch to detection (det_conf={det_conf:.2f}, IOU={best_iou:.2f}, last_conf={last_det_conf:.2f})")
                                force_redetect = True
                                break
                            else:
                                # Update tracking with better detection if available
                                if det_conf > last_det_conf:
                                    print(f"[AGENT] Update tracker with better detection (conf={det_conf:.2f})")
                                    drone_tracker.change_state(det_box)
                                    last_detect_box = [int(v) for v in det_box]
                                    last_det_conf = det_conf
                                    frames_since_last_detection = 0
                        else:
                            # No good detection found, keep tracking
                            print(f"[AGENT] No good detection found, continuing tracking")
                except Exception as e:
                    print(f"Tracking error: {e}")
                    # Stop beeping on tracking error
                    stop_alert()
                    # Show "No Drone Detected" when tracking fails
                    text = "No Drone Detected"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 1.0
                    color = (0, 0, 255)  # Red color
                    thickness = 2
                    
                    # Get text size for centering
                    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
                    frame_height, frame_width = visuframe.shape[:2]
                    
                    # Center the text
                    x = (frame_width - text_width) // 2
                    y = (frame_height + text_height) // 2
                    
                    # Add background rectangle for better visibility
                    padding = 10
                    cv2.rectangle(visuframe, 
                                (x - padding, y - text_height - padding), 
                                (x + text_width + padding, y + baseline + padding), 
                                (255, 255, 255), -1)
                    
                    # Add the text
                    cv2.putText(visuframe, text, (x, y), font, font_scale, color, thickness)
                
                # Add model indicator
                model_text = f"Weights: {mode}"
                cv2.putText(visuframe, model_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                cv2.putText(visuframe, model_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                if writer is not None:
                    writer.write(visuframe)
                if not no_gui:
                    cv2.imshow("tracking", visuframe)
                    key = cv2.waitKey(30) & 0xFF  # Increased wait time for better video playback
                    if key == ord('q') or key == 27:  # 'q' or ESC to quit
                        break

            # if agent requested redetect, continue outer loop to run detector again
            if force_redetect:
                first_track = False  # keep tracker instance but we will re-detect next outer step

    cap.release()
    if writer is not None:
        writer.release()
    cv2.destroyAllWindows()
    
    # Stop beeping at end of processing
    stop_alert()

    # ------- Summary Report -------
    avg_track = float(np.array(time_record).mean()) if len(time_record) > 0 else 0.0
    avg_detect = float(np.array(det_time).mean()) if len(det_time) > 0 else 0.0
    print("Done......")
    print(f"Average tracking time per frame: {avg_track:.6f} sec")
    print(f"Average detection time per frame: {avg_detect:.6f} sec")

    final_cls = None
    if classification_results:
        # choose highest confidence as final classification
        final_cls = max(classification_results, key=lambda x: x[1])
    if final_cls is not None:
        cname, cconf = final_cls
        print(f"Final classification: {cname} ({cconf:.4f})")
    else:
        print("Final classification: None")

    # Save metrics JSON alongside output if applicable
    if out_path is not None:
        try:
            # Calculate probability score (0-100) from detection confidences
            detection_probability = 0
            if all_detection_confidences:
                # Use average confidence as the probability score
                avg_confidence = float(np.array(all_detection_confidences).mean())
                detection_probability = int(round(avg_confidence * 100))
            elif classification_results:
                # Fallback to classification confidence if no detections but we have classification
                detection_probability = int(round(final_cls[1] * 100)) if final_cls else 0
            
            metrics = {
                "average_tracking_time_sec": avg_track,
                "average_detection_time_sec": avg_detect,
                "final_classification": {
                    "class": cname if final_cls is not None else None,
                    "confidence": cconf if final_cls is not None else None
                },
                "video_type": mode,
                "drone_detected": drone_detected,
                "detection_probability": detection_probability
            }
            metrics_path = out_path + ".json"
            with open(metrics_path, 'w', encoding='utf-8') as f:
                json.dump(metrics, f)
            print(f"Metrics saved: {metrics_path}")
            print(f"Drone detected: {drone_detected}, Probability: {detection_probability}%")
        except Exception as e:
            print(f"Failed to save metrics JSON: {e}")

    # Ensure 100% at end
    write_progress(total_frames if total_frames > 0 else processed_frames + 1)


# -------------------- Run --------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drone detection and tracking")
    parser.add_argument("--input", type=str, default=None, help="Input video path")
    parser.add_argument("--output", type=str, default=None, help="Output video path (MP4)")
    parser.add_argument("--no-gui", action="store_true", help="Disable GUI windows during processing")
    parser.add_argument("--progress", type=str, default=None, help="Path to write progress JSON")
    args = parser.parse_args()
    test(input_path=args.input, output_path=args.output, no_gui=args.no_gui, progress_path=args.progress)




















# #RGB 1
# -------------------- Fixed demo_detect_track.py --------------------
# from __future__ import division  # Must be first
# import sys
# import os
# import time
# import warnings
# warnings.filterwarnings("ignore")

# # -------------------- Add parent folder to sys.path --------------------
# project_root = os.path.dirname(os.path.abspath(__file__))  # Codes folder
# if project_root not in sys.path:
#     sys.path.insert(0, project_root)

# # -------------------- Add YOLOv5 folder to sys.path --------------------
# yolov5_path = os.path.join(project_root, 'yolov5')
# if yolov5_path not in sys.path:
#     sys.path.insert(0, yolov5_path)

# # -------------------- Add Tracking Wrapper folders --------------------
# tracking_wrapper_path1 = os.path.join(project_root,'tracking_wrapper','dronetracker')
# tracking_wrapper_path2 = os.path.join(project_root,'tracking_wrapper','drtracker')
# if tracking_wrapper_path1 not in sys.path:
#     sys.path.append(tracking_wrapper_path1)
# if tracking_wrapper_path2 not in sys.path:
#     sys.path.append(tracking_wrapper_path2)

# # -------------------- Standard Imports --------------------
# import queue
# import pdb
# import datetime
# import argparse
# import struct
# import socket
# import json
# from PIL import Image
# import cv2
# import torch
# from torch.utils.data import DataLoader
# from torchvision import datasets
# from torch.autograd import Variable
# import matplotlib.pyplot as plt
# import matplotlib.patches as patches
# from matplotlib.ticker import NullLocator
# from collections import deque
# import numpy as np

# # -------------------- Custom Imports --------------------
# from detect_wrapper.Detectoruav import DroneDetection
# from detect_wrapper.utils.datasets import LoadStreams, LoadImages
# from tracking_wrapper.dronetracker.trackinguav.evaluation.tracker import Tracker

# # -------------------- Video Path & Settings --------------------
# video_path = os.path.join(project_root, 'testvideo', 'n20.mp4')
# magnification = 2

# # -------------------- Helper Function --------------------
# def lefttop2center(bbx):
#     obbx = [0, 0, bbx[2], bbx[3]]
#     obbx[0] = bbx[0] + bbx[2] / 2
#     obbx[1] = bbx[1] + bbx[3] / 2
#     return obbx

# # -------------------- Main Test Function --------------------
# def test():
#     # IR weights (you can leave as is)
#     IRweights_path = os.path.join(project_root, 'detect_wrapper', 'weights', 'best.pt')
    
#     # RGB-trained YOLOv5 weights (your new model)
#     RGBweights_path = os.path.join(os.path.dirname(project_root), 'checkpoints', 'drone_rgb_yolov5s.pt')
    
#     time_record = []
#     det_time = []
#     interval = 50
#     cap = cv2.VideoCapture(video_path)
    
#     ret, frame = cap.read()
#     if not ret:
#         print("Error: Cannot read video file.")
#         return

#     oframe = frame.copy()
#     # Pass both IR and RGB weights to DroneDetection
#     drone_det = DroneDetection(IRweights_path=IRweights_path, RGBweights_path=RGBweights_path)
#     drone_tracker = Tracker()
#     first_track = True

#     while ret:
#         t1 = time.time()
#         # Use RGB forward function instead of IR if you want RGB detection
#         init_box = drone_det.forward_RGB(frame)  # <-- changed from forward_IR()
#         t2 = time.time()
#         det_time.append(t2 - t1)

#         if init_box is not None:
#             if first_track:
#                 drone_tracker.init_track(init_box, frame)
#                 first_track = False
#             else:
#                 drone_tracker.change_state(init_box)

#             bbx = [int(x) for x in init_box]
#             print("Detection BB:", bbx)

#             visuframe = cv2.resize(oframe,
#                                     (oframe.shape[1]*magnification, oframe.shape[0]*magnification),
#                                     cv2.INTER_LINEAR)
#             bbx = [i*magnification for i in bbx]
#             cv2.rectangle(visuframe, (bbx[0], bbx[1]), (bbx[0]+bbx[2], bbx[1]+bbx[3]), (0, 255, 0), 2)
#             cv2.imshow("tracking", visuframe)
#             cv2.waitKey(1)

#         num = 0
#         while num < interval:
#             num += 1
#             ret, frame = cap.read()
#             if not ret:
#                 break
#             oframe = frame.copy()
#             visuframe = cv2.resize(oframe,
#                                     (oframe.shape[1]*magnification, oframe.shape[0]*magnification),
#                                     cv2.INTER_LINEAR)
#             t1 = time.time()
#             outputs = drone_tracker.on_track(frame)
#             t2 = time.time()
#             time_record.append(t2 - t1)
#             bbx = [i*magnification for i in outputs]
#             print("Tracking BB:", bbx)
#             cv2.rectangle(visuframe,(bbx[0],bbx[1]),(bbx[0]+bbx[2],bbx[1]+bbx[3]),(0,255,0),2)
#             cv2.imshow("tracking", visuframe)
#             cv2.waitKey(1)

#     cap.release()
#     cv2.destroyAllWindows()
#     print("Done......")
#     print('Track average time:', np.array(time_record).mean())
#     print('Detect average time:', np.array(det_time).mean())

# # -------------------- Run --------------------
# if __name__ == "__main__":
#     test()








































# # -------------------- Fixed demo_detect_track.py --------------------
# from __future__ import division  # Must be first
# import sys
# import os
# import time
# import warnings
# warnings.filterwarnings("ignore")

# # -------------------- Add parent folder to sys.path --------------------
# # This allows 'detect_wrapper' to be imported
# project_root = os.path.dirname(os.path.abspath(__file__))  # Codes folder
# if project_root not in sys.path:
#     sys.path.insert(0, project_root)

# # -------------------- Add YOLOv5 folder to sys.path --------------------
# yolov5_path = os.path.join(project_root, 'yolov5')
# if yolov5_path not in sys.path:
#     sys.path.insert(0, yolov5_path)

# # -------------------- Add Tracking Wrapper folders --------------------
# tracking_wrapper_path1 = os.path.join(project_root,'tracking_wrapper','dronetracker')
# tracking_wrapper_path2 = os.path.join(project_root,'tracking_wrapper','drtracker')
# if tracking_wrapper_path1 not in sys.path:
#     sys.path.append(tracking_wrapper_path1)
# if tracking_wrapper_path2 not in sys.path:
#     sys.path.append(tracking_wrapper_path2)

# # -------------------- Standard Imports --------------------
# import queue
# import pdb
# import datetime
# import argparse
# import struct
# import socket
# import json
# from PIL import Image
# import cv2
# import torch
# from torch.utils.data import DataLoader
# from torchvision import datasets
# from torch.autograd import Variable
# import matplotlib.pyplot as plt
# import matplotlib.patches as patches
# from matplotlib.ticker import NullLocator
# from collections import deque
# import numpy as np

# # -------------------- Custom Imports --------------------
# from detect_wrapper.Detectoruav import DroneDetection
# from detect_wrapper.utils.datasets import LoadStreams, LoadImages
# from tracking_wrapper.dronetracker.trackinguav.evaluation.tracker import Tracker

# # -------------------- Video Path & Settings --------------------
# video_path = os.path.join(project_root, 'testvideo', 'n19.mp4')
# magnification = 2

# # -------------------- Helper Function --------------------
# def lefttop2center(bbx):
#     obbx = [0, 0, bbx[2], bbx[3]]
#     obbx[0] = bbx[0] + bbx[2] / 2
#     obbx[1] = bbx[1] + bbx[3] / 2
#     return obbx

# # -------------------- Main Test Function --------------------
# def test():
#     IRweights_path = os.path.join(project_root, 'detect_wrapper', 'weights', 'best.pt')
#     time_record = []
#     det_time = []
#     interval = 50
#     cap = cv2.VideoCapture(video_path)
    
#     ret, frame = cap.read()
#     if not ret:
#         print("Error: Cannot read video file.")
#         return

#     oframe = frame.copy()
#     drone_det = DroneDetection(IRweights_path=IRweights_path, RGBweights_path=IRweights_path)
#     drone_tracker = Tracker()
#     first_track = True

#     while ret:
#         t1 = time.time()
#         init_box = drone_det.forward_IR(frame)
#         t2 = time.time()
#         det_time.append(t2 - t1)

#         if init_box is not None:
#             if first_track:
#                 drone_tracker.init_track(init_box, frame)
#                 first_track = False
#             else:
#                 drone_tracker.change_state(init_box)

#             bbx = [int(x) for x in init_box]
#             print("Detection BB:", bbx)

#             visuframe = cv2.resize(oframe,
#                                     (oframe.shape[1]*magnification, oframe.shape[0]*magnification),
#                                     cv2.INTER_LINEAR)
#             bbx = [i*magnification for i in bbx]
#             cv2.rectangle(visuframe, (bbx[0], bbx[1]), (bbx[0]+bbx[2], bbx[1]+bbx[3]), (0, 255, 0), 2)
#             cv2.imshow("tracking", visuframe)
#             cv2.waitKey(1)

#         num = 0
#         while num < interval:
#             num += 1
#             ret, frame = cap.read()
#             if not ret:
#                 break
#             oframe = frame.copy()
#             visuframe = cv2.resize(oframe,
#                                     (oframe.shape[1]*magnification, oframe.shape[0]*magnification),
#                                     cv2.INTER_LINEAR)
#             t1 = time.time()
#             outputs = drone_tracker.on_track(frame)
#             t2 = time.time()
#             time_record.append(t2 - t1)
#             bbx = [i*magnification for i in outputs]
#             print("Tracking BB:", bbx)
#             cv2.rectangle(visuframe,(bbx[0],bbx[1]),(bbx[0]+bbx[2],bbx[1]+bbx[3]),(0,255,0),2)
#             cv2.imshow("tracking", visuframe)
#             cv2.waitKey(1)

#     cap.release()
#     cv2.destroyAllWindows()
#     print("Done......")
#     print('Track average time:', np.array(time_record).mean())
#     print('Detect average time:', np.array(det_time).mean())

# # -------------------- Run --------------------
# if __name__ == "__main__":
#     test()




# from __future__ import division

# import sys
# import os

# # Path to YOLOv5 folder
# yolov5_path = os.path.join(os.path.dirname(__file__), 'yolov5')
# sys.path.insert(0, yolov5_path)

# import sys

# import queue
# import pdb
# import os
# import time
# import datetime
# import argparse
# import struct
# import socket
# import json
# from PIL import Image
# import cv2
# import torch
# from torch.utils.data import DataLoader
# from torchvision import datasets
# from torch.autograd import Variable
# import matplotlib.pyplot as plt
# import matplotlib.patches as patches
# from matplotlib.ticker import NullLocator
# from collections import deque
# import numpy as np
# from detect_wrapper.Detectoruav import DroneDetection
# from tracking_wrapper.dronetracker.trackinguav.evaluation.tracker import Tracker

# # sys.path.append((os.path.dirname(__file__)))
# sys.path.append(os.path.join(os.path.dirname(__file__),'detect_wrapper'))
# sys.path.append(os.path.join(os.path.dirname(__file__),'tracking_wrapper\\dronetracker'))
# sys.path.append(os.path.join(os.path.dirname(__file__),'tracking_wrapper\\drtracker'))




# ## Input video
# video_path = os.path.join(os.path.dirname(__file__),'testvideo\\n19.mp4');

# magnification = 2

# import warnings
# warnings.filterwarnings("ignore")

# # IP, Port = 0, 0
# # IP = "192.168.0.139"
# # Port = 9874
# # AF_INET, SOCK_DGRAM = socket.AF_INET, socket.SOCK_DGRAM
# # udp_socket = socket.socket(AF_INET, SOCK_DGRAM)
# # udp_socket.bind(("",9921))

# def lefttop2center(bbx):
#     obbx=[0,0,bbx[2],bbx[3]]
#     obbx[0]=bbx[0]+bbx[2]/2
#     obbx[1]=bbx[1]+bbx[3]/2
#     return obbx

# # class  DroneTracker():
# #     def __init__(self):
# #         self.tracker = drtracker.CorrFilterTracker(False, True, True)
        
# #     def init_track(self, init_box, init_frame):
# #         self.tracker.init(init_box, init_frame)
# #     def on_track(self, frame):
# #         boundingbox = self.tracker.update(frame)
# #         boundingbox = [int(x) for x in boundingbox]
# #         return boundingbox

# def test():
#     IRweights_path = os.path.join(os.path.split(os.path.abspath(__file__))[0],'detect_wrapper\\weights\\best.pt');
#     # spdb.set_trace()
#     time_record=[]
#     det_time=[]
#     interval=50
#     cap = cv2.VideoCapture(video_path)
    
#     # vw= VideoWriter("/home/dell/Project_UAV/result/result.avi", fps=30)
#     ret, frame = cap.read()
#     print(frame.shape)
#     # pdb.set_trace()
#     oframe = frame.copy()
#     drone_det=DroneDetection(IRweights_path=IRweights_path, RGBweights_path=IRweights_path)
#     drone_tracker =Tracker()  #DroneTracker()
#     first_track=True
#     while(ret):
#         t1=time.time()
        
#         init_box=drone_det.forward_IR(frame)
#         t2=time.time()
#         det_time.append(t2-t1)
#         # if vw is not None:
#         #     vw.write(oframe)
#         if init_box is not None:
#             if first_track:
#                 drone_tracker.init_track(init_box,frame)
#                 # first_track=False
#             else:
#                 drone_tracker.change_state(init_box)
#             bbx = [int(x) for x in init_box]
#             print(bbx)
            
#             # cv2.rectangle(oframe,(bbx[0],bbx[1]), (bbx[0]+bbx[2],bbx[1]+bbx[3]), (0,255,0), 2)
#             # cv2.imshow("tracking", oframe)
#             # cv2.waitKey(1)

#             visuframe = cv2.resize(oframe, (oframe.shape[1]*magnification, oframe.shape[0]*magnification), cv2.INTER_LINEAR)
#             bbx=[i*magnification for i in bbx]
#             cv2.rectangle(oframe,(bbx[0],bbx[1]), (bbx[0]+bbx[2],bbx[1]+bbx[3]), (0,255,0), 2)
#             cv2.imshow("tracking", visuframe)
#             cv2.waitKey(1)
            
#         num=0
#         while(num<interval):
#             num=num+1
#             ret, frame = cap.read()
            

#             if ret:
#                 oframe = frame.copy()
#                 visuframe = cv2.resize(oframe, (oframe.shape[1]*magnification, oframe.shape[0]*magnification), cv2.INTER_LINEAR)
#                 t1=time.time()
#                 outputs=drone_tracker.on_track(frame) 
#                 t2=time.time()
#                 time_record.append(t2-t1)
#                 bbx=[i*magnification for i in outputs]
#                 print(bbx)

#                 cv2.rectangle(visuframe,(bbx[0],bbx[1]), (bbx[0]+bbx[2],bbx[1]+bbx[3]), (0,255,0), 2)
                
#                 cv2.imshow("tracking", visuframe)
#                 cv2.waitKey(1)
#                 # if vw is not None:
#                 #     vw.write(oframe)     
#     cap.release()
#     # if vw is not None:
#     #     vw.release()
#     cv2.destroyAllWindows()
#     print("done......")
#     print('track average time:',np.array(time_record).mean())
#     print('detect average time:',np.array(det_time).mean())
    
# if __name__=="__main__":
#     test()
