"""
DEVMATE - Face Recognition Module
For access control and identity verification.
"""
import logging
import time
import os
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

class FaceRecognitionModule:
    def __init__(self, data_dir: Path, output_callback=None):
        self._output_cb = output_callback or (lambda msg: logger.info("[FACE] %s", msg))
        self.data_dir = Path(data_dir)
        self.reference_image_path = self.data_dir / "reference_face.jpg"
        
        try:
            import cv2
            from deepface import DeepFace
            self.cv2 = cv2
            self.DeepFace = DeepFace
            self.available = True
        except ImportError:
            self._emit("opencv-python or deepface not installed. Security disabled.")
            self.available = False
            
    def _emit(self, msg: str):
        if self._output_cb:
            self._output_cb(msg)

    def is_registered(self) -> bool:
        return self.reference_image_path.exists()

    def capture_reference(self) -> Tuple[bool, str]:
        if not self.available:
            return False, "Dependencies not installed. Setup deepface and opencv."
            
        self._emit("Starting camera for face registration...")
        cap = self.cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "Could not open webcam."
            
        success = False
        message = "Canceled or failed."
        start_time = time.time()
        
        # Capture for up to 15 seconds
        while time.time() - start_time < 15:
            ret, frame = cap.read()
            if not ret:
                continue
                
            elapsed = time.time() - start_time
            
            # Verify once every 2 seconds to not freeze frame forever
            if int(elapsed * 2) % 4 == 0:
                temp_path = str(self.data_dir / "temp_reg.jpg")
                self.cv2.imwrite(temp_path, frame)
                
                try:
                    # verify if a face can be extracted
                    faces = self.DeepFace.extract_faces(img_path=temp_path, enforce_detection=True)
                    if faces:
                        self.cv2.imwrite(str(self.reference_image_path), frame)
                        success = True
                        message = "Face registered successfully!"
                        self._emit("Face reference saved.")
                        break
                except ValueError:
                    pass # no face found
                    
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            
            # UI
            h, w = frame.shape[:2]
            scan_y = int((time.time() * 300) % h)
            self.cv2.line(frame, (0, scan_y), (w, scan_y), (255, 100, 0), 2)
            self.cv2.putText(frame, "DevMate Security - Registering...", (50, 50), 
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            self.cv2.imshow('DevMate Security Protocol', frame)
            
            if self.cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
        cap.release()
        self.cv2.destroyAllWindows()
        if os.path.exists(str(self.data_dir / "temp_reg.jpg")):
            os.remove(str(self.data_dir / "temp_reg.jpg"))
            
        return success, message

    def authenticate(self, timeout: int = 15) -> Tuple[bool, str]:
        """Attempt to authenticate by comparing the webcam with the stored reference face."""
        if not self.available:
            return True, "Face recognition disabled (dependencies missing), bypassing security."
            
        if not self.is_registered():
            return False, "No reference face registered."
            
        self._emit("Starting camera for authentication...")
        cap = self.cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "Could not open webcam."
            
        start_time = time.time()
        authenticated = False
        checked = False
        message = "Access Denied."
        scan_duration = 5.0  # Exact scan duration per user request
        
        while time.time() - start_time < scan_duration:
            ret, frame = cap.read()
            if not ret:
                continue
                
            elapsed = time.time() - start_time
            
            # Run DeepFace check around 1.5s mark to ensure camera exposure is settled
            # Do it only once to not block UI forever
            if elapsed > 1.5 and not checked:
                temp_path = str(self.data_dir / "temp_auth.jpg")
                self.cv2.imwrite(temp_path, frame)
                try:
                    self._emit("Verifying...")
                    result = self.DeepFace.verify(
                        img1_path=str(self.reference_image_path),
                        img2_path=temp_path,
                        enforce_detection=False,
                        model_name="VGG-Face"
                    )
                    if result.get("verified", False):
                        authenticated = True
                        message = "Access Granted! Welcome back."
                    checked = True
                except Exception as e:
                    self._emit(f"Verification issue: {e}")
                    checked = True
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            
            # --- Graphical User Interface ---
            h, w = frame.shape[:2]
            
            # Scanning laser line
            scan_y = int((time.time() * 300) % h)
            self.cv2.line(frame, (0, scan_y), (w, scan_y), (0, 255, 0), 2)
            
            # Top-left info box
            self.cv2.putText(frame, "DEVMATE SECURITY SYSTEM", (20, 30),
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                             
            status_text = "SCANNING..."
            color = (0, 165, 255) # Orange
            if checked:
                if authenticated:
                    status_text = "ACCESS IDENTIFIED"
                    color = (0, 255, 0) # Green
                else:
                    status_text = "ACCESS DENIED"
                    color = (0, 0, 255) # Red
                    
            self.cv2.putText(frame, status_text, (20, 70), 
                             self.cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
                             
            progress = min(100, (elapsed / scan_duration) * 100)
            self.cv2.putText(frame, f"Analysis: {progress:.0f}%", (20, 110), 
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                             
            # Draw HUD reticle targeting
            cx, cy = int(w/2), int(h/2)
            c_size = 150
            self.cv2.line(frame, (cx-c_size, cy-c_size), (cx-c_size+40, cy-c_size), color, 3)
            self.cv2.line(frame, (cx-c_size, cy-c_size), (cx-c_size, cy-c_size+40), color, 3)
            self.cv2.line(frame, (cx+c_size, cy-c_size), (cx+c_size-40, cy-c_size), color, 3)
            self.cv2.line(frame, (cx+c_size, cy-c_size), (cx+c_size, cy-c_size+40), color, 3)
            self.cv2.line(frame, (cx-c_size, cy+c_size), (cx-c_size+40, cy+c_size), color, 3)
            self.cv2.line(frame, (cx-c_size, cy+c_size), (cx-c_size, cy+c_size-40), color, 3)
            self.cv2.line(frame, (cx+c_size, cy+c_size), (cx+c_size-40, cy+c_size), color, 3)
            self.cv2.line(frame, (cx+c_size, cy+c_size), (cx+c_size, cy+c_size-40), color, 3)
            
            # Center target
            self.cv2.circle(frame, (cx, cy), 15, color, 1)

            # Audio Effect
            if os.name == 'nt':
                try:
                    import winsound
                    time_sec = int(elapsed * 5)
                    play_flag = getattr(self, "_last_beep", -1)
                    if time_sec != play_flag:
                        self._last_beep = time_sec
                        # Small quick beep
                        winsound.Beep(1200 if authenticated else 800, 20)
                except Exception:
                    pass

            self.cv2.imshow('DevMate Security Protocol', frame)
            
            if self.cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
        # Make sure deepface check ran
        if not checked:
            temp_path = str(self.data_dir / "temp_auth.jpg")
            ret, frame = cap.read()
            if ret:
                self.cv2.imwrite(temp_path, frame)
                try:
                    result = self.DeepFace.verify(
                        img1_path=str(self.reference_image_path),
                        img2_path=temp_path,
                        enforce_detection=False,
                        model_name="VGG-Face"
                    )
                    if result.get("verified", False):
                        authenticated = True
                        message = "Access Granted! Welcome back."
                except Exception:
                    pass
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # Allow user to see "ACCESS IDENTIFIED" or "DENIED" for 1 extra second
        cap.release()
        self.cv2.destroyAllWindows()
            
        return authenticated, message
