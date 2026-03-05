"""
DEVMATE – LLM Module
Wraps the Ollama API to:
  1. Parse user input into structured intents (JSON)
  2. Generate conversational responses for general_chat
  3. Gracefully handle Ollama unavailability
"""

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Keyword-Based Intent Detection (fast, no LLM needed)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_intent_local(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to match user text against common command patterns using regex.
    Returns an intent dict or None if no pattern matched.
    """
    t = text.strip().lower()

    # ── create_project ────────────────────────────────────────────────────
    m = re.search(
        r"create\s+(?:a\s+)?(\w+)\s+project\s+(?:called|named)\s+(\w+)", t
    )
    if m:
        return {"intent": "create_project", "params": {"language": m.group(1), "name": m.group(2)}}
    m = re.search(r"create\s+(?:a\s+)?project\s+(?:called|named)\s+(\w+)", t)
    if m:
        return {"intent": "create_project", "params": {"name": m.group(1)}}
    m = re.search(r"create\s+(?:a\s+)?(\w+)\s+project", t)
    if m:
        return {"intent": "create_project", "params": {"language": m.group(1)}}
    if re.search(r"create\s+(?:a\s+)?project", t):
        return {"intent": "create_project", "params": {}}

    # ── init_git ──────────────────────────────────────────────────────────
    m = re.search(r"(?:init|initialise|initialize)\s+git(?:\s+in\s+(.+))?", t)
    if m:
        params = {"path": m.group(1).strip()} if m.group(1) else {}
        return {"intent": "init_git", "params": params}
    if re.search(r"git\s+init", t):
        return {"intent": "init_git", "params": {}}

    # ── create_github_repo ────────────────────────────────────────────────
    # "create a github repo called myapp"
    m = re.search(
        r"create\s+(?:a\s+)?(?:new\s+)?github\s+repo(?:sitory)?\s+(?:called|named)\s+([\w\-]+)", t
    )
    if m:
        return {"intent": "create_github_repo", "params": {"name": m.group(1)}}
    # "make/create a github repo" (no name specified yet)
    if re.search(r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?github\s+repo(?:sitory)?", t):
        return {"intent": "create_github_repo", "params": {}}
    # "create repo" shorthand
    if re.search(r"create\s+(?:a\s+)?(?:new\s+)?repo(?:sitory)?", t):
        return {"intent": "create_github_repo", "params": {}}

    # ── push_files_to_repo ───────────────────────────────────────────────
    # "push files to my-repo", "commit files to project-x"
    m = re.search(
        r"(?:push|commit|upload|send)\s+(?:my\s+)?files?\s+to\s+([\w\-]+)", t
    )
    if m:
        return {"intent": "push_files_to_repo", "params": {"repo": m.group(1)}}
    # no repo name given: "push files", "upload my files"
    if re.search(r"(?:push|commit|upload|send)\s+(?:my\s+)?files?", t):
        return {"intent": "push_files_to_repo", "params": {}}

    # ── push_github ───────────────────────────────────────────────────────
    if re.search(r"push\s+.*?github|git\s+push|push\s+.*?remote|push\s+.*?origin", t):
        params = {}
        m = re.search(r"message\s+[\"'](.+?)[\"']", t)
        if m:
            params["message"] = m.group(1)
        return {"intent": "push_github", "params": params}
    # delete_file_from_repo ── "delete index.html from my-repo"
    m = re.search(r"(?:delete|remove)\s+(.+?)\s+from\s+([\w\-]+)", t)
    if m:
        return {
            "intent": "delete_file_from_repo",
            "params": {"file": m.group(1).strip(), "repo": m.group(2).strip()},
        }

    # delete_github_repo ── "delete repo myapp" / "delete myapp repo" / "delete REPONAME"
    m = re.search(r"(?:delete|remove)\s+(?:github\s+)?repo(?:sitory)?\s+([\w\-]+)", t)
    if m:
        return {"intent": "delete_github_repo", "params": {"name": m.group(1)}}
    m = re.search(r"(?:delete|remove)\s+([\w\-]+)\s+(?:github\s+)?repo(?:sitory)?", t)
    if m:
        return {"intent": "delete_github_repo", "params": {"name": m.group(1)}}
    if re.search(r"(?:delete|remove)\s+(?:the\s+)?(?:github\s+)?repo(?:sitory)?", t):
        return {"intent": "delete_github_repo", "params": {}}




    # ── downloads ───────────────────────────────────────────────────────
    # "download index.html from my-repo"
    m = re.search(r"download\s+([^\s]+)\s+from\s+([\w\-]+)", t)
    if m:
        return {"intent": "download_file_from_repo", "params": {"file": m.group(1).strip(), "repo": m.group(2).strip()}}
    
    # "download repo myapp" / "download myapp repo"
    m = re.search(r"download\s+(?:the\s+)?(?:github\s+)?repo(?:sitory)?\s+([\w\-]+)", t)
    if m:
        return {"intent": "download_github_repo", "params": {"name": m.group(1)}}
    m = re.search(r"download\s+([\w\-]+)\s+(?:github\s+)?repo(?:sitory)?", t)
    if m:
        return {"intent": "download_github_repo", "params": {"name": m.group(1)}}
    
    # ── add_reminder ──────────────────────────────────────────────────────
    # "remind me in 5 minutes to take a break"
    m = re.search(r"remind\s+(?:me\s+)?(.+?)\s+to\s+(.+)", t)
    if m:
        return {"intent": "add_reminder", "params": {"when": m.group(1).strip(), "text": m.group(2).strip()}}
    # "set a reminder for 5pm: review PR"
    m = re.search(r"(?:set\s+)?(?:a\s+)?reminder\s+(?:for\s+)?(.+?)[\s:]+(.+)", t)
    if m:
        return {"intent": "add_reminder", "params": {"when": m.group(1).strip(), "text": m.group(2).strip()}}

    # ── list_tasks ────────────────────────────────────────────────────────
    if re.search(r"(?:list|show|view|display)\s+(?:my\s+)?tasks?", t):
        return {"intent": "list_tasks", "params": {}}

    # ── add_task ──────────────────────────────────────────────────────────
    m = re.search(r"add\s+task[\s:]+(.+)", t)
    if m:
        task_text = m.group(1).strip()
        priority = "medium"
        for p in ("high", "low"):
            if p in t:
                priority = p
                break
        return {"intent": "add_task", "params": {"text": task_text, "priority": priority}}

    # ── remove_task ───────────────────────────────────────────────────────
    m = re.search(r"(?:remove|delete)\s+task\s+(\d+)", t)
    if m:
        return {"intent": "remove_task", "params": {"id": m.group(1)}}

    # ── complete_task ─────────────────────────────────────────────────────
    m = re.search(r"(?:complete|finish|done|mark)\s+task\s+(\d+)", t)
    if m:
        return {"intent": "complete_task", "params": {"id": m.group(1)}}

    # ── run_command ───────────────────────────────────────────────────────
    m = re.search(r"(?:run|execute)\s+(?:command|cmd)[\s:]+(.+)", t)
    if m:
        return {"intent": "run_command", "params": {"command": m.group(1).strip()}}

    # ── time_date ─────────────────────────────────────────────────────────
    if re.search(r"what\s+(?:is\s+)?(?:the\s+)?(?:current\s+)?(?:time|date|day)", t):
        return {"intent": "time_date", "params": {}}
    if re.search(r"(?:tell|show|give)\s+(?:me\s+)?(?:the\s+)?(?:current\s+)?(?:time|date|day)", t):
        return {"intent": "time_date", "params": {}}
    if re.search(r"(?:what|which)\s+day\s+(?:is\s+)?(?:it\s+)?(?:today)?", t):
        return {"intent": "time_date", "params": {}}
    if re.search(r"(?:today'?s?)\s+date", t):
        return {"intent": "time_date", "params": {}}

    # ── change_mode ────────────────────────────────────────────────────────
    m = re.search(r"(?:change|switch|set)\s+(?:the\s+)?mode\s+(?:to\s+)?(dev|mate)", t)
    if m:
        return {"intent": "change_mode", "params": {"mode": m.group(1).upper()}}

    # No pattern matched → return None so LLM can try
    return None

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt – Intent Parser
# ─────────────────────────────────────────────────────────────────────────────
_INTENT_SYSTEM_PROMPT = """You are DEVMATE's intent parser.
Your ONLY job is to convert the user message into a JSON object.
The JSON must have exactly two keys: "intent" and "params".

Valid intents and their expected params:

| intent               | params keys (all optional)                               |
|----------------------|----------------------------------------------------------|
| create_project       | name (str), language (str: python/node/react/angular)   |
| init_git             | path (str)                                               |
| push_github          | path (str), remote (str), branch (str), message (str)   |
| create_github_repo   | name (str), private (bool)                               |
| push_files_to_repo   | repo (str)                                               |
| delete_github_repo   | name (str)                                               |
| delete_file_from_repo| repo (str), file (str)                                   |
| add_reminder         | text (str), when (str — natural language time)           |
| list_tasks           | (none)                                                   |
| add_task             | text (str), priority (str: low/medium/high)              |
| remove_task          | id (int or str)                                          |
| complete_task        | id (int or str)                                          |
| run_command          | command (str), cwd (str)                                 |
| change_mode          | mode (str: DEV/MATE)                                     |
| general_chat         | (none)                                                   |

Rules:
- Respond with ONLY the JSON object, no markdown, no extra text.
- If you cannot determine a structured intent, use "general_chat".
- Missing params should be omitted, not set to null.

Examples:
User: "Create a python project called my_app"
{"intent": "create_project", "params": {"name": "my_app", "language": "python"}}

User: "Remind me at 5pm to review the PR"
{"intent": "add_reminder", "params": {"text": "review the PR", "when": "5pm"}}

User: "What is a decorator in Python?"
{"intent": "general_chat", "params": {}}
"""

_DEV_SYSTEM_PROMPT = (
    "You are DEVMATE, a smart developer assistant running on the user's local PC. "
    "Rules: answer in 1-2 short sentences. Be direct, professional, and helpful. "
    "Focus purely on professional tasks, coding, and the work at hand. "
    "Never apologize. Never mention Reddit, Alice, or fictional names. "
    "You are DEVMATE only. Use the conversation history to remember what the user said."
)

_MATE_SYSTEM_PROMPT = (
    "You are DEVMATE, but right now you are in MATE mode! "
    "You are a funny, friendly buddy running on the user's local PC. "
    "Rules: answer in 1-2 short, humorous, and friendly sentences. Use emojis. "
    "Act as their friend first, but still be helpful with their coding tasks. "
    "Never apologize. Never mention Reddit, Alice, or fictional names. "
    "You are DEVMATE only. Use the conversation history to remember what the user said."
)

# ─────────────────────────────────────────────────────────────────────────────
# Post-processing: force short, clean replies regardless of model quality
# ─────────────────────────────────────────────────────────────────────────────

_JUNK_PHRASES = [
    "i'm sorry", "i apologize", "as an ai", "as a language model",
    "i'm not able to", "i cannot", "please feel free",
    "here are some", "here's a list", "in my previous response",
    "on reddit", "my name is alice", "alice", "reddit",
    "i'm a machine learning", "autonomous", "self-aware",
    "cutting-edge", "advanced programming",
]

def _clean_reply(text: str) -> str:
    """
    Post-process LLM output to enforce short, sweet, on-topic responses.
    - Strips common junk/hallucination phrases
    - Truncates to max 2 sentences
    - Removes empty lines and excess whitespace
    """
    if not text or text.startswith("⚠️") or text.startswith("❌"):
        return text

    # Strip lines containing junk phrases
    lines = text.strip().splitlines()
    cleaned_lines = []
    for line in lines:
        lower_line = line.lower()
        if any(junk in lower_line for junk in _JUNK_PHRASES):
            continue
        cleaned_lines.append(line.strip())

    text = " ".join(cleaned_lines).strip()

    # If the cleaning removed everything, return a friendly fallback
    if not text:
        return "Hey! Could you rephrase that? I'd love to help! 😊"

    # (Removed) Truncate to max 2 sentences to allow DevMate to speak the full streamed response
    # sentences = re.split(r'(?<=[.!?])\s+', text)
    # if len(sentences) > 2:
    #     text = " ".join(sentences[:2])

    # Ensure it doesn't end mid-sentence (trim trailing fragments)
    if text and text[-1] not in '.!?':
        # Find the last sentence-ending punctuation
        last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
        if last_end > 10:  # only trim if there's a reasonable sentence before
            text = text[:last_end + 1]

    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# LLMModule
# ─────────────────────────────────────────────────────────────────────────────
class LLMModule:
    """Manages all communication with the local Ollama instance."""

    def __init__(self):
        self._available: Optional[bool] = None  # None = unchecked
        self._lock = threading.Lock()

    # ──────────────────── Health Check ───────────────────────────────────────

    def is_available(self) -> bool:
        """Ping Ollama and cache result; re-check each session."""
        if self._available is not None:
            return self._available
        try:
            import ollama
            ollama.list()  # lightweight list call
            self._available = True
        except Exception as e:
            logger.warning("Ollama not reachable: %s", e)
            self._available = False
        return self._available

    def reset_availability(self) -> None:
        """Force a fresh availability check on next call."""
        self._available = None

    # ──────────────────── Intent Detection ───────────────────────────────────

    def detect_intent(
        self,
        user_text: str,
        context: List[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Parse *user_text* into a structured intent dict.

        Uses fast keyword matching first, falls back to LLM only if needed.
        Returns:
            {"intent": str, "params": dict}
        """
        # ── Fast path: keyword / regex matching (no LLM call) ────────────
        local_result = _detect_intent_local(user_text)
        if local_result is not None:
            logger.info("Intent matched locally: %s", local_result["intent"])
            return local_result

        # ── Slow path: ask Ollama to parse intent as JSON ────────────────
        if not self.is_available():
            return {"intent": "general_chat", "params": {}}

        messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}]
        if context:
            messages.extend(context[-4:])
        messages.append({"role": "user", "content": user_text})

        try:
            import ollama
            response = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                options={
                    "temperature": config.LLM_TEMPERATURE,
                    "num_predict": 256,
                },
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = "\n".join(
                    line for line in raw.splitlines()
                    if not line.startswith("```")
                )
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Intent JSON parse failed (%s) — falling back to general_chat", e)
            return {"intent": "general_chat", "params": {}}
        except Exception as e:
            logger.error("Intent detection error: %s", e)
            self._available = False
            return {"intent": "general_chat", "params": {}}

    def detect_intent_async(
        self,
        user_text: str,
        context: List[Dict[str, str]],
        callback: Callable[[Dict[str, Any]], None],
    ) -> threading.Thread:
        """
        Non-blocking version of detect_intent.
        Calls *callback* with the result dict from a daemon thread.
        """
        def _worker():
            result = self.detect_intent(user_text, context)
            callback(result)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    # ──────────────────── General Chat ───────────────────────────────────────

    def chat(
        self,
        user_text: str,
        context: List[Dict[str, str]] = None,
    ) -> str:
        """
        Generate a conversational reply for general_chat intents.

        Returns the assistant's reply string, or an error message.
        """
        if not self.is_available():
            return (
                "⚠️  Ollama is not running. Please start it with:\n"
                "  ollama serve\n"
                "Then load the model with:\n"
                f"  ollama pull {config.OLLAMA_MODEL}"
            )

        # Inject brevity instruction directly into user message
        # (phi3:mini obeys inline instructions well)
        boosted_text = f"Answer in 1-2 short friendly sentences only: {user_text}"

        # Build dynamic system prompt with current date/time
        now_str = datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")
        
        system_prompt_base = _DEV_SYSTEM_PROMPT if config.CURRENT_MODE == "DEV" else _MATE_SYSTEM_PROMPT
        dynamic_prompt = f"{system_prompt_base} Current date/time: {now_str}."

        messages = [{"role": "system", "content": dynamic_prompt}]
        if context:
            messages.extend(context[-config.LLM_CONTEXT_TURNS:])  # use configured context depth
        messages.append({"role": "user", "content": boosted_text})

        # Limit total context tokens (rough character estimate)
        total_chars = sum(len(m["content"]) for m in messages)
        while total_chars > config.LLM_MAX_TOKENS * 4 and len(messages) > 2:
            messages.pop(1)
            total_chars = sum(len(m["content"]) for m in messages)

        try:
            import ollama
            response = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                options={"temperature": 0.5, "num_predict": 60, "top_k": 20, "top_p": 0.8},
            )
            return _clean_reply(response["message"]["content"])
        except Exception as e:
            logger.error("LLM chat error: %s", e)
            self._available = False
            return f"❌ LLM error: {e}"

    def chat_async(
        self,
        user_text: str,
        context: List[Dict[str, str]],
        callback: Callable[[str], None],
    ) -> threading.Thread:
        """Non-blocking version of chat(). Calls *callback* with the reply string."""
        def _worker():
            reply = self.chat(user_text, context)
            callback(reply)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    # ──────────────────── Streaming Chat ─────────────────────────────────────

    def chat_stream(
        self,
        user_text: str,
        context: List[Dict[str, str]] = None,
        on_token: Callable[[str], None] = None,
        on_done: Callable[[str], None] = None,
    ) -> None:
        """
        Stream a conversational reply token-by-token.

        Calls *on_token(chunk)* for every streamed piece of text so the UI can
        display it immediately.  Calls *on_done(full_reply)* when the stream
        is finished.  Both callbacks are optional.

        If Ollama is unavailable the error message is sent to *on_done* directly.
        """
        if not self.is_available():
            msg = (
                "⚠️  Ollama is not running. Please start it with:\n"
                "  ollama serve\n"
                "Then load the model with:\n"
                f"  ollama pull {config.OLLAMA_MODEL}"
            )
            if on_done:
                on_done(msg)
            return

        # Inject brevity instruction into user message
        boosted_text = f"Answer in 1-2 short friendly sentences only: {user_text}"

        # Build dynamic system prompt with current date/time
        now_str = datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")
        
        system_prompt_base = _DEV_SYSTEM_PROMPT if config.CURRENT_MODE == "DEV" else _MATE_SYSTEM_PROMPT
        dynamic_prompt = f"{system_prompt_base} Current date/time: {now_str}."

        messages = [{"role": "system", "content": dynamic_prompt}]
        if context:
            messages.extend(context[-config.LLM_CONTEXT_TURNS:])  # use configured context depth
        messages.append({"role": "user", "content": boosted_text})

        # Trim context to stay within token budget
        total_chars = sum(len(m["content"]) for m in messages)
        while total_chars > config.LLM_MAX_TOKENS * 4 and len(messages) > 2:
            messages.pop(1)
            total_chars = sum(len(m["content"]) for m in messages)

        try:
            import ollama
            full_reply: List[str] = []
            stream = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                options={
                    "temperature": 0.5,
                    "num_predict": 60,    # short & fast
                    "top_k": 20,
                    "top_p": 0.8,
                },
                stream=True,
            )
            for chunk in stream:
                token = chunk["message"]["content"]
                if token:
                    full_reply.append(token)
                    if on_token:
                        on_token(token)
            # Post-process the full reply for cleanliness
            cleaned = _clean_reply("".join(full_reply))
            if on_done:
                on_done(cleaned)
        except Exception as e:
            logger.error("LLM stream error: %s", e)
            self._available = False
            err = f"❌ LLM error: {e}"
            if on_done:
                on_done(err)

    def chat_stream_async(
        self,
        user_text: str,
        context: List[Dict[str, str]],
        on_token: Callable[[str], None],
        on_done: Callable[[str], None],
    ) -> threading.Thread:
        """Non-blocking wrapper around chat_stream(). Runs in a daemon thread."""
        def _worker():
            self.chat_stream(user_text, context, on_token=on_token, on_done=on_done)

        t = threading.Thread(target=_worker, daemon=True, name="StreamChat")
        t.start()
        return t
