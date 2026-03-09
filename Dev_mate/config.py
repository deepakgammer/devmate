"""
DEVMATE – Central Configuration
All module-level settings, paths, and constants are defined here.
"""

import os
from pathlib import Path

# ─────────────────────────── Paths ───────────────────────────
BASE_DIR        = Path(__file__).parent.resolve()
DATA_DIR        = BASE_DIR / "data"
DB_PATH         = DATA_DIR / "devmate.db"
LOG_PATH        = DATA_DIR / "activity.log"
TASKS_PATH      = DATA_DIR / "tasks.json"
MODULES_DIR     = BASE_DIR / "modules"

# Default directory where new projects will be created
BASE_PROJECT_DIR = Path.home() / "Projects"

# ─────────────────────────── App Modes ─────────────────────────
# "DEV" for professional task-focused, "MATE" for friendly buddy mode.
CURRENT_MODE = "DEV"

# ─────────────────────────── Security ──────────────────────────
FACE_RECOGNITION_ENABLED = True

# ─────────────────────────── LLM ────────────────────────────
OLLAMA_MODEL        = "phi3:mini"      # Microsoft Phi-3 Mini – fast & capable
OLLAMA_HOST         = "http://localhost:11434"

LLM_MAX_TOKENS      = 128      # keep responses short & fast
LLM_TEMPERATURE     = 0.1           # more deterministic for intent parsing
LLM_TIMEOUT_SEC     = 45            # lower timeout to avoid hanging

# ─────────────────────────── STT ────────────────────────────
WHISPER_MODEL       = "small.en"   # better accuracy for English
WHISPER_LANGUAGE    = "en"
RECORD_SAMPLE_RATE  = 16000
RECORD_CHANNELS     = 1
RECORD_CHUNK        = 1024
SILENCE_TIMEOUT_SEC = 2.0      # stop recording after N seconds of silence

# ─────────────────────────── TTS ────────────────────────────
TTS_MODEL           = "tts_models/en/ljspeech/vits"
TTS_ENABLED_DEFAULT = True     # user can toggle in GUI

# ──────────────── Idle Engagement ────────────────────────────
IDLE_TIMEOUT_SEC    = 120      # seconds of inactivity before DevMate speaks up
IDLE_REPEAT_SEC     = 180      # seconds between subsequent idle nudges

# ──────────────────────── Memory ────────────────────────────
SHORT_TERM_MAXLEN   = 15       # deque: last 15 turns kept in RAM
LLM_CONTEXT_TURNS   = 5        # more turns → better memory recall

# ─────────────────── Command Security ───────────────────────
COMMAND_BLACKLIST = {
    "rm -rf", "del /f", "format", "mkfs", "dd if=",
    "shutdown", "reboot", "halt", "poweroff",
    ":(){ :|:& };:", "DROP TABLE", "DROP DATABASE",
    "rmdir /s /q", "> /dev/", "chmod 777 /",
    "wget", "curl",  # block network fetches in offline mode
}

# Safe prefixes – only commands starting with these are allowed
COMMAND_WHITELIST_PREFIXES = (
    "echo", "python", "pip", "npm", "npx", "node", "git",
    "gh", "gws", "ls", "dir", "cat", "type", "mkdir",
    "cd", "pwd", "pytest", "black", "isort",
    "poetry", "uvicorn", "flask", "django",
)

# ─────────────────────────── UI ─────────────────────────────
APP_TITLE   = "DEVMATE – Intelligent Developer Assistant"
APP_WIDTH   = 1280
APP_HEIGHT  = 780
MIN_WIDTH   = 900
MIN_HEIGHT  = 600

# Dark-mode colour palette
COLORS = {
    "bg":           "#0f1117",
    "sidebar_bg":   "#161b22",
    "card_bg":      "#1c2128",
    "input_bg":     "#21262d",
    "border":       "#30363d",
    "accent":       "#58a6ff",
    "accent2":      "#3fb950",
    "warning":      "#d29922",
    "danger":       "#f85149",
    "text":         "#e6edf3",
    "text_dim":     "#8b949e",
    "user_bubble":  "#1f4068",
    "bot_bubble":   "#1b2a1b",
    "scrollbar":    "#30363d",
}

FONTS = {
    "title":    ("Segoe UI", 16, "bold"),
    "heading":  ("Segoe UI", 12, "bold"),
    "body":     ("Segoe UI", 11),
    "code":     ("Consolas", 10),
    "small":    ("Segoe UI", 9),
    "input":    ("Segoe UI", 12),
}

# ────────── Google Workspace (gws CLI) ────────────────────
GWS_TIMEOUT_SEC  = 30          # subprocess timeout for gws commands
GWS_AUTH_SETUP   = "gws auth setup"
GWS_AUTH_LOGIN   = "gws auth login"

# ────────────────────── Logging ───────────────────────────
LOG_MAX_BYTES   = 1_000_000   # rotate log at 1 MB
LOG_BACKUP_COUNT = 3
