"""
DEVMATE – Google Workspace CLI Command Templates
All gws CLI commands are defined here as frozen constants.
NO arbitrary shell execution is allowed — only these predefined commands.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class GWSCommand:
    """Immutable CLI command template."""
    name: str
    description: str
    base_args: tuple  # base CLI arguments (immutable)
    required_params: tuple = ()  # parameter names that MUST be provided
    optional_params: tuple = ()  # parameter names that CAN be provided


# ─────────────────────────────────────────────────────────────────────────────
# Google Drive Commands
# ─────────────────────────────────────────────────────────────────────────────

DRIVE_LIST = GWSCommand(
    name="drive_list",
    description="List files in Google Drive",
    base_args=("gws", "drive", "files", "list", "--format", "json"),
)

DRIVE_UPLOAD = GWSCommand(
    name="drive_upload",
    description="Upload a file to Google Drive",
    base_args=("gws", "drive", "files", "create", "--format", "json"),
    required_params=("file_path",),
)

DRIVE_DOWNLOAD = GWSCommand(
    name="drive_download",
    description="Download a file from Google Drive",
    base_args=("gws", "drive", "files", "export", "--format", "json"),
    required_params=("file_id",),
)

DRIVE_SEARCH = GWSCommand(
    name="drive_search",
    description="Search files in Google Drive",
    base_args=("gws", "drive", "files", "list", "--format", "json"),
    required_params=("query",),
)

# ─────────────────────────────────────────────────────────────────────────────
# Google Sheets Commands
# ─────────────────────────────────────────────────────────────────────────────

SHEETS_CREATE = GWSCommand(
    name="sheets_create",
    description="Create a new Google Spreadsheet",
    base_args=("gws", "sheets", "spreadsheets", "create", "--format", "json"),
    required_params=("title",),
)

SHEETS_APPEND = GWSCommand(
    name="sheets_append",
    description="Append rows to a Google Spreadsheet",
    base_args=("gws", "sheets", "spreadsheets", "values", "append", "--format", "json"),
    required_params=("spreadsheet_id", "range", "values"),
)

SHEETS_READ = GWSCommand(
    name="sheets_read",
    description="Read a range from a Google Spreadsheet",
    base_args=("gws", "sheets", "spreadsheets", "values", "get", "--format", "json"),
    required_params=("spreadsheet_id", "range"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Gmail Commands
# ─────────────────────────────────────────────────────────────────────────────

GMAIL_SEND = GWSCommand(
    name="gmail_send",
    description="Send an email via Gmail",
    base_args=("gws", "gmail", "users", "messages", "send", "--format", "json"),
    required_params=("to", "subject", "body"),
)

GMAIL_LIST = GWSCommand(
    name="gmail_list",
    description="List inbox messages",
    base_args=("gws", "gmail", "users", "messages", "list", "--format", "json"),
)

GMAIL_READ = GWSCommand(
    name="gmail_read",
    description="Read a specific email message",
    base_args=("gws", "gmail", "users", "messages", "get", "--format", "json"),
    required_params=("message_id",),
)

# ─────────────────────────────────────────────────────────────────────────────
# Google Calendar Commands
# ─────────────────────────────────────────────────────────────────────────────

CALENDAR_CREATE = GWSCommand(
    name="calendar_create",
    description="Create a calendar event",
    base_args=("gws", "calendar", "events", "insert", "--format", "json"),
    required_params=("summary", "start_time"),
    optional_params=("end_time", "description"),
)

CALENDAR_LIST = GWSCommand(
    name="calendar_list",
    description="List upcoming calendar events",
    base_args=("gws", "calendar", "events", "list", "--format", "json"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Google Docs Commands
# ─────────────────────────────────────────────────────────────────────────────

DOCS_CREATE = GWSCommand(
    name="docs_create",
    description="Create a new Google Document",
    base_args=("gws", "docs", "documents", "create", "--format", "json"),
    required_params=("title",),
)

DOCS_LIST = GWSCommand(
    name="docs_list",
    description="List Google Documents",
    base_args=(
        "gws", "drive", "files", "list",
        "--query", "mimeType='application/vnd.google-apps.document'",
        "--format", "json",
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Auth Commands (not user-facing, used internally)
# ─────────────────────────────────────────────────────────────────────────────

AUTH_STATUS = GWSCommand(
    name="auth_status",
    description="Check authentication status",
    base_args=("gws", "auth", "status"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Lookup table — maps intent names → command templates
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_REGISTRY = {
    "gws_drive_list":       DRIVE_LIST,
    "gws_drive_upload":     DRIVE_UPLOAD,
    "gws_drive_download":   DRIVE_DOWNLOAD,
    "gws_drive_search":     DRIVE_SEARCH,
    "gws_sheets_create":    SHEETS_CREATE,
    "gws_sheets_append":    SHEETS_APPEND,
    "gws_sheets_read":      SHEETS_READ,
    "gws_gmail_send":       GMAIL_SEND,
    "gws_gmail_list":       GMAIL_LIST,
    "gws_gmail_read":       GMAIL_READ,
    "gws_calendar_create":  CALENDAR_CREATE,
    "gws_calendar_list":    CALENDAR_LIST,
    "gws_docs_create":      DOCS_CREATE,
    "gws_docs_list":        DOCS_LIST,
}
