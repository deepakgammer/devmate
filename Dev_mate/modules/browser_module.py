"""
DEVMATE - Browser Automation Module
Using Selenium and webdriver-manager.
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

class BrowserModule:
    def __init__(self, output_callback=None):
        self._output_cb = output_callback or (lambda msg: logger.info("[BROWSER] %s", msg))
        self.driver = None

    def _emit(self, msg: str):
        if self._output_cb:
            self._output_cb(msg)

    def _ensure_driver(self):
        if self.driver is None:
            self._emit("Starting Chrome browser instance...")
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                options = webdriver.ChromeOptions()
                # options.add_argument('--headless') # Uncomment for headless operation
                options.add_argument('--start-maximized')
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            except Exception as e:
                self._emit(f"Failed to start browser: {e}")
                self.driver = None

    def open_url(self, url: str) -> bool:
        self._ensure_driver()
        if not self.driver:
            return False
        
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
            
        try:
            from selenium.common.exceptions import WebDriverException
            self._emit(f"Navigating to {url}...")
            self.driver.get(url)
            return True
        except Exception as e:
            self._emit(f"Error navigating: {e}")
            return False

    def search_google(self, query: str) -> bool:
        self._ensure_driver()
        if not self.driver:
            return False
            
        self._emit(f"Searching Google for: '{query}'")
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            self.driver.get("https://www.google.com")
            search_box = self.driver.find_element(By.NAME, "q")
            search_box.send_keys(query)
            search_box.send_keys(Keys.RETURN)
            return True
        except Exception as e:
            self._emit(f"Search failed: {e}")
            return False

    def close(self):
        if self.driver:
            self._emit("Closing browser instance...")
            self.driver.quit()
            self.driver = None
