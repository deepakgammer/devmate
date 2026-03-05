"""
DEVMATE – UI Module
Dark-mode Tkinter GUI for the DEVMATE assistant.

Layout:
  ┌───────────────────────────────────────────────────────┐
  │  Top Bar: Logo  |  Status dot + text  |  Spinner      │
  ├─────────────────────────────────┬─────────────────────┤
  │  Chat Area (scrollable)         │  Sidebar            │
  │  – User bubbles (blue tint)     │   ├─ Task List      │
  │  – Bot bubbles (green tint)     │   └─ Activity Log   │
  ├─────────────────────────────────┴─────────────────────┤
  │  [ text input ................. ] [📤] [🎤] [🔊]      │
  └───────────────────────────────────────────────────────┘

All LLM / subprocess calls are dispatched on daemon threads.
GUI updates always go through root.after() to stay thread-safe.
"""

import logging
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class DevMateGUI(tk.Tk):
    """Main application window."""

    # ──────────────────── Constructor ────────────────────────────────────────

    def __init__(self, on_user_input: Callable[[str], None], on_voice_input: Callable[[], None]):
        super().__init__()
        self._on_user_input = on_user_input
        self._on_voice_input = on_voice_input
        self._spinner_chars = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self._spinner_idx = 0
        self._busy = False
        self._tts_on = config.TTS_ENABLED_DEFAULT
        self._tasks: list = []

        self._setup_window()
        self._build_ui()
        self._bind_shortcuts()
        self._welcome_message()

    # ──────────────────── Window Setup ───────────────────────────────────────

    def _setup_window(self) -> None:
        self.title(config.APP_TITLE)
        self.geometry(f"{config.APP_WIDTH}x{config.APP_HEIGHT}")
        self.minsize(config.MIN_WIDTH, config.MIN_HEIGHT)
        self.configure(bg=config.COLORS["bg"])

        # Set window icon (graceful fallback)
        try:
            icon_data = self._create_icon()
            self.iconphoto(False, icon_data)
        except Exception:
            pass

    def _create_icon(self):
        """Create a simple coloured icon programmatically."""
        from PIL import Image, ImageDraw, ImageTk
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=config.COLORS["accent"])
        draw.text((18, 18), "DM", fill="white")
        return ImageTk.PhotoImage(img)

    # ──────────────────── UI Construction ────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_topbar()
        self._build_paned()
        self._build_input_bar()

    def _build_topbar(self) -> None:
        """Top title bar with logo, status indicator, and spinner."""
        bar = tk.Frame(self, bg=config.COLORS["sidebar_bg"], height=56)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        # Logo
        tk.Label(
            bar,
            text="⚡ DEVMATE",
            bg=config.COLORS["sidebar_bg"],
            fg=config.COLORS["accent"],
            font=config.FONTS["title"],
            pady=12,
        ).pack(side="left", padx=18)

        # Sub-title
        tk.Label(
            bar,
            text="Intelligent Developer Assistant",
            bg=config.COLORS["sidebar_bg"],
            fg=config.COLORS["text_dim"],
            font=config.FONTS["small"],
        ).pack(side="left", padx=0)

        # Spinner (right side)
        self._spinner_lbl = tk.Label(
            bar,
            text="",
            bg=config.COLORS["sidebar_bg"],
            fg=config.COLORS["accent"],
            font=config.FONTS["heading"],
            width=3,
        )
        self._spinner_lbl.pack(side="right", padx=8)

        # Status dot + text
        self._status_dot = tk.Label(
            bar,
            text="●",
            bg=config.COLORS["sidebar_bg"],
            fg=config.COLORS["accent2"],
            font=config.FONTS["body"],
        )
        self._status_dot.pack(side="right", padx=(8, 2))

        self._status_lbl = tk.Label(
            bar,
            text="Ready",
            bg=config.COLORS["sidebar_bg"],
            fg=config.COLORS["text_dim"],
            font=config.FONTS["small"],
        )
        self._status_lbl.pack(side="right", padx=(0, 4))

        # Separator
        tk.Frame(self, bg=config.COLORS["border"], height=1).pack(fill="x")

    def _build_paned(self) -> None:
        """Main paned window: chat (left) + sidebar (right)."""
        paned = tk.PanedWindow(
            self,
            orient="horizontal",
            bg=config.COLORS["bg"],
            sashwidth=4,
            sashrelief="flat",
            sashpad=0,
        )
        paned.pack(fill="both", expand=True)

        # ── Chat Area ────────────────────────────────────────────────────────
        chat_frame = tk.Frame(paned, bg=config.COLORS["bg"])
        paned.add(chat_frame, minsize=500, width=860, stretch="always")

        self._chat = scrolledtext.ScrolledText(
            chat_frame,
            bg=config.COLORS["bg"],
            fg=config.COLORS["text"],
            font=config.FONTS["body"],
            wrap="word",
            state="disabled",
            relief="flat",
            bd=0,
            padx=16,
            pady=12,
            cursor="arrow",
        )
        self._chat.pack(fill="both", expand=True)

        # Configure tags for colorised messages
        self._chat.tag_configure(
            "user",
            background=config.COLORS["user_bubble"],
            lmargin1=16,
            lmargin2=16,
            rmargin=16,
            spacing1=6,
            spacing3=6,
        )
        self._chat.tag_configure(
            "bot",
            background=config.COLORS["bot_bubble"],
            lmargin1=16,
            lmargin2=16,
            rmargin=16,
            spacing1=6,
            spacing3=6,
        )
        self._chat.tag_configure(
            "system",
            foreground=config.COLORS["text_dim"],
            lmargin1=16,
            lmargin2=16,
            spacing1=4,
            spacing3=4,
            font=config.FONTS["small"],
        )
        self._chat.tag_configure(
            "error",
            foreground=config.COLORS["danger"],
            lmargin1=16,
            spacing1=4,
        )
        self._chat.tag_configure(
            "code",
            font=config.FONTS["code"],
            foreground=config.COLORS["accent2"],
            lmargin1=32,
            lmargin2=32,
        )

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = tk.Frame(paned, bg=config.COLORS["sidebar_bg"], width=340)
        paned.add(sidebar, minsize=260, width=340, stretch="never")

        self._build_task_panel(sidebar)
        self._build_log_panel(sidebar)

    def _build_task_panel(self, parent: tk.Frame) -> None:
        """Task List card in the sidebar."""
        card = tk.Frame(parent, bg=config.COLORS["card_bg"], bd=0)
        card.pack(fill="x", padx=10, pady=(12, 6))

        header = tk.Frame(card, bg=config.COLORS["card_bg"])
        header.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(
            header,
            text="📋  Tasks",
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text"],
            font=config.FONTS["heading"],
        ).pack(side="left")

        self._task_count_lbl = tk.Label(
            header,
            text="0",
            bg=config.COLORS["accent"],
            fg="white",
            font=config.FONTS["small"],
            width=3,
            relief="flat",
        )
        self._task_count_lbl.pack(side="right")

        # Separator
        tk.Frame(card, bg=config.COLORS["border"], height=1).pack(fill="x")

        # Task listbox
        lb_frame = tk.Frame(card, bg=config.COLORS["card_bg"])
        lb_frame.pack(fill="both", padx=8, pady=6)

        self._task_listbox = tk.Listbox(
            lb_frame,
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text"],
            selectbackground=config.COLORS["accent"],
            selectforeground="white",
            font=config.FONTS["small"],
            relief="flat",
            bd=0,
            height=10,
            activestyle="none",
        )
        sb = tk.Scrollbar(lb_frame, command=self._task_listbox.yview)
        self._task_listbox.configure(yscrollcommand=sb.set)
        self._task_listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Label(
            card,
            text='💡 Say "add task: …" or "list tasks"',
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text_dim"],
            font=config.FONTS["small"],
            pady=6,
        ).pack()

    def _build_log_panel(self, parent: tk.Frame) -> None:
        """Activity Log card in the sidebar."""
        card = tk.Frame(parent, bg=config.COLORS["card_bg"])
        card.pack(fill="both", expand=True, padx=10, pady=(6, 12))

        tk.Label(
            card,
            text="📜  Activity Log",
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text"],
            font=config.FONTS["heading"],
            anchor="w",
            padx=12,
            pady=10,
        ).pack(fill="x")

        tk.Frame(card, bg=config.COLORS["border"], height=1).pack(fill="x")

        self._log_text = scrolledtext.ScrolledText(
            card,
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text_dim"],
            font=config.FONTS["small"],
            wrap="word",
            state="disabled",
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            height=12,
        )
        self._log_text.pack(fill="both", expand=True)

    def _build_input_bar(self) -> None:
        """Bottom input row: text entry + Send / Voice / TTS buttons."""
        # Separator
        tk.Frame(self, bg=config.COLORS["border"], height=1).pack(fill="x")

        bar = tk.Frame(self, bg=config.COLORS["input_bg"], pady=10)
        bar.pack(fill="x", side="bottom")

        # ── Input field ───────────────────────────────────────────────────────
        entry_frame = tk.Frame(bar, bg=config.COLORS["card_bg"], padx=4, pady=4)
        entry_frame.pack(side="left", fill="x", expand=True, padx=(14, 8))

        self._input_var = tk.StringVar()
        self._entry = tk.Entry(
            entry_frame,
            textvariable=self._input_var,
            bg=config.COLORS["card_bg"],
            fg=config.COLORS["text"],
            insertbackground=config.COLORS["accent"],
            font=config.FONTS["input"],
            relief="flat",
            bd=0,
        )
        self._entry.pack(fill="x", padx=6, pady=4)
        self._entry.focus_set()

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_cfg = dict(
            bg=config.COLORS["card_bg"],
            activebackground=config.COLORS["input_bg"],
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=6,
            pady=6,
        )

        # Send
        self._send_btn = tk.Button(
            bar,
            text="📤",
            font=("Segoe UI Emoji", 16),
            command=self._handle_send,
            fg=config.COLORS["accent"],
            **btn_cfg,
        )
        self._send_btn.pack(side="left", padx=4)

        # Voice
        self._voice_btn = tk.Button(
            bar,
            text="🎤",
            font=("Segoe UI Emoji", 16),
            command=self._handle_voice,
            fg=config.COLORS["accent2"],
            **btn_cfg,
        )
        self._voice_btn.pack(side="left", padx=4)

        # TTS toggle
        self._tts_btn = tk.Button(
            bar,
            text="🔊",
            font=("Segoe UI Emoji", 16),
            command=self._handle_tts_toggle,
            fg=config.COLORS["accent"],
            **btn_cfg,
        )
        self._tts_btn.pack(side="left", padx=(4, 4))
        
        # Mode toggle
        self._mode_btn = tk.Button(
            bar,
            text="DEV",
            font=config.FONTS["heading"],
            command=self._handle_mode_toggle,
            fg=config.COLORS["accent2"],
            **btn_cfg,
        )
        self._mode_btn.pack(side="left", padx=(4, 14))

    def _bind_shortcuts(self) -> None:
        self._entry.bind("<Return>", lambda _: self._handle_send())
        self._entry.bind("<Shift-Return>", lambda e: "break")  # allow newline in future
        self.bind("<Control-l>", lambda _: self._clear_chat())
        self.bind("<Escape>", lambda _: self._entry.focus_set())

    # ──────────────────── Public API (called by devmate.py) ────────────────────

    def add_message(self, role: str, text: str) -> None:
        """
        Append a message to the chat area. Thread-safe via root.after().
        role: 'user' | 'bot' | 'system' | 'error'
        """
        self.after(0, self._append_chat, role, text)

    def log_activity(self, text: str) -> None:
        """Append a line to the activity log sidebar. Thread-safe."""
        self.after(0, self._append_log, text)

    def set_status(self, text: str, ok: bool = True) -> None:
        """Update the status bar text and dot colour. Thread-safe."""
        self.after(0, self._update_status, text, ok)

    def set_busy(self, busy: bool) -> None:
        """Start/stop the spinner and disable/enable input. Thread-safe."""
        self.after(0, self._toggle_busy, busy)

    def refresh_tasks(self, tasks: list) -> None:
        """Replace the task listbox contents. Thread-safe."""
        self.after(0, self._update_task_list, tasks)

    def show_reminder_popup(self, text: str) -> None:
        """Show a reminder messagebox alert. Thread-safe."""
        self.after(0, messagebox.showinfo, "⏰ Reminder", text)

    def begin_stream_message(self) -> None:
        """
        Open a new bot bubble immediately (before tokens arrive).
        Call append_stream_token() for each chunk as it streams in.
        Thread-safe.
        """
        self.after(0, self._begin_stream_chat)

    def append_stream_token(self, token: str) -> None:
        """Append a streaming token to the currently open bot bubble. Thread-safe."""
        self.after(0, self._insert_stream_token, token)

    def set_mode_ui(self, mode: str) -> None:
        """Update the UI mode button externally. Thread-safe."""
        self.after(0, self._set_mode_btn_text, mode)

    def _set_mode_btn_text(self, mode: str) -> None:
        self._mode_btn.configure(text=mode)
        self.log_activity(f"Mode switched to {mode}")

    def open_file_picker(self, callback: Callable[[list], None]) -> None:
        """
        Open the native OS file-picker dialog and pass chosen paths to *callback*.

        Thread-safe: scheduling via after(0) ensures the dialog always runs on
        the Tkinter main thread (required on Windows).

        callback(paths): called with a list[str] of absolute file paths.
                         Empty list if the user cancelled.
        """
        self.after(0, self._open_file_picker_main, callback)

    def _open_file_picker_main(self, callback: Callable[[list], None]) -> None:
        """Main-thread file picker implementation."""
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Select files to push to GitHub",
            filetypes=[
                ("All files",        "*.*"),
                ("Python files",     "*.py"),
                ("JavaScript/TS",    "*.js *.ts *.jsx *.tsx"),
                ("Web files",        "*.html *.css *.json"),
                ("Text / Config",    "*.txt *.md *.yaml *.yml *.toml"),
            ],
        )
        callback(list(paths))


    def open_mixed_picker(self, callback: Callable[[list], None]) -> None:
        self.after(0, self._open_mixed_picker_main, callback)

    def _open_mixed_picker_main(self, callback: Callable[[list], None]) -> None:
        from tkinter import filedialog
        import tkinter as tk
        top = tk.Toplevel(self)
        top.title("Select Files & Folders to Push")
        top.geometry("600x400")
        top.transient(self)
        top.grab_set()

        selected_paths = []

        listbox = tk.Listbox(top, selectmode="extended", font=config.FONTS["body"])
        listbox.pack(fill="both", expand=True, padx=10, pady=10)

        def update_list():
            listbox.delete(0, 'end')
            for p in selected_paths:
                listbox.insert('end', p)

        def add_files():
            paths = filedialog.askopenfilenames(parent=top, title="Select Files")
            for p in paths:
                if p not in selected_paths:
                    selected_paths.append(p)
            update_list()

        def add_folder():
            path = filedialog.askdirectory(parent=top, title="Select Folder")
            if path and path not in selected_paths:
                selected_paths.append(path)
            update_list()

        def remove_selected():
            sel = list(listbox.curselection())
            sel.reverse()
            for i in sel:
                selected_paths.pop(i)
            update_list()

        def on_ok():
            top.grab_release()
            top.destroy()
            callback(selected_paths)

        def on_cancel():
            top.grab_release()
            top.destroy()
            callback([])

        btn_frame = tk.Frame(top)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btn_frame, text="Add Files...", font=config.FONTS["body"], command=add_files).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Add Folder...", font=config.FONTS["body"], command=add_folder).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Remove Selected", font=config.FONTS["body"], command=remove_selected).pack(side="left", padx=5)

        ctrl_frame = tk.Frame(top)
        ctrl_frame.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(ctrl_frame, text="Commit & Push", bg=config.COLORS.get("accent", "#007acc"), fg="white", font=config.FONTS["body"], command=on_ok).pack(side="right", padx=5)
        tk.Button(ctrl_frame, text="Cancel", font=config.FONTS["body"], command=on_cancel).pack(side="right", padx=5)

    def open_folder_picker(self, callback: Callable[[str], None]) -> None:
        """
        Open a native OS folder-picker dialog and pass the chosen path to *callback*.

        Thread-safe: scheduled via after(0) to run on the Tkinter main thread.

        callback(path): called with a str of the absolute folder path,
                        or empty string if the user cancelled.
        """
        self.after(0, self._open_folder_picker_main, callback)

    def _open_folder_picker_main(self, callback: Callable[[str], None]) -> None:
        """Main-thread folder picker implementation."""
        from tkinter import filedialog
        path = filedialog.askdirectory(
            parent=self,
            title="Select folder for your project",
        )
        callback(path or "")

    # ──────────────────── Internal Handlers ───────────────────────────────────

    def _handle_send(self) -> None:
        text = self._input_var.get().strip()
        if not text or self._busy:
            return
        self._input_var.set("")
        self._on_user_input(text)

    def _handle_voice(self) -> None:
        if self._busy:
            return
        self._on_voice_input()

    def _handle_tts_toggle(self) -> None:
        self._tts_on = not self._tts_on
        icon = "🔊" if self._tts_on else "🔇"
        self._tts_btn.configure(text=icon)
        state = "ON" if self._tts_on else "OFF"
        self.log_activity(f"TTS {state}")
        self.set_status(f"TTS {state}", ok=True)

    def _handle_mode_toggle(self) -> None:
        if config.CURRENT_MODE == "DEV":
            new_mode = "MATE"
        else:
            new_mode = "DEV"
        from config import CURRENT_MODE
        self._on_user_input(f"change mode to {new_mode}")

    # ──────────────────── Internal GUI Updaters (main thread only) ─────────────

    def _append_chat(self, role: str, text: str) -> None:
        self._chat.configure(state="normal")
        now = datetime.now().strftime("%H:%M")
        prefix_map = {
            "user":   f"\n👤 You [{now}]\n",
            "bot":    f"\n🤖 DEVMATE [{now}]\n",
            "system": f"\n⚙️  [{now}] ",
            "error":  f"\n❌ [{now}] ",
        }
        prefix = prefix_map.get(role, f"\n[{now}] ")
        self._chat.insert("end", prefix, role)
        self._chat.insert("end", text + "\n", role)
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _begin_stream_chat(self) -> None:
        """Open a bot bubble header and leave the cursor at 'end' for token insertion."""
        self._chat.configure(state="normal")
        now = datetime.now().strftime("%H:%M")
        self._chat.insert("end", f"\n🤖 DEVMATE [{now}]\n", "bot")
        # Mark position so tokens are appended after the header
        self._chat.mark_set("stream_end", "end")
        self._chat.mark_gravity("stream_end", "right")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _insert_stream_token(self, token: str) -> None:
        """Insert a token at the tracked stream position (main thread only)."""
        self._chat.configure(state="normal")
        self._chat.insert("stream_end", token, "bot")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _append_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        now = datetime.now().strftime("%H:%M:%S")
        self._log_text.insert("end", f"[{now}] {text}\n")
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    def _update_status(self, text: str, ok: bool) -> None:
        color = config.COLORS["accent2"] if ok else config.COLORS["warning"]
        self._status_dot.configure(fg=color)
        self._status_lbl.configure(text=text)

    def _toggle_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._send_btn.configure(state=state)
        self._voice_btn.configure(state=state)
        self._entry.configure(state=state)
        if busy:
            self._start_spinner()
        else:
            self._stop_spinner()

    def _update_task_list(self, tasks: list) -> None:
        self._tasks = tasks
        self._task_listbox.delete(0, "end")
        for t in tasks:
            done = "✅" if t.get("done") else "○"
            pri_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            pri = pri_icons.get(t.get("priority", "medium"), "○")
            self._task_listbox.insert("end", f" {done} {pri} {t.get('text', '')}")
        self._task_count_lbl.configure(text=str(len(tasks)))

    def _clear_chat(self) -> None:
        self._chat.configure(state="normal")
        self._chat.delete("1.0", "end")
        self._chat.configure(state="disabled")

    # ──────────────────── Spinner ─────────────────────────────────────────────

    def _start_spinner(self) -> None:
        self._spinner_idx = 0
        self._animate_spinner()

    def _stop_spinner(self) -> None:
        self._spinner_lbl.configure(text="")

    def _animate_spinner(self) -> None:
        if not self._busy:
            return
        self._spinner_lbl.configure(text=self._spinner_chars[self._spinner_idx % len(self._spinner_chars)])
        self._spinner_idx += 1
        self.after(80, self._animate_spinner)

    # ──────────────────── Welcome ─────────────────────────────────────────────

    def _welcome_message(self) -> None:
        self._append_chat(
            "bot",
            "Here's what I can do:\n"
            "  🗂️  Create projects  — 'Create a python project called myapp'\n"
            "  🔀  Git operations   — 'Init git in myapp' / 'Push to GitHub'\n"
            "  🐙  GitHub repos     — 'Create a GitHub repo called myapp'\n"
            "  📥  Download repos   — 'Download myapp repo'\n"
            "  ⏰  Reminders        — 'Remind me in 30 minutes to review PR'\n"
            "  📋  Task tracking    — 'Add task: write unit tests'\n"
            "  ▶️  Run commands     — 'Run command: pytest tests/'\n"
            "  💬  General chat     — Ask me anything about code!\n\n"
            "Press Ctrl+L to clear chat. Click 🎤 to use your voice.",
        )

    # ──────────────────── Properties ─────────────────────────────────────────

    @property
    def tts_enabled(self) -> bool:
        return self._tts_on
