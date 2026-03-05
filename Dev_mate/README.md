# DEVMATE – Intelligent Developer Assistant

> Fully offline | Modular Python | Dark-mode GUI | Voice I/O | Local LLM

---

## Features

| Feature | Technology |
|---|---|
| 🧠 Local LLM | Ollama (`llama3:8b-instruct-q4_0`) |
| 🎙️ Speech-to-Text | OpenAI Whisper (base, CPU-only) |
| 🔊 Text-to-Speech | Coqui TTS (VITS, offline) |
| 💾 Hybrid Memory | deque (session) + SQLite (persistent) |
| 🗂️ Project Init | Python / JS / Node / HTML / C++ templates |
| 🔀 Git & GitHub | `git` + `gh` CLI automation |
| ▶️ Safe Commands | Whitelist-filtered subprocess execution |
| ⏰ Reminders | `threading.Timer` + `dateutil` parsing |
| 📋 Tasks | JSON-backed CRUD with priorities |
| 🖥️ GUI | Tkinter dark-mode, sidebar, spinner |

---

## System Requirements

| Component | Minimum |
|---|---|
| RAM | 8 GB (6 GB free recommended) |
| CPU | Ryzen 3 / Intel i3 (4+ cores) |
| Storage | ~5 GB (models) |
| OS | Windows 10+ / Linux / macOS |
| Python | 3.10+ |

---

## Quick Start

### 1. Prerequisites

Install [Ollama](https://ollama.ai) then pull the model:
```powershell
ollama pull llama3:8b-instruct-q4_0
```

Install [Git](https://git-scm.com) and optionally [GitHub CLI](https://cli.github.com):
```powershell
gh auth login   # only needed for GitHub push
```

### 2. Install Python Dependencies

```powershell
cd "C:\Users\santh\OneDrive\Desktop\DevMate"

# (Recommended) Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

Or just double-click **`install.bat`** which does all of the above.

### 3. Run DEVMATE

Make sure Ollama is running first:
```powershell
ollama serve          # terminal 1 (keep open)
python devmate.py     # terminal 2
```

---

## Folder Structure

```
DevMate/
├── devmate.py            ← Main controller (entry point)
├── config.py             ← All settings & constants
├── requirements.txt
├── install.bat           ← Windows one-click setup
├── README.md
├── modules/
│   ├── __init__.py
│   ├── memory_module.py  ← Hybrid memory (deque + SQLite)
│   ├── llm_module.py     ← Ollama intent detection + chat
│   ├── speech_module.py  ← Whisper STT + Coqui TTS
│   ├── automation_module.py  ← Project init, Git, commands
│   ├── scheduler_module.py   ← Threading reminder scheduler
│   └── ui_module.py      ← Tkinter dark-mode GUI
├── data/
│   ├── devmate.db        ← SQLite long-term memory (auto-created)
│   ├── tasks.json        ← Task store (auto-created)
│   └── activity.log      ← Rotating log (auto-created)
└── tests/
    └── test_modules.py   ← pytest test suite
```

---

## Usage Examples

| What to say / type | What happens |
|---|---|
| `Create a python project called myapi` | Scaffolds folder + venv |
| `Initialize git in myapi` | `git init` |
| `Push to GitHub as myapi` | `gh repo create` + push |
| `Remind me in 30 minutes to review the PR` | Timer set |
| `Add task: write unit tests` (high priority) | Task saved |
| `List tasks` | All tasks shown in chat + sidebar |
| `Complete task 1` | Marks task done |
| `Run command: pytest tests/` | Safe subprocess run |
| `What is a Python generator?` | LLM answers |
| Click 🎤 → speak | Whisper transcribes → same as typing |

---

## Configuration

Edit `config.py` to customise:

```python
OLLAMA_MODEL        = "phi3:mini"  # or llama3.1:8b
WHISPER_MODEL       = "base"                      # tiny/base/small
TTS_ENABLED_DEFAULT = True
BASE_PROJECT_DIR    = Path.home() / "Devmate_Projects"
LLM_MAX_TOKENS      = 2048
SHORT_TERM_MAXLEN   = 20
```

---

## Running Tests

```powershell
cd "C:\Users\santh\OneDrive\Desktop\DevMate"
.\.venv\Scripts\Activate.ps1
pip install pytest pytest-mock
python -m pytest tests/ -v
```

No Ollama server required to run tests (mocked).

---

## Database Schema

SQLite at `data/devmate.db`:

| Table | Purpose |
|---|---|
| `memory` | All conversation turns (session_id, role, content) |
| `preferences` | User preferences (key/value, JSON-serialised) |
| `projects` | Project history (name, path, language, created_at) |
| `commands` | Command frequency log (run_count, last_used) |

---

## RAM Optimization Techniques

1. **Lazy model loading** — Whisper & TTS load on first voice use
2. **Deque cap** — only last 20 turns kept in RAM
3. **LLM context cap** — max 2048 tokens / 10 turns sent to Ollama
4. **q4 quantization** — llama3 8B in 4-bit uses ~4.5 GB RAM
5. **Daemon threads** — background threads don't prevent GC
6. **WAL mode SQLite** — non-blocking concurrent writes

---

## Future Scalability

- **Plugin system**: drop new intent handlers as separate files
- **Web interface**: replace Tkinter with FastAPI + React
- **RAG memory**: add ChromaDB vector store for semantic retrieval
- **Larger models**: swap to `llama3:70b-q4` on better hardware
- **STT upgrade**: use `whisper-medium` for better accuracy
- **Multi-user**: add session isolation in SQLite schema
- **Code execution sandbox**: Docker-based safe code runner
