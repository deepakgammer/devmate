"""
DEVMATE – Controller Module (DevMateController)
Central orchestrator. Instantiates all modules and routes intents.

Data Flow:
  User text/voice
      │
      ▼
  LLMModule.detect_intent()
      │
      ├─► create_project  → AutomationModule.create_project()
      ├─► init_git        → AutomationModule.git_init()
      ├─► push_github     → AutomationModule.git_push() / create_github_repo()
      ├─► add_reminder    → SchedulerModule.add_reminder()
      ├─► list_tasks      → TaskManager.list_tasks()
      ├─► add_task        → TaskManager.add_task()
      ├─► remove_task     → TaskManager.remove_task()
      ├─► complete_task   → TaskManager.complete_task()
      ├─► run_command     → AutomationModule.run_command()
      └─► general_chat    → LLMModule.chat()
          │
          ▼
      MemoryModule.add_message()  ← all turns recorded
          │
          ▼
      DevMateGUI.add_message() + SpeechModule.speak_async()
"""

import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import config
from modules.memory_module import MemoryManager
from modules.llm_module import LLMModule
from modules.speech_module import SpeechModule
from modules.automation_module import AutomationModule
from modules.scheduler_module import SchedulerModule
from modules.google_workspace import GWSManager
from modules.ui_module import DevMateGUI
from modules.task_manager import TaskManager
from modules.face_recognition_module import FaceRecognitionModule
from modules.os_automation_module import OSAutomationModule
from modules.browser_module import BrowserModule
import sys

logger = logging.getLogger("devmate")


