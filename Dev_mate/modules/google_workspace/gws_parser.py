"""
DEVMATE – Google Workspace Intent Parser
Regex-based intent detection for GWS commands.
Returns the same {intent, params} dict shape as _detect_intent_local().
"""

import re
from typing import Any, Dict, Optional


def detect_gws_intent(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to match user text against Google Workspace command patterns.
    Returns an intent dict or None if no pattern matched.
    """
    t = text.strip().lower()

    # ── Google Drive ──────────────────────────────────────────────────────

    # "show my drive files" / "list drive files" / "list my google drive"
    if re.search(r"(?:show|list|display|view)\s+(?:my\s+)?(?:google\s+)?drive\s+files?", t):
        return {"intent": "gws_drive_list", "params": {}}
    if re.search(r"(?:show|list|display|view)\s+(?:my\s+)?(?:google\s+)?drive$", t):
        return {"intent": "gws_drive_list", "params": {}}

    # "upload <file> to drive" / "upload to drive <file>"
    m = re.search(r"upload\s+(.+?)\s+to\s+(?:google\s+)?drive", t)
    if m:
        return {"intent": "gws_drive_upload", "params": {"file_path": m.group(1).strip()}}
    m = re.search(r"upload\s+to\s+(?:google\s+)?drive\s+(.+)", t)
    if m:
        return {"intent": "gws_drive_upload", "params": {"file_path": m.group(1).strip()}}

    # "download drive file <name>" / "download <name> from drive"
    m = re.search(r"download\s+(?:google\s+)?drive\s+file\s+(.+)", t)
    if m:
        return {"intent": "gws_drive_download", "params": {"file_name": m.group(1).strip()}}
    m = re.search(r"download\s+(.+?)\s+from\s+(?:google\s+)?drive", t)
    if m:
        return {"intent": "gws_drive_download", "params": {"file_name": m.group(1).strip()}}

    # "search drive for <query>" / "find <query> in drive" / "search drive files <query>"
    m = re.search(r"search\s+(?:google\s+)?drive\s+(?:for\s+|files?\s+)?(.+)", t)
    if m:
        return {"intent": "gws_drive_search", "params": {"query": m.group(1).strip()}}
    m = re.search(r"find\s+(.+?)\s+(?:in|on)\s+(?:google\s+)?drive", t)
    if m:
        return {"intent": "gws_drive_search", "params": {"query": m.group(1).strip()}}

    # ── Google Sheets ─────────────────────────────────────────────────────

    # "create sheet <name>" / "create spreadsheet <name>" / "new sheet <name>"
    m = re.search(
        r"(?:create|make|new)\s+(?:a\s+)?(?:google\s+)?(?:sheet|spreadsheet)\s+(?:called\s+|named\s+)?(.+)",
        t,
    )
    if m:
        return {"intent": "gws_sheets_create", "params": {"title": m.group(1).strip()}}

    # "add row to sheet <name>" / "append row to spreadsheet <name>"
    m = re.search(
        r"(?:add|append|insert)\s+(?:a\s+)?rows?\s+to\s+(?:google\s+)?(?:sheet|spreadsheet)\s+(.+)",
        t,
    )
    if m:
        return {"intent": "gws_sheets_append", "params": {"title": m.group(1).strip()}}

    # "read sheet <name>" / "show spreadsheet <name>"
    m = re.search(
        r"(?:read|show|view|display|get)\s+(?:google\s+)?(?:sheet|spreadsheet)\s+(.+)",
        t,
    )
    if m:
        return {"intent": "gws_sheets_read", "params": {"title": m.group(1).strip()}}

    # ── Gmail ─────────────────────────────────────────────────────────────

    # "send email to <recipient>" / "send mail to <recipient>"
    m = re.search(r"send\s+(?:an?\s+)?(?:e-?mail|message|mail)\s+to\s+(.+)", t)
    if m:
        return {"intent": "gws_gmail_send", "params": {"to": m.group(1).strip()}}

    # "show my latest emails" / "list inbox" / "show my emails" / "check email"
    if re.search(
        r"(?:show|list|display|view|check)\s+(?:my\s+)?(?:latest\s+|recent\s+|new\s+)?(?:e-?mails?|inbox|messages?|mail)",
        t,
    ):
        return {"intent": "gws_gmail_list", "params": {}}

    # "read email <id>" / "open email <id>"
    m = re.search(r"(?:read|open|view)\s+(?:e-?mail|message)\s+(.+)", t)
    if m:
        return {"intent": "gws_gmail_read", "params": {"message_id": m.group(1).strip()}}

    # ── Google Calendar ───────────────────────────────────────────────────

    # "schedule <event> tomorrow at 6pm" / "create event <name> at <time>"
    m = re.search(
        r"(?:schedule|create\s+(?:a\s+)?(?:calendar\s+)?event|add\s+(?:a\s+)?(?:calendar\s+)?event)\s+(.+?)\s+(?:at|on|for|from)\s+(.+)",
        t,
    )
    if m:
        return {
            "intent": "gws_calendar_create",
            "params": {"summary": m.group(1).strip(), "start_time": m.group(2).strip()},
        }
    # Simpler version: "schedule meeting tomorrow"
    m = re.search(
        r"(?:schedule|create\s+(?:a\s+)?(?:calendar\s+)?event|add\s+(?:a\s+)?(?:calendar\s+)?event)\s+(.+)",
        t,
    )
    if m:
        return {
            "intent": "gws_calendar_create",
            "params": {"summary": m.group(1).strip()},
        }

    # "show my events" / "list calendar events" / "show my calendar"
    if re.search(
        r"(?:show|list|display|view)\s+(?:my\s+)?(?:upcoming\s+)?(?:calendar\s+)?events?", t
    ):
        return {"intent": "gws_calendar_list", "params": {}}
    if re.search(r"(?:show|list|display|view)\s+(?:my\s+)?calendar$", t):
        return {"intent": "gws_calendar_list", "params": {}}

    # ── Google Docs ───────────────────────────────────────────────────────

    # "create document <name>" / "create a doc called <name>" / "new google doc <name>"
    m = re.search(
        r"(?:create|make|new)\s+(?:a\s+)?(?:google\s+)?(?:doc(?:ument)?)\s+(?:called\s+|named\s+)?(.+)",
        t,
    )
    if m:
        return {"intent": "gws_docs_create", "params": {"title": m.group(1).strip()}}

    # "list my documents" / "show my docs" / "list google docs"
    if re.search(
        r"(?:show|list|display|view)\s+(?:my\s+)?(?:google\s+)?(?:doc(?:ument)?s)", t
    ):
        return {"intent": "gws_docs_list", "params": {}}

    # ── Advanced: Publish Report ──────────────────────────────────────────

    if re.search(r"publish\s+(?:a\s+)?report", t):
        return {"intent": "gws_publish_report", "params": {}}

    # No GWS pattern matched
    return None
