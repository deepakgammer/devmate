"""
DEVMATE – Task Manager Module
Simple JSON-backed task CRUD, fully thread-safe.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import config


class TaskManager:
    """Simple JSON-backed task CRUD, fully thread-safe."""

    def __init__(self, path: Path = config.TASKS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._tasks: List[Dict] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._tasks = data.get("tasks", [])
                self._next_id = data.get("next_id", len(self._tasks) + 1)
            except Exception:
                self._tasks = []
                self._next_id = 1

    def _save(self) -> None:
        self._path.write_text(
            json.dumps({"tasks": self._tasks, "next_id": self._next_id}, indent=2),
            encoding="utf-8",
        )

    def add_task(self, text: str, priority: str = "medium") -> Dict:
        with self._lock:
            task = {
                "id": self._next_id,
                "text": text,
                "priority": priority if priority in ("low", "medium", "high") else "medium",
                "done": False,
                "created_at": datetime.now().isoformat(),
            }
            self._tasks.append(task)
            self._next_id += 1
            self._save()
        return task

    def list_tasks(self, only_pending: bool = False) -> List[Dict]:
        with self._lock:
            tasks = list(self._tasks)
        if only_pending:
            tasks = [t for t in tasks if not t["done"]]
        return tasks

    def complete_task(self, task_id) -> Optional[Dict]:
        with self._lock:
            for t in self._tasks:
                if str(t["id"]) == str(task_id):
                    t["done"] = True
                    self._save()
                    return t
        return None

    def remove_task(self, task_id) -> bool:
        with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if str(t["id"]) != str(task_id)]
            changed = len(self._tasks) < before
            if changed:
                self._save()
        return changed

    def format_list(self) -> str:
        tasks = self.list_tasks()
        if not tasks:
            return "📭 No tasks yet. Say 'Add task: …' to create one."
        icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines = ["📋 Your Tasks:\n"]
        for t in tasks:
            done = "✅" if t["done"] else "○"
            pri = icons.get(t["priority"], "○")
            lines.append(f"  [{t['id']}] {done} {pri} {t['text']} "
                         f"({'done' if t['done'] else t['priority']})")
        return "\n".join(lines)
