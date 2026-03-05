"""
DEVMATE – Automation Module
Combines three automation concerns:
  1. Project Initialisation — scaffold new projects (Python/Node/React/Angular)
  2. Git & GitHub CLI       — init, commit, push, create GitHub repos
  3. Safe Command Execution — whitelist-filtered subprocess runner with streaming
"""

import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Project Templates
# ─────────────────────────────────────────────────────────────────────────────
# Languages that use CLI scaffolding (npx) — no static templates needed
_CLI_LANGUAGES = {"react", "angular"}

# Languages that use static file templates
_TEMPLATES: Dict[str, Dict[str, str]] = {
    "python": {
        "main.py": '"""Entry point."""\n\ndef main():\n    print("Hello, {name}!")\n\nif __name__ == "__main__":\n    main()\n',
        "requirements.txt": "# Add your dependencies here\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n*.egg-info/\n",
    },
    "node": {
        "index.js": 'const express = require("express");\nconst app = express();\napp.listen(3000, () => console.log("{name} running on :3000"));\n',
        "package.json": '{{\n  "name": "{name}",\n  "version": "1.0.0",\n  "dependencies": {{\n    "express": "^4.18.0"\n  }}\n}}\n',
        ".gitignore": "node_modules/\n.env\n",
    },
}

_README_TEMPLATE = """# {name}

> Created with DEVMATE ⚡

## Getting Started

```bash
# Clone this repo
git clone <repo-url>
cd {name}
```

## Description

_Add your project description here._
"""


