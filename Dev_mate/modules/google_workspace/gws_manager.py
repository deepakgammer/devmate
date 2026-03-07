"""
DEVMATE – Google Workspace Manager (Native Python API)
Core execution engine for Google Workspace using the official Python client.
Bypasses the broken 'gws' CLI and handles direct OAuth2 and API requests.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import dateutil.parser

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from email.message import EmailMessage
    import base64
    import io
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger("devmate.gws")

# OAuth 2.0 scopes needed for all features
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents"
]

CONFIG_DIR = Path.home() / ".config" / "gws"
CLIENT_SECRET_FILE = CONFIG_DIR / "client_secret.json"
TOKEN_FILE = CONFIG_DIR / "python_token.json"


# ─────────────────────────────────────────────────────────────────────────────
# Input Validation
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_text(value: str) -> str:
    """Strip dangerous characters from user input."""
    return re.sub(r"[^\w\s@.\-+,:;/\\()'\"]", "", value).strip()

def _validate_file_path(path: str) -> bool:
    """Check that a file path is safe and exists."""
    p = Path(path)
    if not p.exists():
        return False
    dangerous = ["..", "~", "|", ";", "&", "`", "$"]
    return not any(d in str(p) for d in dangerous)


# ─────────────────────────────────────────────────────────────────────────────
# GWSManager
# ─────────────────────────────────────────────────────────────────────────────

class GWSManager:
    """Manages all Google Workspace operations via Native Python API."""

    def __init__(self, output_callback: Optional[Callable[[str], None]] = None) -> None:
        self._output_cb = output_callback or (lambda line: logger.info(line))
        self._creds = None
        self._cached_services = {}

    def set_output_callback(self, cb: Callable[[str], None]) -> None:
        self._output_cb = cb

    def _emit(self, text: str) -> None:
        self._output_cb(text)

    # ──────────────────── Authentication ─────────────────────────────────────

    def check_auth(self) -> bool:
        """
        Check auth and load credentials. If needed, triggers a browser OAuth popup.
        Returns True if authenticated.
        """
        if not HAS_GOOGLE_API:
            self._emit("❌ Required Python packages are missing.")
            return False

        if not CLIENT_SECRET_FILE.exists():
            return False

        try:
            creds = None
            if TOKEN_FILE.exists():
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    self._emit("🔐 Opening browser to authenticate with Google ...")
                    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
                    creds = flow.run_local_server(port=0)
                
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())

            self._creds = creds
            return True
        except Exception as e:
            logger.error("OAuth error: %s", e)
            self._emit(f"❌ OAuth error: {e}")
            return False

    def get_auth_instructions(self) -> str:
        """Return user-friendly authentication instructions."""
        if not HAS_GOOGLE_API:
            return (
                "❌ **Google Libraries Missing**\n\n"
                "Please run: `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
            )
            
        return (
            "🔐 **Google Workspace Setup Required**\n\n"
            "DevMate needs Google Cloud credentials to safely access your Workspace:\n\n"
            "1. Go to Google Cloud Console\n"
            "2. Create an OAuth 2.0 Desktop App Client ID\n"
            "3. Download the JSON and save it here:\n"
            f"   `{CLIENT_SECRET_FILE}`\n\n"
            "After doing that, run any command (e.g. `show my drive files`) to log in!"
        )

    def _get_service(self, name: str, version: str):
        """Get a cached Google API service object."""
        key = f"{name}_{version}"
        if key not in self._cached_services:
            self._cached_services[key] = build(name, version, credentials=self._creds)
        return self._cached_services[key]

    # ── Drive ────────────────────────────────────────────────────────────────

    def drive_list(self) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        try:
            service = self._get_service('drive', 'v3')
            results = service.files().list(
                pageSize=20, fields="nextPageToken, files(id, name, mimeType)",
                orderBy="modifiedTime desc"
            ).execute()
            items = results.get('files', [])
            
            if not items: return True, "📂 No files found in Drive."
            
            lines = ["📂 **Google Drive Files:**\n"]
            for i, item in enumerate(items, 1):
                icon = "📁" if "folder" in item.get('mimeType', '') else "📄"
                lines.append(f"  {i}. {icon} **{item['name']}**  `{item['id'][:12]}…`")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    def drive_upload(self, file_path: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        if not _validate_file_path(file_path): return False, f"❌ Invalid path: {file_path}"
        try:
            service = self._get_service('drive', 'v3')
            file_metadata = {'name': Path(file_path).name}
            media = MediaFileUpload(file_path, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id, name').execute()
            return True, f"📁 **{file.get('name')}** uploaded to Drive\n🔑 File ID: `{file.get('id')}`"
        except Exception as e:
            return False, f"API Error: {e}"

    def drive_download(self, file_name: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        name = _sanitize_text(file_name)
        try:
            service = self._get_service('drive', 'v3')
            results = service.files().list(q=f"name contains '{name}'", pageSize=1, fields="files(id, name)").execute()
            items = results.get('files', [])
            if not items: return False, f"❌ No file named '{name}' found."
            
            file_id = items[0]['id']
            real_name = items[0]['name']
            
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            out_path = Path.cwd() / real_name
            with open(out_path, 'wb') as f:
                f.write(fh.getvalue())
                
            return True, f"📥 File **{real_name}** downloaded to {out_path}."
        except Exception as e:
            return False, f"API Error: {e}"

    def drive_search(self, query: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        q = _sanitize_text(query)
        try:
            service = self._get_service('drive', 'v3')
            results = service.files().list(
                q=f"name contains '{q}'", pageSize=20, fields="files(id, name, mimeType)"
            ).execute()
            items = results.get('files', [])
            
            if not items: return True, f"No files matching '{q}' found."
            lines = [f"📂 **Search Results for '{q}':**\n"]
            for i, item in enumerate(items, 1):
                icon = "📁" if "folder" in item.get('mimeType', '') else "📄"
                lines.append(f"  {i}. {icon} **{item['name']}**  `{item['id'][:12]}…`")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    # ── Sheets ───────────────────────────────────────────────────────────────

    def sheets_create(self, title: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        title = _sanitize_text(title)
        try:
            service = self._get_service('sheets', 'v4')
            spreadsheet = {'properties': {'title': title}}
            spreadsheet = service.spreadsheets().create(body=spreadsheet, fields='spreadsheetId, spreadsheetUrl').execute()
            sid = spreadsheet.get("spreadsheetId")
            url = spreadsheet.get("spreadsheetUrl")
            return True, f"📊 Spreadsheet **{title}** created!\n🔑 ID: `{sid}`\n🔗 URL: {url}"
        except Exception as e:
            return False, f"API Error: {e}"

    def sheets_append(self, spreadsheet_id: str, range_: str, values: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        spreadsheet_id = _sanitize_text(spreadsheet_id)
        range_ = _sanitize_text(range_) or "Sheet1!A:Z"
        try:
            service = self._get_service('sheets', 'v4')
            row_data = [x.strip() for x in values.split(",")]
            body = {'values': [row_data]}
            result = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id, range=range_,
                valueInputOption="USER_ENTERED", body=body
            ).execute()
            return True, f"✅ Rows appended. Updated {result.get('updates', {}).get('updatedCells', 0)} cells."
        except Exception as e:
            return False, f"API Error: {e}"

    def sheets_read(self, spreadsheet_id: str, range_: str = "Sheet1!A:Z") -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        spreadsheet_id = _sanitize_text(spreadsheet_id)
        range_ = _sanitize_text(range_) or "Sheet1!A:Z"
        try:
            service = self._get_service('sheets', 'v4')
            result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_).execute()
            values = result.get('values', [])
            if not values: return True, "📊 Spreadsheet is empty."
            
            lines = ["📊 **Spreadsheet Data:**\n"]
            for i, row in enumerate(values[:25], 1):
                lines.append(f"  {i}. " + " | ".join(str(c) for c in row))
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    # ── Gmail ────────────────────────────────────────────────────────────────

    def gmail_send(self, to: str, subject: str, body: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        to = _sanitize_text(to)
        try:
            service = self._get_service('gmail', 'v1')
            message = EmailMessage()
            message.set_content(body)
            message['To'] = to
            message['Subject'] = subject

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'raw': encoded_message}
            
            send_message = service.users().messages().send(userId="me", body=create_message).execute()
            return True, f"✉️ Email sent to **{to}**\n📌 Subject: {subject}\n🔑 Message Id: {send_message.get('id')}"
        except Exception as e:
            return False, f"API Error: {e}"

    def gmail_list(self) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        try:
            service = self._get_service('gmail', 'v1')
            results = service.users().messages().list(userId='me', maxResults=10).execute()
            messages = results.get('messages', [])
            if not messages: return True, "📧 Inbox is empty."
            
            lines = ["📧 **Latest Inbox Messages:**\n"]
            for i, msg in enumerate(messages, 1):
                msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject']).execute()
                headers = msg_data.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(no subject)')
                snippet = msg_data.get('snippet', '')[:80]
                lines.append(f"  {i}. 💌 **{subject}**\n     {snippet}\n     ID: `{msg['id']}`")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    def gmail_read(self, message_id: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        message_id = _sanitize_text(message_id)
        try:
            service = self._get_service('gmail', 'v1')
            msg_data = service.users().messages().get(userId='me', id=message_id, format='full').execute()
            
            headers = msg_data.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(no subject)')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '(unknown)')
            snippet = msg_data.get('snippet', '')
            
            lines = ["📧 **Email Details:**\n"]
            lines.append(f"  📌 **Subject:** {subject}")
            lines.append(f"  👤 **From:** {sender}\n")
            lines.append(f"  {snippet}")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    # ── Calendar ─────────────────────────────────────────────────────────────

    def calendar_create(self, summary: str, start_time: str, end_time: str = "", description: str = "") -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        summary = _sanitize_text(summary)
        try:
            # Simple parsing for "tomorrow at 6pm" using dateutil (best effort)
            dt_start = dateutil.parser.parse(start_time, fuzzy=True)
            if not end_time:
                dt_end = dt_start + timedelta(hours=1)
            else:
                dt_end = dateutil.parser.parse(end_time, fuzzy=True)

            service = self._get_service('calendar', 'v3')
            event = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': dt_start.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': dt_end.isoformat(), 'timeZone': 'UTC'},
            }
            event = service.events().insert(calendarId='primary', body=event).execute()
            return True, f"📅 Event **{summary}** created!\n🔗 {event.get('htmlLink')}"
        except Exception as e:
            return False, f"API Error: {e}"

    def calendar_list(self) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        try:
            service = self._get_service('calendar', 'v3')
            now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
            events_result = service.events().list(
                calendarId='primary', timeMin=now,
                maxResults=10, singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            if not events: return True, "📅 No upcoming events."
            
            lines = ["📅 **Upcoming Events:**\n"]
            for i, evt in enumerate(events, 1):
                start = evt['start'].get('dateTime', evt['start'].get('date'))
                lines.append(f"  {i}. 🗓️ **{evt.get('summary', 'Untitled')}** at {start}")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    # ── Docs ─────────────────────────────────────────────────────────────────

    def docs_create(self, title: str) -> Tuple[bool, str]:
        if not self.check_auth(): return False, "Not authenticated."
        title = _sanitize_text(title)
        try:
            service = self._get_service('docs', 'v1')
            document = service.documents().create(body={'title': title}).execute()
            return True, f"📝 Document **{title}** created!\n🔑 ID: `{document.get('documentId')}`"
        except Exception as e:
            return False, f"API Error: {e}"

    def docs_list(self) -> Tuple[bool, str]:
        """Lists Docs using Drive API with Q filter."""
        if not self.check_auth(): return False, "Not authenticated."
        try:
            service = self._get_service('drive', 'v3')
            results = service.files().list(
                q="mimeType='application/vnd.google-apps.document'",
                pageSize=15, fields="files(id, name)"
            ).execute()
            items = results.get('files', [])
            
            if not items: return True, "No documents found."
            lines = ["📝 **Google Documents:**\n"]
            for i, item in enumerate(items, 1):
                lines.append(f"  {i}. 📄 **{item['name']}**  `{item['id'][:12]}…`")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"API Error: {e}"

    # ── Publish Report (composite command) ───────────────────────────────────

    def publish_report(self, output_callback: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
        emit = output_callback or self._emit
        results: List[str] = []

        emit("📊 Step 1/3: Creating report spreadsheet …")
        ok, msg = self.sheets_create("DevMate Report")
        if not ok: return False, f"Step 1 failed: {msg}"
        results.append(msg)

        sheet_url = ""
        if "URL:" in msg:
            sheet_url = msg.split("URL:")[-1].strip()
        elif "ID:" in msg:
            sheet_id = msg.split("ID:")[-1].strip().strip("`")
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"

        emit("📁 Step 2/3: Uploading report to Drive …")
        report_path = Path(config.DATA_DIR) / "report.txt"
        if report_path.exists():
            ok2, msg2 = self.drive_upload(str(report_path))
            results.append(msg2 if ok2 else f"⚠️ Upload skipped: {msg2}")
        else:
            results.append("⚠️ No local report.txt found — skipping upload.")

        emit("✉️ Step 3/3: Sending report email …")
        body = f"Here is the latest DevMate report: {sheet_url}" if sheet_url else "DevMate report created."
        ok3, msg3 = self.gmail_send(to="me", subject="DevMate Report", body=body)
        results.append(msg3 if ok3 else f"⚠️ Email skipped: {msg3}")

        return True, f"🚀 **Report Published!**\n\n" + "\n\n".join(results)