class DevMateController:
    """
    Central orchestrator.  Instantiates all modules and routes intents.
    """

    def __init__(self):
        logger.info("=== DEVMATE starting ===")

        # Modules
        self.memory     = MemoryManager()
        self.llm        = LLMModule()
        self.speech     = SpeechModule()
        self.scheduler  = SchedulerModule(fire_callback=self._on_reminder_fire)
        self.automation = AutomationModule(output_callback=self._on_cmd_output)
        self.tasks      = TaskManager()
        self.gws        = GWSManager(output_callback=self._on_cmd_output)
        # GUI (created last; passes callbacks INTO controller)
        self.gui = DevMateGUI(
            on_user_input=self.handle_text_input,
            on_voice_input=self.handle_voice_input,
        )

        # Wire reminder scheduler → GUI
        self.scheduler._fire_cb = self._on_reminder_fire
        
        # Modules that depend on GUI for output callbacks
        self.face_rec   = FaceRecognitionModule(data_dir=config.DATA_DIR, output_callback=self._on_cmd_output)
        self.os_auto    = OSAutomationModule(output_callback=self._on_cmd_output)
        self.browser    = BrowserModule(output_callback=self._on_cmd_output)

        # Pre-load models in background
        self.speech.preload_models()

        # Sync initial task list to sidebar
        self.gui.refresh_tasks(self.tasks.list_tasks())

        # Multi-turn pending state for GitHub repo creation
        # Keys: 'step', 'name', 'private'
        self._pending_repo: Optional[Dict[str, Any]] = None

        # Pending state for push_files_to_repo flow
        # Keys: 'repo' (once name is known)
        self._pending_push: Optional[Dict[str, Any]] = None
        self._pending_confirm_delete: Optional[str] = None  # repo awaiting delete confirm

        # Pending state for create_project flow (folder picker → name prompt)
        # Keys: 'language', 'base_dir', 'name' (optional), 'step'
        self._pending_create_project: Optional[Dict[str, Any]] = None

        # Pending state for WhatsApp sending
        self._pending_whatsapp: Optional[Dict[str, str]] = None

        # ── Idle engagement ───────────────────────────────────────────────
        self._last_activity = time.time()
        self._idle_timer_id: Optional[str] = None
        self._idle_messages = [
            "Hey there! 👋 Need any help with your project?",
            "I'm here if you need me! Just type or speak your request. 😊",
            "Taking a break? Let me know when you're ready to code! 💻",
            "Don't forget — I can create projects, manage Git, and more! ⚡",
            "Still around? I'd love to help with something! 🚀",
            "Feeling stuck? Try asking me a coding question! 🤔",
            "Need a reminder? Just say 'Remind me in 10 minutes to …' ⏰",
            "Want me to set up a new project? Just say the word! 🗂️",
            "I'm not going anywhere — ready when you are! 😄",
            "Pro tip: you can push files to GitHub just by asking me! 🐙",
        ]

        # Schedule spoken welcome greeting after a short delay
        self.gui.after(2000, self._speak_welcome)
        # Start idle timer
        self._reset_idle_timer()

        logger.info("DevMateController ready.")

    # ──────────────────── Input Entry Points ─────────────────────────────────

    def handle_text_input(self, text: str) -> None:
        """Called by GUI when user submits text."""
        logger.info("User text: %r", text)
        self.gui.add_message("user", text)
        self.memory.add_message("user", text)
        self.gui.set_busy(True)
        self.gui.set_status("Thinking …", ok=True)

        # Reset idle timer on every user interaction
        self._reset_idle_timer()
        self.gui.log_activity(f"User: {text[:60]}")

        # ── Multi-turn pending state: project creation (name prompt) ─────
        if self._pending_create_project is not None:
            threading.Thread(
                target=self._continue_create_project,
                args=(text,),
                daemon=True,
                name="Handler-project-pending",
            ).start()
            return

        # ── Multi-turn pending state: repo creation conversation ──────────
        if self._pending_repo is not None:
            threading.Thread(
                target=self._continue_repo_creation,
                args=(text,),
                daemon=True,
                name="Handler-repo-pending",
            ).start()
            return

        # Confirm dangerous delete-repo action
        if self._pending_confirm_delete:
            threading.Thread(
                target=self._process_delete_confirm,
                args=(text,),
                daemon=True,
                name="Handler-delete-confirm",
            ).start()
            return

        # ── Multi-turn pending state: push-files repo-name question ────────
        if self._pending_push is not None:
            threading.Thread(
                target=self._continue_push_files,
                args=(text,),
                daemon=True,
                name="Handler-push-pending",
            ).start()
            return
            
        # ── Multi-turn pending state: WhatsApp sending confirmation ────────
        if self._pending_whatsapp is not None:
            threading.Thread(
                target=self._continue_whatsapp_send,
                args=(text,),
                daemon=True,
                name="Handler-whatsapp-pending",
            ).start()
            return

        context = self.memory.get_context()
        self.llm.detect_intent_async(text, context, callback=self._on_intent)

    def handle_voice_input(self) -> None:
        """Called by GUI when user clicks the microphone button."""
        self.gui.set_busy(True)
        self.gui.set_status("Listening …", ok=True)

        def _on_transcript(text: str) -> None:
            if text:
                self.gui.set_status("Processing …", ok=True)
                self.handle_text_input(text)
            else:
                self.gui.set_busy(False)
                self.gui.set_status("No speech detected", ok=False)
                self.gui.add_message("system", "No speech detected. Please try again.")

        self.speech.record_and_transcribe_async(
            status_callback=lambda s: self.gui.set_status(s, ok=True),
            done_callback=_on_transcript,
        )

    # ──────────────────── Intent Dispatch ───────────────────────────────────

    def _on_intent(self, intent_data: Dict[str, Any]) -> None:
        """Callback from LLMModule.detect_intent_async(). Dispatches to handlers."""
        intent  = intent_data.get("intent", "general_chat")
        params  = intent_data.get("params", {})
        logger.info("Intent: %s  params: %s", intent, params)
        self.gui.log_activity(f"Intent: {intent}")

        dispatch = {
            "create_project":      self._handle_create_project,
            "init_git":            self._handle_init_git,
            "push_github":         self._handle_push_github,
            "create_github_repo":  self._handle_create_github_repo,
            "push_files_to_repo":  self._handle_push_files_to_repo,
            "delete_github_repo":   self._handle_delete_github_repo,
                        "delete_file_from_repo": self._handle_delete_file_from_repo,
            "download_github_repo": self._handle_download_github_repo,
            "download_file_from_repo": self._handle_download_file_from_repo,
            "add_reminder":        self._handle_add_reminder,
            "list_tasks":          self._handle_list_tasks,
            "add_task":            self._handle_add_task,
            "remove_task":         self._handle_remove_task,
            "complete_task":       self._handle_complete_task,
            "run_command":         self._handle_run_command,
            "change_mode":         self._handle_change_mode,
            "time_date":           self._handle_time_date,
            "browser_open":        self._handle_browser_open,
            "browser_search":      self._handle_browser_search,
            "os_open_app":         self._handle_os_open_app,
            "os_type":             self._handle_os_type,
            "whatsapp_send":       self._handle_whatsapp_send,
            "whatsapp_read":       self._handle_whatsapp_read,
            # Google Workspace intents
            "gws_drive_list":      self._handle_gws_drive_list,
            "gws_drive_upload":    self._handle_gws_drive_upload,
            "gws_drive_download":  self._handle_gws_drive_download,
            "gws_drive_search":    self._handle_gws_drive_search,
            "gws_sheets_create":   self._handle_gws_sheets_create,
            "gws_sheets_append":   self._handle_gws_sheets_append,
            "gws_sheets_read":     self._handle_gws_sheets_read,
            "gws_gmail_send":      self._handle_gws_gmail_send,
            "gws_gmail_list":      self._handle_gws_gmail_list,
            "gws_gmail_read":      self._handle_gws_gmail_read,
            "gws_calendar_create": self._handle_gws_calendar_create,
            "gws_calendar_list":   self._handle_gws_calendar_list,
            "gws_docs_create":     self._handle_gws_docs_create,
            "gws_docs_list":       self._handle_gws_docs_list,
            "gws_publish_report":  self._handle_gws_publish_report,
            "general_chat":        self._handle_general_chat,
        }

        handler = dispatch.get(intent, self._handle_general_chat)
        # Run handler in daemon thread to keep GUI responsive
        threading.Thread(
            target=handler, args=(params,), daemon=True, name=f"Handler-{intent}"
        ).start()

    # ──────────────────── Intent Handlers ────────────────────────────────────

    def _handle_change_mode(self, params: Dict) -> None:
        mode = params.get("mode", "DEV").upper()
        if mode not in ("DEV", "MATE"):
            mode = "DEV"
            
        import config
        config.CURRENT_MODE = mode
        self.gui.set_mode_ui(mode)
        
        if mode == "MATE":
            msg = "😎 Switching to **MATE** mode! Let's have some fun while we code! 🎉"
        else:
            msg = "⚙️ Switching to **DEV** mode. Ready to get to work."
            
        self._reply(msg)

    def _handle_create_project(self, params: Dict) -> None:
        """
        Start multi-turn project creation:
          1. Open folder picker to choose parent directory
          2. Ask for project name (if not already provided)
          3. Create the project
        """
        name     = params.get("name", "").strip()
        language = params.get("language", "python")

        self._reply(
            f"📂 Let's create a **{language.capitalize()}** project!\n\n"
            "Please select the folder where you want to create the project."
        )
        self.gui.set_status("Opening folder picker …", ok=True)
        self.gui.set_busy(False)

        def _on_folder_selected(folder_path: str) -> None:
            if not folder_path:
                self.gui.add_message(
                    "bot",
                    "❌ Folder selection cancelled. Project was not created."
                )
                self.memory.add_message(
                    "assistant", "Folder selection cancelled."
                )
                self.gui.set_status("Ready", ok=True)
                return

            if name:
                # Name already provided — skip the name prompt, create immediately
                threading.Thread(
                    target=self._execute_create_project,
                    args=(name, language, folder_path),
                    daemon=True,
                    name="CreateProject-Worker",
                ).start()
            else:
                # Save state and ask for the project name
                self._pending_create_project = {
                    "language": language,
                    "base_dir": folder_path,
                }
                self.gui.add_message(
                    "bot",
                    f"✅ Folder selected: `{folder_path}`\n\n"
                    "📝 What would you like to name the project?"
                )
                self.memory.add_message(
                    "assistant",
                    f"Folder selected: {folder_path}. Waiting for project name."
                )
                self.gui.set_status("Waiting for project name …", ok=True)

        self.gui.open_folder_picker(_on_folder_selected)

    def _continue_create_project(self, user_text: str) -> None:
        """
        Handle the user's reply with the project name.
        Called from handle_text_input when _pending_create_project is set.
        """
        import re as _re
        name = user_text.strip()

        # Validate the project name
        if not _re.match(r'^[\w\-]+$', name):
            self._reply(
                "❌ Project names may only contain letters, numbers, "
                "hyphens, and underscores. Please try again."
            )
            self.gui.set_busy(False)
            self.gui.set_status("Waiting for project name …", ok=True)
            return

        language  = self._pending_create_project["language"]
        base_dir  = self._pending_create_project["base_dir"]
        self._pending_create_project = None  # clear pending state

        self._execute_create_project(name, language, base_dir)

    def _execute_create_project(
        self, name: str, language: str, base_dir: str
    ) -> None:
        """Actually create the project at the specified path."""
        self.gui.set_busy(True)
        self.gui.set_status(
            f"Creating {language} project '{name}' …", ok=True
        )
        self.gui.log_activity(
            f"Creating {language} project: {name} at {base_dir}"
        )

        ok, path = self.automation.create_project(
            name, language, base_dir=Path(base_dir)
        )
        if ok:
            self.memory.log_project(name, path, language)
            reply = (
                f"✅ **{language.capitalize()}** project **{name}** "
                f"created successfully!\n\n📁 Location:\n`{path}`"
            )
        else:
            reply = f"❌ Could not create project: {path}"

        self._reply(reply)

    def _handle_init_git(self, params: Dict) -> None:
        path = params.get("path", "")

        # Resolve vague paths like "my project" to the last created project
        if not path or not Path(path).exists():
            projects = self.memory.get_projects(limit=1)
            if projects:
                path = projects[0]["path"]
            else:
                self._reply(
                    "❌ No project found. Create a project first:\n"
                    '  Say: "Create a Python project called MyApp"'
                )
                return

        ok, msg = self.automation.git_init(path)
        self._reply(("✅ " if ok else "❌ ") + msg)

    def _handle_push_github(self, params: Dict) -> None:
        path    = params.get("path", "")
        remote  = params.get("remote", "origin")
        branch  = params.get("branch", "main")
        message = params.get("message", "Update via DEVMATE")
        name    = params.get("name", "")

        # If no path given, try the last created project from memory
        if not path or path == ".":
            projects = self.memory.get_projects(limit=1)
            if projects:
                path = projects[0]["path"]
            else:
                path = "."

        project_dir = Path(path)

        # Check if path exists
        if not project_dir.exists():
            self._reply(f"❌ Project path not found: {path}\nTry creating a project first.")
            return

        # Check if git is initialised
        git_dir = project_dir / ".git"
        if not git_dir.exists():
            self.gui.set_status("Initialising git …", ok=True)
            ok, msg = self.automation.git_init(str(project_dir))
            if not ok:
                self._reply(f"❌ Git init failed: {msg}")
                return
            self.gui.log_activity(f"✅ {msg}")

        self.gui.set_status("Committing & pushing …", ok=True)

        # Stage and commit (may return "nothing to commit" — that's OK)
        ok1, m1 = self.automation.git_add_commit(str(project_dir), message)
        if not ok1:
            self._reply(f"❌ Git commit failed: {m1}")
            return

        # Try pushing
        ok2, m2 = self.automation.git_push(str(project_dir), remote, branch)
        if ok2:
            self._reply(f"✅ {m2}")
            return

        # Push failed — try creating a GitHub repo
        repo_name = name or project_dir.name
        self.gui.set_status("Creating GitHub repo …", ok=True)
        ok3, m3 = self.automation.create_github_repo(
            repo_name, str(project_dir), private=False
        )
        if ok3:
            self._reply(f"✅ {m3}")
        else:
            self._reply(
                f"❌ Push failed: {m2}\n"
                f"❌ GitHub repo creation also failed: {m3}\n\n"
                f"💡 Make sure:\n"
                f"  1. GitHub CLI is installed: gh --version\n"
                f"  2. You are authenticated: gh auth login\n"
                f"  3. A remote is configured: git remote add origin <url>"
            )

    # ──────────────────── GitHub Repo Creation (multi-turn) ──────────────────

    def _handle_create_github_repo(self, params: Dict) -> None:
        """
        Start the multi-turn GitHub repo creation conversation.
        If the user already provided name and/or visibility in the first
        message we skip those questions.
        """
        name    = params.get("name", "").strip()
        private = params.get("private", None)  # None = not yet known

        self._pending_repo = {"step": None, "name": name, "private": private}

        if not name:
            # Ask for the repo name first
            self._pending_repo["step"] = "waiting_name"
            self._reply(
                "🐙 Let's create a GitHub repository!\n\n"
                "📝 What would you like to name the repository?"
            )
        elif private is None:
            # Name known, ask visibility
            self._pending_repo["step"] = "waiting_visibility"
            self._reply(
                f"🐙 Creating repo **{name}**\n\n"
                "🔒 Should it be **public** or **private**?"
            )
        else:
            # Everything known — proceed immediately
            self._pending_repo = None
            self._execute_create_github_repo(name, bool(private))

    def _continue_repo_creation(self, user_text: str) -> None:
        """
        Handle subsequent turns of the create-repo conversation.
        Called from handle_text_input when _pending_repo is set.
        """
        step = self._pending_repo.get("step")
        t    = user_text.strip()

        if step == "waiting_name":
            # Validate the name (alphanumeric, hyphens, underscores)
            import re as _re
            if not _re.match(r'^[\w\-]+$', t):
                self._reply(
                    "❌ Repository names may only contain letters, numbers, "
                    "hyphens, and underscores. Please try again."
                )
                self.gui.set_busy(False)
                self.gui.set_status("Waiting for repo name …", ok=True)
                return

            self._pending_repo["name"]    = t
            self._pending_repo["step"]    = "waiting_visibility"
            self._reply(
                f"✅ Repo name set to **{t}**\n\n"
                "🔒 Should it be **public** or **private**?"
            )
            self.gui.set_busy(False)
            self.gui.set_status("Waiting for visibility …", ok=True)

        elif step == "waiting_visibility":
            tl = t.lower()
            if any(w in tl for w in ("private", "yes", "priv", "secret")):
                private = True
            elif any(w in tl for w in ("public", "no", "pub", "open")):
                private = False
            else:
                self._reply(
                    "❓ I didn't catch that. Please reply **public** or **private**."
                )
                self.gui.set_busy(False)
                self.gui.set_status("Waiting for visibility …", ok=True)
                return

            name = self._pending_repo["name"]
            self._pending_repo = None  # clear pending state
            self._execute_create_github_repo(name, private)

        else:
            # Unknown step — cancel
            self._pending_repo = None
            self._reply("❌ Repo creation cancelled. Please try again.")

    def _execute_create_github_repo(self, name: str, private: bool) -> None:
        """Actually call gh CLI to create the repo (standalone, no project dir)."""
        visibility = "private" if private else "public"
        self.gui.set_status(f"Creating {visibility} GitHub repo '{name}' …", ok=True)
        self.gui.log_activity(f"Creating GitHub repo: {name} ({visibility})")

        ok, msg = self.automation.create_github_repo(name, ".", private=private)
        if ok:
            self._reply(
                f"✅ GitHub repository **{name}** created successfully!\n"
                f"🔒 Visibility: **{visibility}**\n\n"
                f"💡 You can push an existing project with:\n"
                f"  git remote add origin https://github.com/YOUR_USER/{name}.git\n"
                f"  git push -u origin main"
            )
        else:
            self._reply(
                f"❌ Failed to create repo '{name}'\n"
                f"Details: {msg}\n\n"
                "💡 Make sure:\n"
                "  1. GitHub CLI is installed: gh --version\n"
                "  2. You are authenticated: gh auth login"
            )

    # ──────────────────────── Push Files to GitHub Repo ────────────────────────

    def _handle_push_files_to_repo(self, params: Dict) -> None:
        """
        Entry point for 'push files to <repo>' intent.
        If the repo name is already in params, open the file picker now.
        Otherwise ask the user which repo to target first.
        """
        repo = params.get("repo", "").strip()

        if repo:
            # Repo name known — go straight to file picker
            self._open_picker_for_repo(repo)
        else:
            # Ask for the repo name
            self._pending_push = {"repo": ""}
            self._reply(
                "\U0001f4c2 Let's push your files to GitHub!\n\n"
                "\U0001f4dd Which repository should I push the files to? "
                "(enter the repo name)"
            )

    def _continue_push_files(self, user_text: str) -> None:
        """
        Pending-state handler — receives the repo name from the user's reply
        and then opens the file picker.
        """
        import re as _re
        repo = user_text.strip()
        if not _re.match(r'^[\w\-]+$', repo):
            self._reply(
                "\u274c Repo names may only contain letters, numbers, hyphens, "
                "and underscores. Please try again."
            )
            self.gui.set_busy(False)
            self.gui.set_status("Waiting for repo name ...", ok=True)
            return

        self._pending_push = None  # clear pending state
        self._open_picker_for_repo(repo)

    def _open_picker_for_repo(self, repo: str) -> None:
        """Open the OS file picker then launch the background push worker."""
        self._reply(
            f"\U0001f4c2 Opening file picker for repo **{repo}** ...\n"
            "Please select the files you want to push."
        )
        self.gui.set_status("Opening file picker ...", ok=True)
        # set_busy(False) so the input bar doesn't block while the picker is open
        self.gui.set_busy(False)

        def _on_files_selected(file_paths: list) -> None:
            if not file_paths:
                self.gui.add_message(
                    "bot",
                    "\u274c File selection cancelled. No files were pushed."
                )
                self.memory.add_message(
                    "assistant",
                    "File selection cancelled."
                )
                self.gui.set_status("Ready", ok=True)
                return

            # Run the actual push in a background thread
            self.gui.set_busy(True)
            self.gui.set_status(
                f"Pushing {len(file_paths)} file(s) to '{repo}' ...", ok=True
            )
            threading.Thread(
                target=self._do_push_files,
                args=(repo, list(file_paths)),
                daemon=True,
                name="PushFiles-Worker",
            ).start()

        self.gui.open_mixed_picker(_on_files_selected)

    def _do_push_files(
        self, repo: str, file_paths: list
    ) -> None:
        """Background worker: commit and push selected files to GitHub."""
        n = len(file_paths)
        names = ", ".join(Path(p).name for p in file_paths[:5])
        if n > 5:
            names += f" ... (+{n - 5} more)"

        self.gui.add_message(
            "system",
            f"Staging {n} file(s): {names}"
        )
        self.gui.log_activity(f"Pushing {n} file(s) to '{repo}'")

        commit_msg = f"Add {n} file(s) via DEVMATE"
        ok, msg = self.automation.push_files_to_repo(
            repo_name=repo,
            file_paths=file_paths,
            commit_message=commit_msg,
            private=False,
        )

        if ok:
            self._reply(
                f"\u2705 Successfully pushed **{n} file(s)** to **{repo}**!\n\n"
                f"\U0001f4c4 Files pushed:\n"
                + "\n".join(f"  \u2022 {Path(p).name}" for p in file_paths)
                + f"\n\n\U0001f4a1 View on GitHub:\n"
                  f"  https://github.com/YOUR_USER/{repo}"
            )
        else:
            self._reply(
                f"\u274c Push failed: {msg}\n\n"
                "\U0001f4a1 Make sure:\n"
                "  1. GitHub CLI is installed: gh --version\n"
                "  2. You are authenticated: gh auth login"
            )

    # ── Delete GitHub Repo (with confirmation) ──────────────────────────────

    def _handle_delete_github_repo(self, params: Dict) -> None:
        name = params.get("name", "").strip()
        if not name:
            # Ask for repo name
            self._reply(
                "\U0001f5d1\ufe0f Which repository do you want to delete? "
                "(enter the exact repo name)"
            )
            return
        self._confirm_and_delete_repo(name)

    def _confirm_and_delete_repo(self, name: str) -> None:
        """Ask the user to confirm before permanently deleting a repo."""
        self._pending_confirm_delete = name
        self._reply(
            f"\u26a0\ufe0f Are you sure you want to **permanently delete** "
            f"repo **{name}**?\n\n"
            "This **cannot be undone**! "
            "Reply **yes** to confirm or **no** to cancel."
        )
        self.gui.set_busy(False)
        self.gui.set_status("Waiting for delete confirmation ...", ok=False)

    def _process_delete_confirm(self, user_text: str) -> None:
        """Handle the yes/no confirmation reply for repo deletion."""
        tl = user_text.strip().lower()
        repo = self._pending_confirm_delete
        self._pending_confirm_delete = None
        if tl in ('yes', 'y', 'confirm', 'ok', 'sure', 'delete'):
            self.gui.set_status(f"Deleting repo '{repo}' ...", ok=False)
            self.gui.log_activity(f"Deleting GitHub repo: {repo}")
            ok, msg = self.automation.delete_github_repo(repo)
            if ok:
                self._reply(
                    f"\u2705 Repository **{repo}** permanently deleted."
                )
            else:
                self._reply(f"\u274c {msg}")
        else:
            self._reply(f"\u274c Deletion of **{repo}** cancelled. Your repo is safe.")

    def _handle_delete_file_from_repo(self, params: Dict) -> None:
        file_name = params.get("file", "").strip()
        repo = params.get("repo", "").strip()
        if not file_name or not repo:
            self._reply(
                "\u274c Please specify both the filename and repo.\n"
                "Example: \"delete index.html from my-repo\""
            )
            return
        self.gui.set_status(f"Deleting '{file_name}' from '{repo}' ...", ok=True)
        self.gui.log_activity(f"Delete file: {file_name} from {repo}")
        ok, msg = self.automation.delete_file_from_repo(repo, file_name)
        if ok:
            self._reply(
                f"\u2705 File **{file_name}** deleted from **{repo}**!\n"
                f"\U0001f4a1 The deletion has been committed to the repo."
            )
        else:
            self._reply(f"\u274c {msg}")


    # ── Download GitHub Repo & File ──────────────────────────────

    def _handle_download_github_repo(self, params: Dict) -> None:
        name = params.get("name", "").strip()
        if not name:
            self._reply(
                "\U0001f4e5 Which repository do you want to download? "
                "(enter the exact repo name)"
            )
            return
        
        from pathlib import Path
        downloads_dir = str(Path.home() / "Downloads")
        self.gui.set_status(f"Downloading repo '{name}' ...", ok=True)
        self.gui.log_activity(f"Downloading repo: {name}")
        
        ok, msg, dest = self.automation.download_github_repo(name, downloads_dir)
        if ok:
            self._reply(f"\u2705 Repository **{name}** cloned successfully!\n\n\U0001f4c1 Saved to:\n`{dest}`")
        else:
            self._reply(f"\u274c {msg}")

    def _handle_download_file_from_repo(self, params: Dict) -> None:
        file_name = params.get("file", "").strip()
        repo = params.get("repo", "").strip()
        if not file_name or not repo:
            self._reply("\u274c Please specify both the filename and repo.\nExample: \"download index.html from my-repo\"")
            return
        
        from pathlib import Path
        downloads_dir = str(Path.home() / "Downloads")
        self.gui.set_status(f"Downloading '{file_name}' from '{repo}' ...", ok=True)
        self.gui.log_activity(f"Downloading file: {file_name} from {repo}")
        
        ok, msg, dest = self.automation.download_file_from_repo(repo, file_name, downloads_dir)
        if ok:
            self._reply(f"\u2705 File **{file_name}** downloaded successfully!\n\n\U0001f4c1 Saved to:\n`{dest}`")
        else:
            self._reply(f"\u274c {msg}")

    def _handle_add_reminder(self, params: Dict) -> None:

        text = params.get("text", "Reminder")
        when = params.get("when", "in 5 minutes")
        ok, msg = self.scheduler.add_reminder(text, when)
        self._reply(msg)

    def _handle_list_tasks(self, _: Dict) -> None:
        self._reply(self.tasks.format_list())
        self.gui.refresh_tasks(self.tasks.list_tasks())

    def _handle_add_task(self, params: Dict) -> None:
        text     = params.get("text", "New task")
        priority = params.get("priority", "medium")
        task = self.tasks.add_task(text, priority)
        self.gui.refresh_tasks(self.tasks.list_tasks())
        pri_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        self._reply(
            f"✅ Task [{task['id']}] added: '{text}' "
            f"({pri_icons.get(priority, '○')} {priority})"
        )

    def _handle_remove_task(self, params: Dict) -> None:
        task_id = params.get("id", "")
        removed = self.tasks.remove_task(task_id)
        self.gui.refresh_tasks(self.tasks.list_tasks())
        self._reply(
            f"✅ Task {task_id} removed." if removed else f"❌ Task {task_id} not found."
        )

    def _handle_complete_task(self, params: Dict) -> None:
        task_id = params.get("id", "")
        task = self.tasks.complete_task(task_id)
        self.gui.refresh_tasks(self.tasks.list_tasks())
        if task:
            self._reply(f"✅ Task [{task_id}] marked as done: '{task['text']}'")
        else:
            self._reply(f"❌ Task {task_id} not found.")

    def _handle_run_command(self, params: Dict) -> None:
        command = params.get("command", "")
        cwd     = params.get("cwd", None)

        if not command:
            self._reply("❌ No command provided.")
            return

        self.gui.set_status(f"Running: {command[:50]}", ok=True)
        self.memory.log_command(command)

        ok, msg = self.automation.run_command(command, cwd=cwd, stream=True)
        self._reply(f"{'✅' if ok else '❌'} {msg}")

    def _handle_time_date(self, params: Dict) -> None:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%A, %B %d, %Y")
        self._reply(f"🕐 It's **{time_str}** on **{date_str}**")

    def _handle_browser_open(self, params: Dict) -> None:
        url = params.get("url", "")
        if not url:
            self._reply("❌ No URL provided.")
            return
        self.gui.set_status(f"Opening browser to {url}...", ok=True)
        ok = self.browser.open_url(url)
        if ok:
            self._reply(f"✅ Opened browser navigating to {url}")
        else:
            self._reply("❌ Failed to open URL in browser.")

    def _handle_browser_search(self, params: Dict) -> None:
        query = params.get("query", "")
        if not query:
            self._reply("❌ No search query provided.")
            return
        self.gui.set_status(f"Searching Google for {query}...", ok=True)
        ok = self.browser.search_google(query)
        if ok:
            self._reply(f"✅ Performed Google search for: '{query}'")
        else:
            self._reply("❌ Failed to perform search.")

    def _handle_os_open_app(self, params: Dict) -> None:
        name = params.get("name", "")
        if not name:
            self._reply("❌ No app name provided.")
            return
        self.gui.set_status(f"Opening application: {name}...", ok=True)
        ok = self.os_auto.open_app(name)
        if ok:
            self._reply(f"✅ Attempted to open application: {name}")
        else:
            self._reply(f"❌ Failed to open application: {name}")

    def _handle_os_type(self, params: Dict) -> None:
        text = params.get("text", "")
        if not text:
            self._reply("❌ No text to type provided.")
            return
        self.gui.set_status(f"Typing text...", ok=True)
        ok = self.os_auto.type_text(text)
        if ok:
            self._reply("✅ Successfully typed the requested text.")
        else:
            self._reply("❌ Failed to type text. Check if OS automation is enabled.")

    def _handle_whatsapp_send(self, params: Dict) -> None:
        contact = params.get("contact", "")
        message = params.get("message", "")
        if not contact or not message:
            self._reply("❌ Please specify both the contact and the message.")
            return
            
        self._pending_whatsapp = {"contact": contact, "message": message}
        self._reply(f"Do you want me to send the following message to **{contact}**?\n\n\"{message}\"\n\n*(Reply with 'yes' or 'no')*")

    def _continue_whatsapp_send(self, text: str) -> None:
        state = self._pending_whatsapp
        self._pending_whatsapp = None
        
        text_lower = text.lower().strip()
        if text_lower in ["yes", "y", "sure", "ok", "send it", "do it", "yeah"]:
            self.gui.set_status("Sending WhatsApp message...", ok=True)
            ok = self.os_auto.send_whatsapp_message(state["contact"], state["message"])
            if ok:
                self._reply("✅ WhatsApp message sent successfully!")
            else:
                self._reply("❌ Failed to send WhatsApp message.")
        else:
            self._reply("🚫 WhatsApp message sending cancelled.")
            
    def _handle_whatsapp_read(self, params: Dict) -> None:
        contact = params.get("contact", "")
        if not contact:
            self._reply("❌ Please specify the contact whose messages you want to read.")
            return
            
        self.gui.set_status(f"Reading WhatsApp messages from {contact}...", ok=True)
        text = self.os_auto.read_whatsapp_messages(contact)
        if text:
            # truncate to avoid spamming the chat if it's too long
            display_text = text[-500:] if len(text) > 500 else text
            prefix = "[...]" if len(text) > 500 else ""
            self._reply(f"📱 **Messages from {contact}:**\n\n```text\n{prefix}{display_text}\n```")
            self.speech.speak_async(f"Here are the latest messages from {contact}.")
        else:
            self._reply(f"❌ Could not retrieve messages from {contact}.")

    def _handle_general_chat(self, params: Dict = None) -> None:
        # Retrieve the last user message from context
        context = self.memory.get_context()
        user_text = context[-1]["content"] if context else ""
        self.gui.set_status("Generating response …", ok=True)

        # Open a bot bubble immediately — tokens will stream into it
        self.gui.begin_stream_message()

        def _on_token(token: str) -> None:
            self.gui.append_stream_token(token)

        def _on_done(full_reply: str) -> None:
            # Add a trailing newline to close the bubble cleanly
            self.gui.append_stream_token("\n")
            # Persist to memory and trigger TTS with the complete reply
            self.memory.add_message("assistant", full_reply)
            self.gui.set_busy(False)
            self.gui.set_status("Ready", ok=True)
            self.gui.log_activity(f"Bot: {full_reply[:60]}")
            if self.gui.tts_enabled:
                self.speech.speak_async(full_reply)

        self.llm.chat_stream_async(
            user_text,
            context[:-1],
            on_token=_on_token,
            on_done=_on_done,
        )

    # ──────────────────── Callbacks ───────────────────────────────────────────

    def _reply(self, text: str) -> None:
        """Common output path: GUI + memory + TTS."""
        self.gui.add_message("bot", text)
        self.memory.add_message("assistant", text)
        self.gui.set_busy(False)
        self.gui.set_status("Ready", ok=True)
        self.gui.log_activity(f"Bot: {text[:60]}")
        # TTS (non-blocking, respects toggle)
        if self.gui.tts_enabled:
            self.speech.speak_async(text)

    # ──────────────────── Google Workspace Handlers ───────────────────────────

    def _gws_auth_guard(self) -> bool:
        """
        Check GWS authentication. If not authenticated, show instructions
        and return False. Otherwise return True.
        """
        if not self.gws.check_auth():
            self._reply(self.gws.get_auth_instructions())
            return False
        return True

    def _gws_reply(self, ok: bool, msg: str) -> None:
        """Format a GWS result with mode-awareness and reply."""
        import config as _cfg
        if ok:
            prefix = "✅ " if _cfg.CURRENT_MODE == "DEV" else "🎉 Nice! "
        else:
            prefix = "❌ " if _cfg.CURRENT_MODE == "DEV" else "😬 Oops — "
        self._reply(f"{prefix}{msg}")

    # ── Drive ────────────────────────────────────────────────────────────────

    def _handle_gws_drive_list(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        self.gui.set_status("Listing Drive files …", ok=True)
        self.gui.log_activity("GWS: listing Drive files")
        ok, msg = self.gws.drive_list()
        self._gws_reply(ok, msg)

    def _handle_gws_drive_upload(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        file_path = params.get("file_path", "").strip()
        if not file_path:
            self._reply("❌ Please specify which file to upload.\nExample: \"upload report.pdf to drive\"")
            return
        self.gui.set_status(f"Uploading '{file_path}' to Drive …", ok=True)
        self.gui.log_activity(f"GWS: uploading {file_path} to Drive")
        ok, msg = self.gws.drive_upload(file_path)
        self._gws_reply(ok, msg)

    def _handle_gws_drive_download(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        file_name = params.get("file_name", "").strip()
        if not file_name:
            self._reply("❌ Please specify which file to download.\nExample: \"download drive file report.pdf\"")
            return
        self.gui.set_status(f"Downloading '{file_name}' from Drive …", ok=True)
        self.gui.log_activity(f"GWS: downloading {file_name} from Drive")
        ok, msg = self.gws.drive_download(file_name)
        self._gws_reply(ok, msg)

    def _handle_gws_drive_search(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        query = params.get("query", "").strip()
        if not query:
            self._reply("❌ Please provide a search term.\nExample: \"search drive for budget\"")
            return
        self.gui.set_status(f"Searching Drive for '{query}' …", ok=True)
        self.gui.log_activity(f"GWS: searching Drive for '{query}'")
        ok, msg = self.gws.drive_search(query)
        self._gws_reply(ok, msg)

    # ── Sheets ───────────────────────────────────────────────────────────────

    def _handle_gws_sheets_create(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        title = params.get("title", "").strip()
        if not title:
            self._reply("❌ Please provide a spreadsheet name.\nExample: \"create sheet bug_tracker\"")
            return
        self.gui.set_status(f"Creating spreadsheet '{title}' …", ok=True)
        self.gui.log_activity(f"GWS: creating spreadsheet '{title}'")
        ok, msg = self.gws.sheets_create(title)
        self._gws_reply(ok, msg)

    def _handle_gws_sheets_append(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        title = params.get("title", "").strip()
        spreadsheet_id = params.get("spreadsheet_id", "").strip()
        values = params.get("values", "")
        if not spreadsheet_id and not title:
            self._reply("❌ Please specify the spreadsheet.\nExample: \"add row to sheet bug_tracker\"")
            return
        sid = spreadsheet_id or title
        self.gui.set_status(f"Appending rows to '{sid}' …", ok=True)
        self.gui.log_activity(f"GWS: appending to spreadsheet '{sid}'")
        ok, msg = self.gws.sheets_append(sid, "Sheet1!A:Z", values or "")
        self._gws_reply(ok, msg)

    def _handle_gws_sheets_read(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        title = params.get("title", "").strip()
        spreadsheet_id = params.get("spreadsheet_id", "").strip()
        if not spreadsheet_id and not title:
            self._reply("❌ Please specify the spreadsheet.\nExample: \"read sheet bug_tracker\"")
            return
        sid = spreadsheet_id or title
        self.gui.set_status(f"Reading spreadsheet '{sid}' …", ok=True)
        self.gui.log_activity(f"GWS: reading spreadsheet '{sid}'")
        ok, msg = self.gws.sheets_read(sid)
        self._gws_reply(ok, msg)

    # ── Gmail ────────────────────────────────────────────────────────────────

    def _handle_gws_gmail_send(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        to = params.get("to", "").strip()
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to:
            self._reply("❌ Please specify a recipient.\nExample: \"send email to user@example.com\"")
            return
        # If only recipient given, ask for subject/body could be done here
        # For now, use defaults
        if not subject:
            subject = "Message from DevMate"
        if not body:
            body = "Sent via DevMate assistant."
        self.gui.set_status(f"Sending email to '{to}' …", ok=True)
        self.gui.log_activity(f"GWS: sending email to {to}")
        ok, msg = self.gws.gmail_send(to, subject, body)
        self._gws_reply(ok, msg)

    def _handle_gws_gmail_list(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        self.gui.set_status("Listing inbox messages …", ok=True)
        self.gui.log_activity("GWS: listing inbox")
        ok, msg = self.gws.gmail_list()
        self._gws_reply(ok, msg)

    def _handle_gws_gmail_read(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        message_id = params.get("message_id", "").strip()
        if not message_id:
            self._reply("❌ Please provide a message ID.\nExample: \"read email 18abc123\"")
            return
        self.gui.set_status(f"Reading email {message_id} …", ok=True)
        self.gui.log_activity(f"GWS: reading email {message_id}")
        ok, msg = self.gws.gmail_read(message_id)
        self._gws_reply(ok, msg)

    # ── Calendar ─────────────────────────────────────────────────────────────

    def _handle_gws_calendar_create(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        summary = params.get("summary", "").strip()
        start_time = params.get("start_time", "").strip()
        end_time = params.get("end_time", "")
        if not summary:
            self._reply("❌ Please provide an event name.\nExample: \"schedule playtest tomorrow at 6pm\"")
            return
        if not start_time:
            self._reply("❌ Please provide a time for the event.\nExample: \"schedule playtest tomorrow at 6pm\"")
            return
        self.gui.set_status(f"Creating event '{summary}' …", ok=True)
        self.gui.log_activity(f"GWS: creating event '{summary}' at {start_time}")
        ok, msg = self.gws.calendar_create(summary, start_time, end_time)
        self._gws_reply(ok, msg)

    def _handle_gws_calendar_list(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        self.gui.set_status("Listing calendar events …", ok=True)
        self.gui.log_activity("GWS: listing calendar events")
        ok, msg = self.gws.calendar_list()
        self._gws_reply(ok, msg)

    # ── Docs ─────────────────────────────────────────────────────────────────

    def _handle_gws_docs_create(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        title = params.get("title", "").strip()
        if not title:
            self._reply("❌ Please provide a document title.\nExample: \"create document design_spec\"")
            return
        self.gui.set_status(f"Creating document '{title}' …", ok=True)
        self.gui.log_activity(f"GWS: creating document '{title}'")
        ok, msg = self.gws.docs_create(title)
        self._gws_reply(ok, msg)

    def _handle_gws_docs_list(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        self.gui.set_status("Listing documents …", ok=True)
        self.gui.log_activity("GWS: listing documents")
        ok, msg = self.gws.docs_list()
        self._gws_reply(ok, msg)

    # ── Publish Report (composite) ───────────────────────────────────────────

    def _handle_gws_publish_report(self, params: Dict) -> None:
        if not self._gws_auth_guard():
            return
        self.gui.set_status("Publishing report …", ok=True)
        self.gui.log_activity("GWS: publishing report")
        ok, msg = self.gws.publish_report(
            output_callback=lambda s: self.gui.add_message("system", s)
        )
        self._gws_reply(ok, msg)

    def _on_cmd_output(self, line: str) -> None:
        """Stream subprocess output to both chat and activity log."""
        self.gui.add_message("system", line)
        self.gui.log_activity(line[:80])

    def _on_reminder_fire(self, reminder_id: str, text: str) -> None:
        """Called by SchedulerModule when a reminder fires."""
        self.gui.show_reminder_popup(text)
        self.gui.add_message("bot", f"⏰ Reminder: {text}")
        self.gui.log_activity(f"Reminder fired: {text}")
        if self.gui.tts_enabled:
            self.speech.speak_async(f"Reminder: {text}")

    # ──────────────────── Welcome & Idle ────────────────────────────────────

    def _speak_welcome(self) -> None:
        """Spoken welcome greeting on launch (called via gui.after)."""
        greeting = (
            "Hey! 👋 Welcome back to DEVMATE!\n\n"
            "I'm your developer buddy — ready to create projects, "
            "manage GitHub repos, run commands, and more.\n"
            "What would you like to work on today?"
        )
        self.gui.add_message("bot", greeting)
        self.memory.add_message("assistant", greeting)
        self.gui.log_activity("Welcome greeting")
        if self.gui.tts_enabled:
            self.speech.speak_async(
                "Hey! Welcome back to DEVMATE! "
                "I'm your developer buddy. What would you like to work on today?"
            )

    def _reset_idle_timer(self) -> None:
        """Cancel existing idle timer and start a fresh one."""
        self._last_activity = time.time()
        if self._idle_timer_id is not None:
            self.gui.after_cancel(self._idle_timer_id)
        self._idle_timer_id = self.gui.after(
            config.IDLE_TIMEOUT_SEC * 1000, self._on_idle
        )

    def _on_idle(self) -> None:
        """Fired when the user has been idle too long. Sends a friendly nudge."""
        msg = random.choice(self._idle_messages)
        self.gui.add_message("bot", msg)
        self.memory.add_message("assistant", msg)
        self.gui.log_activity(f"Idle nudge: {msg[:40]}")
        if self.gui.tts_enabled:
            self.speech.speak_async(msg)
        # Schedule next idle nudge
        self._idle_timer_id = self.gui.after(
            config.IDLE_REPEAT_SEC * 1000, self._on_idle
        )

    # ──────────────────── Lifecycle ───────────────────────────────────────────

    def run(self) -> None:
        """Start the Tkinter main loop."""
        import config
        if getattr(config, "FACE_RECOGNITION_ENABLED", False):
            if not self.face_rec.available:
                print("Face recognition disabled because dependencies are missing. Bypassing security.")
            elif not self.face_rec.is_registered():
                print("Face not registered, running registration...")
                success, msg = self.face_rec.capture_reference()
                if not success:
                    print(f"Registration failed: {msg}. Exiting.")
                    return
            else:
                print("Starting face authentication...")
                authenticated, msg = self.face_rec.authenticate(timeout=15)
                if not authenticated:
                    print(f"Authentication failed: {msg}. Exiting.")
                    sys.exit(1)
                print(f"Authenticated: {msg}")
                
        self.gui.mainloop()
        self._shutdown()

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down DEVMATE …")
        if self._idle_timer_id is not None:
            self.gui.after_cancel(self._idle_timer_id)
        self.scheduler.cancel_all()
        self.memory.close()
        logger.info("DEVMATE shutdown complete.")
