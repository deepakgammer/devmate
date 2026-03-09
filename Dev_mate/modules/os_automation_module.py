"""
DEVMATE - OS Automation Module
Using PyAutoGUI for system-level automation.
"""
import logging
import os
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

class OSAutomationModule:
    def __init__(self, output_callback=None):
        self._output_cb = output_callback or (lambda msg: logger.info("[OS] %s", msg))
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            self.pyautogui = pyautogui
            self.available = True
        except ImportError:
            self._emit("PyAutoGUI not installed. OS automation is disabled.")
            self.available = False

    def _emit(self, msg: str):
        if self._output_cb:
            self._output_cb(msg)

    def open_app(self, app_name: str) -> bool:
        """Attempt to open an application using OS commands."""
        self._emit(f"Attempting to open {app_name}...")
        try:
            if os.name == 'nt' and self.available:
                # Windows: best way for all apps (including ones not in PATH like Discord)
                # is to simulate pressing the Windows key and typing the app name.
                self.pyautogui.press('win')
                time.sleep(0.5)
                self.pyautogui.typewrite(app_name, interval=0.05)
                time.sleep(0.8)
                self.pyautogui.press('enter')
                return True
            elif os.name == 'posix':
                # macOS / Linux
                subprocess.Popen(["open", "-a", app_name])
                return True
            else:
                self._emit("Unsupported OS or missing PyAutoGUI.")
                return False
        except Exception as e:
            self._emit(f"Failed to open {app_name}: {e}")
            return False

    def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text as if from a physical keyboard."""
        if not self.available: return False
        
        self._emit(f"Typing text (length: {len(text)})")
        try:
            self.pyautogui.typewrite(text, interval=interval)
            return True
        except Exception as e:
            self._emit(f"Typing failed: {e}")
            return False

    def press_key(self, key_name: str) -> bool:
        """Press a specific key (e.g., 'enter', 'tab')."""
        if not self.available: return False
        
        try:
            self.pyautogui.press(key_name)
            return True
        except Exception as e:
            self._emit(f"Key press failed: {e}")
            return False
            
    def take_screenshot(self, save_path: str) -> bool:
        if not self.available: return False
        try:
            self._emit(f"Saving screenshot to {save_path}")
            screenshot = self.pyautogui.screenshot()
            screenshot.save(save_path)
            return True
        except Exception as e:
            self._emit(f"Screenshot failed: {e}")
            return False

    def open_whatsapp_contact(self, contact: str) -> bool:
        """Opens WhatsApp and navigates to the specified contact."""
        if not self.available: return False
        try:
            if os.name == 'nt':
                # Open WhatsApp using Windows URI scheme
                subprocess.Popen(["start", "whatsapp:"], shell=True)
                time.sleep(3) # Wait for UI to load
                
                # Search for the contact
                self.pyautogui.hotkey('ctrl', 'f')
                time.sleep(0.5)
                self.pyautogui.typewrite(contact, interval=0.05)
                time.sleep(2.0) # wait for search results to filter
                
                # Use DOWN arrow exactly ONCE to select the first result (the DM) and NOT the groups below it
                self.pyautogui.press('down')
                time.sleep(0.3)
                self.pyautogui.press('enter')
                time.sleep(1.0)
                return True
            else:
                self._emit("WhatsApp automation currently only supported on Windows.")
                return False
        except Exception as e:
            self._emit(f"Failed to open WhatsApp: {e}")
            return False

    def send_whatsapp_message(self, contact: str, message: str) -> bool:
        """Sends a message to the contact. Wait for confirmation logic handled by caller."""
        if not self.available: return False
        self._emit(f"Typing WhatsApp message to {contact}...")
        if self.open_whatsapp_contact(contact):
            self.pyautogui.typewrite(message, interval=0.05)
            time.sleep(0.5)
            self.pyautogui.press('enter')
            return True
        return False
        
    def read_whatsapp_messages(self, contact: str):
        """Attempts to read messages from the contact's chat history via UI automation."""
        if not self.available: return None
        self._emit(f"Reading WhatsApp messages from {contact}...")
        if self.open_whatsapp_contact(contact):
            import pyperclip
            
            # Clear old clipboard
            pyperclip.copy("")
            
            # Click above the typing area to focus chat history
            screen_w, screen_h = self.pyautogui.size()
            self.pyautogui.click(screen_w // 2, screen_h // 2)
            time.sleep(0.5)
            
            # Select all
            self.pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.5)
            # Copy
            self.pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.5)
            
            # Restore view
            self.pyautogui.press('esc')
            
            text = pyperclip.paste()
            if not text:
                return "Could not read text from UI. It might be blocked or the chat is empty."
            return text
        return None