# ─────────────────────────────────────────────────────────────────────────────
# AutomationModule
# ─────────────────────────────────────────────────────────────────────────────
class AutomationModule:
    """Handles project scaffolding, Git operations, and safe command execution."""

    def __init__(self, output_callback: Optional[Callable[[str], None]] = None):
        """
        Args:
            output_callback: called with each line of subprocess output.
                             Defaults to logging.
        """
        self._output_cb = output_callback or (lambda line: logger.info("[CMD] %s", line))
        self._cmd_lock = threading.Lock()

    # ──────────────────── Helpers ─────────────────────────────────────────────

    def _emit(self, text: str) -> None:
        """Send a line to the output callback."""
        try:
            self._output_cb(text)
        except Exception:
            pass

    def set_output_callback(self, cb: Callable[[str], None]) -> None:
        self._output_cb = cb

    # ──────────────────── Project Initialisation ─────────────────────────────

    def create_project(
        self,
        name: str,
        language: str = "python",
        base_dir: Optional[Path] = None,
        create_venv: bool = True,
    ) -> Tuple[bool, str]:
        """
        Scaffold a new project directory.

        Supports:
          - python : static template + venv
          - node   : static template (Express)
          - react  : npx create-react-app
          - angular: npx @angular/cli new

        Returns:
            (success: bool, project_path: str)
        """
        language = language.lower().strip()
        all_supported = set(_TEMPLATES.keys()) | _CLI_LANGUAGES
        if language not in all_supported:
            language = "python"

        base = Path(base_dir) if base_dir else config.BASE_PROJECT_DIR
        project_path = base / name

        # ── CLI-scaffolded projects (React / Angular) ────────────────────
        if language in _CLI_LANGUAGES:
            return self._create_cli_project(name, language, base, project_path)

        # ── Template-based projects (Python / Node) ──────────────────────
        try:
            project_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return False, f"Directory already exists: {project_path}"
        except Exception as e:
            return False, f"Cannot create directory: {e}"

        # Write template files
        template = _TEMPLATES[language]
        for filename, content in template.items():
            file_path = project_path / filename
            file_path.write_text(content.format(name=name), encoding="utf-8")
            self._emit(f"  ✅ Created {filename}")

        # Write README
        (project_path / "README.md").write_text(
            _README_TEMPLATE.format(name=name), encoding="utf-8"
        )
        self._emit("  ✅ Created README.md")

        # Python: create virtual environment
        if language == "python" and create_venv:
            venv_path = project_path / ".venv"
            self._emit("  📦 Creating virtual environment …")
            result = self._run_subprocess(
                [sys.executable, "-m", "venv", str(venv_path)],
                cwd=str(project_path),
                stream=False,
            )
            if result == 0:
                self._emit("  ✅ Virtual environment created at .venv/")
            else:
                self._emit("  ⚠️  venv creation failed (non-fatal)")

        self._emit(f"\n🎉 Project '{name}' created at: {project_path}")
        return True, str(project_path)

    def _create_cli_project(
        self,
        name: str,
        language: str,
        base: Path,
        project_path: Path,
    ) -> Tuple[bool, str]:
        """
        Scaffold a React or Angular project using their official CLIs.
        The CLI itself creates the project directory.

        Returns:
            (success: bool, project_path: str)
        """
        if project_path.exists():
            return False, f"Directory already exists: {project_path}"

        # Ensure the base directory exists
        base.mkdir(parents=True, exist_ok=True)

        if language == "react":
            self._emit(f"  ⚛️  Scaffolding React project '{name}' …")
            self._emit("  📦 Running: npx create-react-app (this may take a minute) …")
            cmd = ["npx", "-y", "create-react-app", name]
        elif language == "angular":
            self._emit(f"  🅰️  Scaffolding Angular project '{name}' …")
            self._emit("  📦 Running: npx @angular/cli new (this may take a minute) …")
            cmd = ["npx", "-y", "-p", "@angular/cli@latest", "ng", "new", name,
                   "--skip-git", "--defaults"]
        else:
            return False, f"Unknown CLI language: {language}"

        rc = self._run_subprocess(cmd, cwd=str(base), stream=True)

        if rc != 0:
            return False, (
                f"CLI scaffolding failed (exit code {rc}). "
                f"Make sure Node.js and npm are installed."
            )

        # Add README if the CLI didn't create one
        readme_path = project_path / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                _README_TEMPLATE.format(name=name), encoding="utf-8"
            )
            self._emit("  ✅ Created README.md")

        self._emit(f"\n🎉 {language.capitalize()} project '{name}' created at: {project_path}")
        return True, str(project_path)

    # ──────────────────── Git Operations ─────────────────────────────────────

    def git_init(self, path: str) -> Tuple[bool, str]:
        """Run `git init` in *path*."""
        p = Path(path)
        if not p.exists():
            return False, f"Path does not exist: {path}"

        rc = self._run_subprocess(["git", "init", str(p)], cwd=str(p))
        if rc == 0:
            return True, f"Git repository initialised in {path}"
        return False, "git init failed (is Git installed?)"

    def git_add_commit(
        self, path: str, message: str = "Initial commit"
    ) -> Tuple[bool, str]:
        """Stage all files and commit. Returns success even if nothing to commit."""
        p = str(Path(path))
        rc1 = self._run_subprocess(["git", "add", "."], cwd=p)
        if rc1 != 0:
            return False, "git add failed"

        # Check if there are staged changes before committing
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=p, capture_output=True, text=True, encoding="utf-8"
            )
            if not result.stdout.strip():
                return True, "Nothing to commit — all files already up to date."
        except Exception:
            pass  # proceed with commit anyway

        rc2 = self._run_subprocess(["git", "commit", "-m", message], cwd=p)
        if rc2 != 0:
            return False, "git commit failed"
        return True, f"Committed with message: '{message}'"

    def git_push(
        self,
        path: str,
        remote: str = "origin",
        branch: str = "",
    ) -> Tuple[bool, str]:
        """Push to remote. Auto-detects current branch if not specified."""
        cwd = str(Path(path))

        # Auto-detect the current branch name
        if not branch:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=cwd, capture_output=True, text=True, encoding="utf-8"
                )
                branch = result.stdout.strip() or "main"
            except Exception:
                branch = "main"

        rc = self._run_subprocess(
            ["git", "push", "-u", remote, branch], cwd=cwd
        )
        if rc == 0:
            return True, f"Pushed to {remote}/{branch}"
        return False, "git push failed"

    def create_github_repo(
        self,
        name: str,
        path: str = ".",
        private: bool = False,
    ) -> Tuple[bool, str]:
        """Create a GitHub repo via `gh` CLI.

        If *path* points to a Git repository, also adds it as the remote and
        pushes.  Otherwise creates a bare remote-only repo (standalone mode).
        """
        privacy_flag = "--private" if private else "--public"
        project_dir  = Path(path).resolve()
        git_dir      = project_dir / ".git"
        has_git      = git_dir.exists()

        if has_git:
            # Local git repo exists — source + push
            rc = self._run_subprocess(
                ["gh", "repo", "create", name, privacy_flag,
                 "--source", ".", "--push"],
                cwd=str(project_dir),
            )
        else:
            # Standalone — just create the remote repo (no local source)
            rc = self._run_subprocess(
                ["gh", "repo", "create", name, privacy_flag],
                cwd=str(project_dir) if project_dir.exists() else ".",
            )

        if rc == 0:
            return True, f"GitHub repo '{name}' created successfully."
        return False, "gh repo create failed (is GitHub CLI installed and authenticated?)"

    def push_files_to_repo(
        self,
        repo_name: str,
        file_paths: List[str],
        commit_message: str = "Update files via DEVMATE",
        private: bool = False,
    ) -> Tuple[bool, str]:
        """
        Push (add or update) selected files to an existing GitHub repository
        WITHOUT deleting any other files already in the repo.

        Strategy:
          1. Resolve GitHub username via `gh api user`.
          2. Clone the target repo into a temp directory.
             If the repo does not yet exist, create it first then clone.
          3. Copy each selected file into the cloned directory
             (preserving filename; deduplicates on name clash with a counter).
          4. git add . -> git commit -> git push.
          5. Clean up the temp clone on failure.

        Returns:
            (success: bool, message: str)
        """
        import shutil as _shutil
        import tempfile
        import subprocess as _sub

        if not file_paths:
            return False, "No files provided to push."

        # 1. Resolve GitHub username
        try:
            up = _sub.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, encoding="utf-8", timeout=10
            )
            gh_user = up.stdout.strip()
        except Exception as e:
            return False, f"Could not resolve GitHub username: {e}"

        if not gh_user:
            return False, "GitHub username not found. Run: gh auth login"

        repo_full = f"{gh_user}/{repo_name}"
        clone_url  = f"https://github.com/{repo_full}.git"

        # 2. Clone (or create then clone) into a temp directory
        tmp_dir = Path(tempfile.mkdtemp(prefix="devmate_push_"))
        clone_dir = tmp_dir / repo_name
        self._emit(f"  Cloning '{repo_full}' ...")

        clone_rc = self._run_subprocess(
            ["gh", "repo", "clone", repo_full, str(clone_dir)],
            cwd=str(tmp_dir),
        )

        if clone_rc != 0:
            # Repo likely doesn't exist yet — create it and clone
            self._emit(f"  Repo not found. Creating '{repo_name}' on GitHub ...")
            privacy_flag = "--private" if private else "--public"
            create_rc = self._run_subprocess(
                ["gh", "repo", "create", repo_name, privacy_flag],
                cwd=str(tmp_dir),
            )
            if create_rc != 0:
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False, (
                    f"Could not create repo '{repo_name}'. "
                    "Check your gh auth and try again."
                )
            # Initialise local clone with a dummy README so clone works
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "README.md").write_text(f"# {repo_name}\n", encoding="utf-8")
            if self._run_subprocess(["git", "init"], cwd=str(clone_dir)) != 0:
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False, "git init failed."
            self._run_subprocess(["git", "config", "user.email", "devmate@local"], cwd=str(clone_dir))
            self._run_subprocess(["git", "config", "user.name",  "DEVMATE"],        cwd=str(clone_dir))
            self._run_subprocess(["git", "add", "."],  cwd=str(clone_dir))
            self._run_subprocess(["git", "commit", "-m", "Initial commit via DEVMATE"], cwd=str(clone_dir))
            self._run_subprocess(["git", "remote", "add", "origin", clone_url], cwd=str(clone_dir))
            self._run_subprocess(["git", "push", "-u", "origin", "HEAD:main"], cwd=str(clone_dir))

        try:
            # 3. Copy selected files/folders into the clone (overwrite if exists)
            copied = []
            for src in file_paths:
                src_path = Path(src)
                if not src_path.exists():
                    self._emit(f"  Skipping (not found): {src}")
                    continue
                dest = clone_dir / src_path.name
                if src_path.is_file():
                    _shutil.copy2(str(src_path), str(dest))
                elif src_path.is_dir():
                    if dest.exists():
                        _shutil.rmtree(dest)
                    _shutil.copytree(str(src_path), str(dest))
                self._emit(f"  Copied: {src_path.name} -> {dest.name}")
                copied.append(src_path.name)

            if not copied:
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False, "No valid files were copied."

            # 4. Configure git identity inside clone (may not inherit global)
            self._run_subprocess(["git", "config", "user.email", "devmate@local"], cwd=str(clone_dir))
            self._run_subprocess(["git", "config", "user.name",  "DEVMATE"],        cwd=str(clone_dir))

            # Stage only the copied files explicitly
            for fname in copied:
                self._run_subprocess(["git", "add", fname], cwd=str(clone_dir))

            # Check if there's actually anything staged
            staged = _sub.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(clone_dir), capture_output=True, text=True, encoding="utf-8"
            )
            if not staged.stdout.strip():
                # Files identical to repo — nothing to push
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return True, (
                    f"No changes detected in the {len(copied)} file(s) — "
                    "repo is already up to date."
                )

            commit_rc = self._run_subprocess(
                ["git", "commit", "-m", commit_message], cwd=str(clone_dir)
            )
            if commit_rc != 0:
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False, "git commit failed."

            # 5. Push
            self._emit(f"  Pushing to '{repo_full}' ...")
            push_rc = self._run_subprocess(
                ["git", "push"], cwd=str(clone_dir)
            )
            if push_rc == 0:
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return True, (
                    f"Successfully pushed {len(copied)} file(s) to '{repo_full}'."
                )

            # Push might fail if tracking not set yet
            push_rc2 = self._run_subprocess(
                ["git", "push", "-u", "origin", "HEAD:main"], cwd=str(clone_dir)
            )
            _shutil.rmtree(tmp_dir, ignore_errors=True)
            if push_rc2 == 0:
                return True, (
                    f"Successfully pushed {len(copied)} file(s) to '{repo_full}'."
                )
            return False, (
                f"Push failed for '{repo_full}'. "
                "Check your gh auth and repo name."
            )

        except Exception as exc:
            _shutil.rmtree(tmp_dir, ignore_errors=True)
            return False, f"Unexpected error: {exc}"



    def download_github_repo(self, name: str, dest_dir: str):
        """Download a GitHub repo via gh repo clone. Returns (bool, str, dest_path)."""
        import subprocess as _sub
        from pathlib import Path
        repo_name = name
        try:
            if "/" not in repo_name:
                up = _sub.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, encoding="utf-8")
                gh_user = up.stdout.strip()
                if gh_user:
                    repo_name = f"{gh_user}/{name}"

            dest_path = Path(dest_dir) / name
            rc = self._run_subprocess(
                ["gh", "repo", "clone", repo_name, str(dest_path)], cwd="."
            )
            if rc == 0:
                return True, f"GitHub repository '{name}' downloaded successfully.", str(dest_path)
            return False, f"Failed to download '{name}'. Check name and permissions.", ""
        except Exception as exc:
            return False, f"Error running gh: {exc}", ""

    def download_file_from_repo(self, repo_name: str, file_path: str, dest_dir: str):
        """Download a file from a GitHub repo using gh api. Returns (bool, str, dest_path)."""
        import subprocess as _sub
        from pathlib import Path
        try:
            up = _sub.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, encoding="utf-8")
            gh_user = up.stdout.strip()
            
            repo_full = repo_name
            if "/" not in repo_full and gh_user:
                repo_full = f"{gh_user}/{repo_name}"
            
            dest_file = Path(dest_dir) / Path(file_path).name
            with open(str(dest_file), "wb") as f:
                sp = _sub.run(
                    ["gh", "api", "-H", "Accept: application/vnd.github.v3.raw", f"repos/{repo_full}/contents/{file_path}"],
                    stdout=f, stderr=_sub.PIPE
                )
            
            if sp.returncode == 0:
                return True, f"File '{file_path}' downloaded from '{repo_full}'.", str(dest_file)
            else:
                dest_file.unlink(missing_ok=True)
                err = sp.stderr.decode('utf-8').strip() if sp.stderr else "unknown error"
                return False, f"Failed to download '{file_path}' from '{repo_full}'. Check filename. Error: {err}", ""
        except Exception as e:
            return False, f"Error downloading: {e}", ""
            
    def delete_github_repo(self, name: str):
        """Delete a GitHub repo via gh CLI with smart error detection. Returns (bool, str)."""
        import subprocess as _sub
        try:
            resolved = __import__("shutil").which("gh") or "gh"
            cmd = [resolved, "repo", "delete", name, "--yes"]
            if __import__("platform").system() == "Windows" and resolved.lower().endswith((".cmd", ".bat")):
                cmd = ["cmd", "/c"] + cmd
            proc = _sub.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            self._emit(output.strip())
            if proc.returncode == 0:
                return True, f"GitHub repository '{name}' deleted successfully."
            # Detect known fixable errors
            if "delete_repo" in output or "delete repo" in output.lower():
                return False, (
                    f"Cannot delete '{name}': missing delete_repo permission.\n\n"
                    "Fix: run this command in your terminal:\n"
                    "  gh auth refresh -h github.com -s delete_repo\n"
                    "Then try deleting again."
                )
            if "403" in output or "admin rights" in output.lower() or "must have admin" in output.lower():
                return False, (
                    f"Cannot delete '{name}': you need Admin rights on this repo.\n\n"
                    "If you are the owner, run:\n"
                    "  gh auth refresh -h github.com -s delete_repo\n"
                    "Then try again."
                )
            if "404" in output or "not found" in output.lower():
                return False, f"Repo '{name}' not found on GitHub. Check the name."
            return False, f"Failed to delete '{name}': {output.strip() or 'unknown error'}"
        except Exception as exc:
            return False, f"Error running gh: {exc}"

    def delete_file_from_repo(self, repo_name, file_path,
                               commit_message="Delete file via DEVMATE"):
        """Delete a file from a GitHub repo using gh api. Returns (bool, str)."""
        import subprocess as _sub
        try:
            up = _sub.run(["gh", "api", "user", "--jq", ".login"],
                          capture_output=True, text=True, encoding="utf-8", timeout=10)
            gh_user = up.stdout.strip()
        except Exception as e:
            return False, f"Could not resolve GitHub username: {e}"
        if not gh_user:
            return False, "GitHub username not found. Run: gh auth login"
        repo_full = f"{gh_user}/{repo_name}"
        self._emit(f"  Fetching SHA for '{file_path}' in '{repo_full}' ...")
        try:
            sp = _sub.run(["gh", "api",
                           f"repos/{repo_full}/contents/{file_path}",
                           "--jq", ".sha"],
                          capture_output=True, text=True, encoding="utf-8", timeout=15)
            sha = sp.stdout.strip()
        except Exception as e:
            return False, f"Failed to fetch file SHA: {e}"
        if not sha:
            return False, (f"File '{file_path}' not found in '{repo_full}'."
                           " Check the filename (case-sensitive).")
        self._emit(f"  Deleting '{file_path}' (sha={sha[:8]}...) ...")
        rc = self._run_subprocess(
            ["gh", "api", f"repos/{repo_full}/contents/{file_path}",
             "--method", "DELETE",
             "-f", f"message={commit_message}",
             "-f", f"sha={sha}"],
            cwd=".", stream=False,
        )
        if rc == 0:
            return True, f"File '{file_path}' deleted from '{repo_full}'."
        return False, (f"Failed to delete '{file_path}' from '{repo_full}'."
                       " Check the exact filename as it appears in the repo.")

    # ──────────────────── Safe Command Execution ─────────────────────────────

    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        """
        Validate a command string against the whitelist / blacklist.

        Returns:
            (safe: bool, reason: str)
        """
        cmd_lower = command.lower().strip()

        # Check blacklist (substring match)
        for blocked in config.COMMAND_BLACKLIST:
            if blocked.lower() in cmd_lower:
                return False, f"Command blocked: contains '{blocked}'"

        # Check whitelist prefix
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return False, f"Bad command syntax: {e}"

        if not parts:
            return False, "Empty command"

        executable = parts[0].lower()
        # Strip path separators so "C:\Python\python" → "python"
        executable = Path(executable).name.replace(".exe", "")

        if not any(executable.startswith(p) for p in config.COMMAND_WHITELIST_PREFIXES):
            return False, (
                f"'{parts[0]}' is not in the command whitelist. "
                f"Allowed: {', '.join(sorted(config.COMMAND_WHITELIST_PREFIXES))}"
            )

        return True, "OK"

    def run_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        stream: bool = True,
    ) -> Tuple[bool, str]:
        """
        Execute a whitelisted command safely.

        Args:
            command : shell command string (tokenised with shlex)
            cwd     : working directory (defaults to home)
            stream  : if True, streams output line-by-line via callback

        Returns:
            (success: bool, combined_output: str)
        """
        safe, reason = self.is_command_safe(command)
        if not safe:
            self._emit(f"🚫 {reason}")
            return False, reason

        try:
            parts = shlex.split(command)
        except ValueError as e:
            return False, f"Command parse error: {e}"

        work_dir = cwd or str(Path.home())
        rc = self._run_subprocess(parts, cwd=work_dir, stream=stream)
        success = rc == 0
        return success, "Command completed." if success else f"Command exited with code {rc}"

    def run_command_async(
        self,
        command: str,
        cwd: Optional[str] = None,
        done_callback: Optional[Callable[[bool, str], None]] = None,
    ) -> threading.Thread:
        """Non-blocking run_command. Calls done_callback(success, output)."""
        def _worker():
            ok, msg = self.run_command(command, cwd=cwd, stream=True)
            if done_callback:
                done_callback(ok, msg)

        t = threading.Thread(target=_worker, daemon=True, name="CMD-Worker")
        t.start()
        return t

    # ──────────────────── Internal subprocess runner ───────────────────────

    def _run_subprocess(
        self,
        args: List[str],
        cwd: str = ".",
        stream: bool = True,
    ) -> int:
        """
        Run a subprocess and stream output to _emit().
        Handles Windows .cmd/.bat files by prepending 'cmd /c'.
        NEVER uses shell=True with user input.
        Returns the exit code.
        """
        with self._cmd_lock:
            try:
                # On Windows, resolve .cmd/.bat scripts (e.g. npx.cmd, npm.cmd)
                # subprocess.Popen(shell=False) cannot execute .cmd files directly
                if platform.system() == "Windows" and args:
                    resolved = shutil.which(args[0])
                    if resolved and resolved.lower().endswith((".cmd", ".bat")):
                        args = ["cmd", "/c"] + args

                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=cwd,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    # Never shell=True – prevents injection
                    shell=False,
                )
                if stream:
                    for line in proc.stdout:
                        self._emit(line.rstrip())
                else:
                    proc.stdout.read()

                proc.wait()
                return proc.returncode
            except FileNotFoundError:
                self._emit(f"❌ Command not found: {args[0]}")
                return 127
            except Exception as e:
                self._emit(f"❌ Subprocess error: {e}")
                return 1
