"""
In-memory session store for the chatbot Generate-from-URL flow.

Each session stores:
  - page_structure       : full SelectorExtractor output (used for test generation)
  - compact              : lightweight summary (used for LLM context)
  - messages             : conversation history [{role, content}]
  - last_test_suite      : most recently generated test suite (for follow-up refinements)
  - last_execution_result: most recent execution result dict
  - execution_session_id : SSE session_id for live execution stream

Sessions live in memory and are cleared on server restart.
"""
import uuid
from typing import Any, Dict, List, Optional

_sessions: Dict[str, Dict[str, Any]] = {}


def create_session(page_structure: Dict[str, Any], compact: Dict[str, Any]) -> str:
    """Create a new session and return the session_id."""
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "page_structure": page_structure,
        "compact": compact,
        "messages": [],
        "last_execution_result": None,
        "execution_session_id": None,
        "credentials": {},
    }
    return session_id


def create_pending_session() -> str:
    """
    Reserve a session_id immediately (before page scraping completes).
    The session has no page_structure yet — call finalize_session() once ready.
    This lets the frontend open an SSE connection before the LLM starts.
    """
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "page_structure": None,
        "compact": None,
        "messages": [],
        "last_execution_result": None,
        "execution_session_id": None,
        "credentials": {},
    }
    return session_id


def finalize_session(session_id: str, page_structure: Dict[str, Any], compact: Dict[str, Any]) -> None:
    """Populate page_structure and compact into a pending session."""
    session = _sessions.get(session_id)
    if session is not None:
        session["page_structure"] = page_structure
        session["compact"] = compact


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the session dict or None if not found."""
    return _sessions.get(session_id)


def append_message(session_id: str, role: str, content: str) -> None:
    """Append a message to the session's conversation history."""
    session = _sessions.get(session_id)
    if session is not None:
        session["messages"].append({"role": role, "content": content})


def set_last_test_suite(session_id: str, test_suite: Dict[str, Any]) -> None:
    """Store the most recently generated test suite in the session."""
    session = _sessions.get(session_id)
    if session is not None:
        session["last_test_suite"] = test_suite


def get_last_test_suite(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the last generated test suite, or None if none yet."""
    session = _sessions.get(session_id)
    if session is not None:
        return session.get("last_test_suite")
    return None


def set_execution_result(session_id: str, result: Dict[str, Any]) -> None:
    """Store execution results in the chat session."""
    session = _sessions.get(session_id)
    if session is not None:
        session["last_execution_result"] = result


def get_execution_result(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the last execution result, or None."""
    session = _sessions.get(session_id)
    if session is not None:
        return session.get("last_execution_result")
    return None


def set_execution_session(session_id: str, exec_session_id: str) -> None:
    """Link an SSE execution session_id to this chat session."""
    session = _sessions.get(session_id)
    if session is not None:
        session["execution_session_id"] = exec_session_id


def get_execution_session(session_id: str) -> Optional[str]:
    """Return the linked execution SSE session_id."""
    session = _sessions.get(session_id)
    if session is not None:
        return session.get("execution_session_id")
    return None


def get_messages(session_id: str, max_messages: int = 10) -> list:
    """Return the last `max_messages` conversation turns, oldest first."""
    session = _sessions.get(session_id)
    if session is None:
        return []
    return session["messages"][-max_messages:]


def delete_session(session_id: str) -> None:
    """Remove a session from memory."""
    _sessions.pop(session_id, None)


def set_pending_approval(session_id: str, results: list) -> None:
    """Store results awaiting user confirmation before adding to Excel."""
    session = _sessions.get(session_id)
    if session is not None:
        session["pending_approval"] = results


def get_pending_approval(session_id: str) -> Optional[list]:
    """Return pending approval results, or None if none queued."""
    session = _sessions.get(session_id)
    if session is not None:
        return session.get("pending_approval")
    return None


def clear_pending_approval(session_id: str) -> None:
    """Remove pending approval results."""
    session = _sessions.get(session_id)
    if session is not None:
        session.pop("pending_approval", None)


def set_credentials(session_id: str, creds: Dict[str, Any]) -> None:
    """Store extracted credentials in the session."""
    session = _sessions.get(session_id)
    if session is not None:
        session["credentials"] = creds


def get_credentials(session_id: str) -> Dict[str, Any]:
    """Return stored credentials, or empty dict."""
    session = _sessions.get(session_id)
    if session is not None:
        return session.get("credentials", {})
    return {}
