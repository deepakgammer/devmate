import io
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class SpeechModule:
    """Manages offline STT (Whisper) and TTS (Coqui VITS)."""

    def __init__(self):
        # Lazy-loaded model references
        self._whisper_model = None
        self._tts_model = None

        # TTS state
        self.tts_enabled: bool = config.TTS_ENABLED_DEFAULT
        self._is_speaking: bool = False
        self._speak_lock = threading.Lock()

        # STT state  
        self._is_recording: bool = False

    # ──────────────────── Model Loading ──────────────────────────────────────

    def _load_whisper(self):
        """Lazy-load Whisper model (downloads on first call if not cached)."""
        if self._whisper_model is None:
            logger.info("Loading Whisper '%s' model …", config.WHISPER_MODEL)
            try:
                import whisper
                self._whisper_model = whisper.load_model(config.WHISPER_MODEL)
                logger.info("Whisper model loaded.")
            except Exception as e:
                logger.error("Failed to load Whisper: %s", e)
                raise
        return self._whisper_model

    def _load_tts(self):
        """Lazy-load Coqui TTS model."""
        if self._tts_model is None:
            logger.info("Loading Coqui TTS model …")
            try:
                from TTS.api import TTS
                self._tts_model = TTS(model_name=config.TTS_MODEL, progress_bar=False)
                logger.info("Coqui TTS model loaded.")
            except Exception as e:
                logger.error("Failed to load Coqui TTS: %s", e)
                raise
        return self._tts_model

    def preload_models(self) -> None:
        """
        Warm up both models in background daemon threads at startup
        so that the first voice interaction feels instant.
        """
        def _load_both():
            try:
                self._load_whisper()
            except Exception:
                logger.warning("Whisper STT not available – voice input disabled. "
                               "Install with: pip install openai-whisper")
            try:
                self._load_tts()
            except Exception:
                logger.warning("Coqui TTS not available – voice output disabled. "
                               "Install with: pip install TTS")

        t = threading.Thread(target=_load_both, daemon=True, name="ModelPreloader")
        t.start()

    # ──────────────────── Speech-to-Text ─────────────────────────────────────

    def record_and_transcribe(
        self,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Record from the microphone until silence, then transcribe with Whisper.

        Args:
            status_callback: optional callable to report progress strings to GUI.

        Returns:
            Transcribed text string (empty string on failure).
        """
        if self._is_recording:
            logger.warning("Already recording – ignoring duplicate call.")
            return ""

        self._is_recording = True
        transcript = ""
        tmp_path = None

        try:
            import speech_recognition as sr

            if status_callback:
                status_callback("🎤 Listening … (speak now)")

            recogniser = sr.Recognizer()
            recogniser.energy_threshold = 400
            recogniser.dynamic_energy_threshold = True
            recogniser.pause_threshold = config.SILENCE_TIMEOUT_SEC

            with sr.Microphone(sample_rate=config.RECORD_SAMPLE_RATE) as source:
                recogniser.adjust_for_ambient_noise(source, duration=1.0)
                audio = recogniser.listen(
                    source,
                    timeout=15,
                    phrase_time_limit=30,
                )

            if status_callback:
                status_callback("🧠 Transcribing …")

            # Save to temp WAV and pass to Whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio.get_wav_data())
                tmp_path = tmp.name

            model = self._load_whisper()
            result = model.transcribe(
                tmp_path,
                language=config.WHISPER_LANGUAGE,
                fp16=False,  # CPU mode
            )
            transcript = result.get("text", "").strip()
            logger.info("STT transcript: %r", transcript)

        except OSError as e:
            # Common on Windows: FLAC binary or audio device not found
            logger.error("STT OS error: %s", e)
            if status_callback:
                status_callback(
                    "❌ Microphone error — make sure a mic is connected "
                    "and PyAudio is installed (pip install pyaudio)"
                )
        except Exception as e:
            logger.error("STT error: %s", e)
            if status_callback:
                status_callback(f"❌ STT error: {e}")
        finally:
            self._is_recording = False
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return transcript

    def record_and_transcribe_async(
        self,
        status_callback: Optional[Callable[[str], None]],
        done_callback: Callable[[str], None],
    ) -> threading.Thread:
        """Non-blocking STT. Calls done_callback(transcript) when finished."""
        def _worker():
            text = self.record_and_transcribe(status_callback)
            done_callback(text)

        t = threading.Thread(target=_worker, daemon=True, name="STT-Worker")
        t.start()
        return t

    # ──────────────────── Text-to-Speech ─────────────────────────────────────

    def speak(self, text: str) -> None:
        """
        Synthesise *text* and play it back (blocking). 
        Skips silently if TTS is disabled or another utterance is playing.
        """
        if not self.tts_enabled:
            return

        import re
        # Remove markdown symbols
        text = re.sub(r'[*_`\n]+', ' ', text)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        # Remove curly braces and brackets which can cause shape mismatches in Coqui TTS
        text = re.sub(r'[\{\}\[\]]', '', text)
        text = " ".join(text.split())
        
        # Coqui VITS fails on extremely long sequences; truncate for safety
        if len(text) > 400:
            text = text[:397] + "..."

        if not text.strip():
            return

        if self._is_speaking:
            logger.debug("TTS busy – skipping utterance.")
            return

        with self._speak_lock:
            self._is_speaking = True
            try:
                tts = self._load_tts()
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    wav_path = tmp.name

                tts.tts_to_file(text=text, file_path=wav_path)

                import soundfile as sf
                import sounddevice as sd
                data, samplerate = sf.read(wav_path, dtype="float32")
                sd.play(data, samplerate)
                sd.wait()

            except Exception as e:
                logger.error("TTS error: %s", e)
            finally:
                self._is_speaking = False
                try:
                    if 'wav_path' in locals():
                        os.unlink(wav_path)
                except Exception:
                    pass

    def speak_async(self, text: str) -> threading.Thread:
        """Non-blocking TTS. Runs speak() in a daemon thread."""
        t = threading.Thread(target=self.speak, args=(text,), daemon=True, name="TTS-Worker")
        t.start()
        return t

    # ──────────────────── Controls ────────────────────────────────────────────

    def toggle_tts(self) -> bool:
        """Toggle TTS on/off. Returns the new state."""
        self.tts_enabled = not self.tts_enabled
        logger.info("TTS %s", "enabled" if self.tts_enabled else "disabled")
        return self.tts_enabled

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
