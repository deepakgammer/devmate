"""
DEVMATE – Scheduler Module
Accurate reminder scheduling using threading.Timer + dateutil.

Supports human time strings:
  - "in 5 minutes"
  - "in 2 hours"  
  - "at 3 PM"
  - "at 17:30"
  - "tomorrow at 9 AM"
  - ISO datetime strings
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Reminder:
    id: str
    text: str
    fire_at: datetime        # timezone-aware UTC datetime
    timer: threading.Timer
    cancelled: bool = False

    def seconds_remaining(self) -> float:
        delta = self.fire_at - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds())

    def __repr__(self) -> str:
        return f"Reminder(id={self.id!r}, text={self.text!r}, fire_at={self.fire_at})"


# ─────────────────────────────────────────────────────────────────────────────
# Time Parsing
# ─────────────────────────────────────────────────────────────────────────────
def _parse_when(when_str: str) -> Optional[datetime]:
    """
    Convert a human time string to a timezone-aware UTC datetime.

    Returns None if parsing fails.
    """
    now = datetime.now(timezone.utc)
    text = when_str.strip().lower()

    # ── "in X minutes/hours/seconds" ──────────────────────────────────────
    import re
    m = re.match(
        r"in\s+(\d+(?:\.\d+)?)\s*(second|minute|hour|day)s?", text
    )
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        delta = {
            "second": timedelta(seconds=amount),
            "minute": timedelta(minutes=amount),
            "hour":   timedelta(hours=amount),
            "day":    timedelta(days=amount),
        }[unit]
        return now + delta

    # ── dateutil fallback (handles "at 5pm", "tomorrow at 9am", ISO, …) ──
    try:
        from dateutil import parser as duparser
        from dateutil.relativedelta import relativedelta

        # dateutil doesn't know about "tomorrow" phrasing well in all combos
        tomorrow = False
        if "tomorrow" in text:
            text = text.replace("tomorrow", "").strip()
            tomorrow = True

        parsed = duparser.parse(text, default=now.replace(tzinfo=None))
        # Make timezone-aware (local → UTC)
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz).astimezone(timezone.utc)

        if tomorrow:
            parsed += timedelta(days=1)

        # If the parsed time is in the past, assume they mean tomorrow
        if parsed <= now:
            parsed += timedelta(days=1)

        return parsed

    except Exception as e:
        logger.warning("dateutil parse failed for %r: %s", when_str, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SchedulerModule
# ─────────────────────────────────────────────────────────────────────────────
class SchedulerModule:
    """
    Threading-based reminder scheduler.

    All reminders run on daemon threads so they don't block Python from exiting.
    """

    def __init__(self, fire_callback: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            fire_callback: called when a reminder fires.
                           Signature: callback(reminder_id, reminder_text)
        """
        self._reminders: Dict[str, Reminder] = {}
        self._lock = threading.Lock()
        self._fire_cb = fire_callback or self._default_fire

    # ──────────────────── Add / Cancel ───────────────────────────────────────

    def add_reminder(
        self,
        text: str,
        when: str,
    ) -> Tuple[bool, str]:
        """
        Schedule a reminder.

        Args:
            text: reminder message shown when it fires
            when: human-readable time string ("in 5 minutes", "at 3 PM", …)

        Returns:
            (success: bool, message: str)
        """
        fire_at = _parse_when(when)
        if fire_at is None:
            return False, f"Could not parse time: '{when}'. Try 'in 5 minutes' or 'at 3 PM'."

        delay_secs = (fire_at - datetime.now(timezone.utc)).total_seconds()
        if delay_secs < 1:
            return False, "Reminder time is in the past or too soon (< 1 second)."

        rid = str(uuid.uuid4())[:8]

        def _on_fire():
            with self._lock:
                reminder = self._reminders.get(rid)
                if reminder and not reminder.cancelled:
                    reminder.cancelled = True  # mark as fired
            self._fire_cb(rid, text)
            logger.info("Reminder fired: id=%s text=%r", rid, text)

        timer = threading.Timer(delay_secs, _on_fire)
        timer.daemon = True
        timer.start()

        reminder = Reminder(id=rid, text=text, fire_at=fire_at, timer=timer)
        with self._lock:
            self._reminders[rid] = reminder

        # Human-readable fire time
        local_fire = fire_at.astimezone().strftime("%I:%M %p")
        logger.info("Reminder scheduled: id=%s at %s (%d s)", rid, local_fire, int(delay_secs))
        return True, f"⏰ Reminder set for {local_fire} — '{text}' (id: {rid})"

    def cancel_reminder(self, reminder_id: str) -> Tuple[bool, str]:
        """Cancel a pending reminder by its short ID."""
        with self._lock:
            reminder = self._reminders.get(reminder_id)
            if reminder is None:
                return False, f"No reminder found with id '{reminder_id}'."
            if reminder.cancelled:
                return False, f"Reminder '{reminder_id}' already fired or cancelled."
            reminder.timer.cancel()
            reminder.cancelled = True

        return True, f"✅ Reminder '{reminder_id}' cancelled."

    # ──────────────────── Listing ─────────────────────────────────────────────

    def list_reminders(self) -> List[Dict]:
        """Return all pending (not yet fired / cancelled) reminders."""
        now = datetime.now(timezone.utc)
        with self._lock:
            active = [
                {
                    "id": r.id,
                    "text": r.text,
                    "fire_at": r.fire_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                    "seconds_remaining": int(r.seconds_remaining()),
                }
                for r in self._reminders.values()
                if not r.cancelled and r.fire_at > now
            ]
        return sorted(active, key=lambda x: x["seconds_remaining"])

    def format_reminders_text(self) -> str:
        """Format active reminders as a display string."""
        reminders = self.list_reminders()
        if not reminders:
            return "📭 No active reminders."
        lines = ["⏰ Active reminders:"]
        for r in reminders:
            mins = r["seconds_remaining"] // 60
            secs = r["seconds_remaining"] % 60
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            lines.append(f"  [{r['id']}] '{r['text']}' — fires in {time_str} at {r['fire_at']}")
        return "\n".join(lines)

    # ──────────────────── Default Fire Callback ───────────────────────────────

    @staticmethod
    def _default_fire(reminder_id: str, text: str) -> None:
        """Default handler — just log (GUI will override this)."""
        logger.info("🔔 REMINDER [%s]: %s", reminder_id, text)

    # ──────────────────── Shutdown ────────────────────────────────────────────

    def cancel_all(self) -> None:
        """Cancel all pending reminders (called on app exit)."""
        with self._lock:
            for r in self._reminders.values():
                if not r.cancelled:
                    r.timer.cancel()
                    r.cancelled = True
        logger.info("All reminders cancelled.")
