"""
memory/memory.py — Conversation memory + shared agent workspace, backed by SQLite.

Two stores:
  1. messages   — per-session conversation history
  2. workspace  — named artifacts any agent can write/read across sessions

Agents use the workspace through first-class SAVE_ARTIFACT / RECALL_ARTIFACT /
LIST_ARTIFACTS actions in their agentic loops — they DECIDE when to save, the
orchestrator does not hardcode it. The _auto_persist fallback in god_agent.py
is a safety net only, using task-based slugs (not output content).
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMORY_DB", "memory/jarvis.db"))


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            session  TEXT NOT NULL,
            role     TEXT NOT NULL,
            content  TEXT NOT NULL,
            ts       TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS workspace (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            key      TEXT NOT NULL UNIQUE,
            content  TEXT NOT NULL,
            agent    TEXT NOT NULL,
            session  TEXT NOT NULL,
            ts       TEXT NOT NULL
        )
    """)
    con.commit()
    return con


class Memory:
    """Session-scoped conversation memory."""

    def save(self, session: str, role: str, content: str) -> None:
        with _conn() as con:
            con.execute(
                "INSERT INTO messages (session, role, content, ts) VALUES (?, ?, ?, ?)",
                (session, role, content, datetime.utcnow().isoformat()),
            )

    def recent(self, session: str, limit: int = 10) -> list[dict]:
        with _conn() as con:
            rows = con.execute(
                "SELECT role, content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
                (session, limit),
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def context_text(self, session: str, limit: int = 8) -> str:
        msgs = self.recent(session, limit)
        if not msgs:
            return "(no prior conversation)"
        lines = []
        for m in msgs:
            tag = "USER" if m["role"] == "user" else "JARVIS"
            lines.append(f"{tag}: {m['content'][:600]}")
        return "\n".join(lines)

    def clear(self, session: str) -> None:
        with _conn() as con:
            con.execute("DELETE FROM messages WHERE session=?", (session,))


class Workspace:
    """
    Shared artifact store — any agent can write/read named artifacts across sessions.

    Keys are human-readable descriptive names like:
      "railway_api_spec", "train_delay_report", "weather_dashboard_src"

    Agents decide when to use this because their prompts tell them workspace exists
    and give them SAVE_ARTIFACT / RECALL_ARTIFACT / LIST_ARTIFACTS as explicit actions.
    """

    def write(self, key: str, content: str, agent: str, session: str) -> None:
        """Store or overwrite a named artifact."""
        if not isinstance(content, str):
            import json
            content = json.dumps(content, indent=2)
        key = re.sub(r"[^a-z0-9_\-]", "_", key.lower().strip())[:80].strip("_")
        if not key:
            key = "artifact"
        with _conn() as con:
            con.execute("""
                INSERT INTO workspace (key, content, agent, session, ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content=excluded.content,
                    agent=excluded.agent,
                    session=excluded.session,
                    ts=excluded.ts
            """, (key, content, agent, session, datetime.utcnow().isoformat()))

    def read(self, key: str) -> str | None:
        """Read a named artifact. Returns None if not found."""
        key = re.sub(r"[^a-z0-9_\-]", "_", key.lower().strip())[:80].strip("_")
        with _conn() as con:
            row = con.execute(
                "SELECT content FROM workspace WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def search(self, query: str) -> list[dict]:
        """Find artifacts whose key contains the query string."""
        query = query.lower()
        with _conn() as con:
            rows = con.execute(
                "SELECT key, agent, session, ts, length(content) as size "
                "FROM workspace WHERE lower(key) LIKE ? ORDER BY ts DESC",
                (f"%{query}%",),
            ).fetchall()
        return [{"key": r[0], "agent": r[1], "session": r[2], "ts": r[3], "size": r[4]} for r in rows]

    def list_keys(self) -> list[dict]:
        """List all stored artifacts with metadata."""
        with _conn() as con:
            rows = con.execute(
                "SELECT key, agent, session, ts, length(content) as size "
                "FROM workspace ORDER BY ts DESC"
            ).fetchall()
        return [{"key": r[0], "agent": r[1], "session": r[2], "ts": r[3], "size": r[4]} for r in rows]

    def delete(self, key: str) -> None:
        with _conn() as con:
            con.execute("DELETE FROM workspace WHERE key=?", (key,))

    def snapshot(self) -> str:
        """Compact summary of workspace contents — injected into every routing call."""
        items = self.list_keys()
        if not items:
            return "(workspace is empty)"
        lines = [
            f"  [{i['key']}] by {i['agent']} at {i['ts'][:16]} ({i['size']} chars)"
            for i in items
        ]
        return "\n".join(lines)


def handle_workspace_action(action: dict, agent_name: str, session_id: str) -> str | None:
    """
    Handles SAVE_ARTIFACT, RECALL_ARTIFACT, LIST_ARTIFACTS actions from any agent loop.

    Returns a result string if action was a workspace action, None otherwise
    (so the caller knows to continue normal action dispatch).

    Usage in agent _execute():
        ws_result = handle_workspace_action(action, "research", session_id)
        if ws_result is not None:
            return ws_result
        # ... normal action dispatch ...
    """
    atype = action.get("type", "").upper()
    ws = Workspace()

    if atype == "SAVE_ARTIFACT":
        key = action.get("key", "").strip()
        content = action.get("content", "").strip()
        if not key:
            return "[SAVE_ARTIFACT error: 'key' field required]"
        if not content:
            return "[SAVE_ARTIFACT error: 'content' field required]"
        ws.write(key, content, agent_name, session_id)
        return f"[SAVED] Artifact '{key}' saved to workspace ({len(content)} chars). Other agents can RECALL_ARTIFACT with key='{key}'."

    if atype == "RECALL_ARTIFACT":
        key = action.get("key", "").strip()
        if not key:
            return "[RECALL_ARTIFACT error: 'key' field required]"
        content = ws.read(key)
        if content:
            return f"[ARTIFACT: {key}]\n{content}"
        # Try fuzzy search
        matches = ws.search(key)
        if matches:
            keys_str = ", ".join(m["key"] for m in matches[:5])
            return f"[RECALL_ARTIFACT] Key '{key}' not found exactly. Similar keys: {keys_str}"
        return f"[RECALL_ARTIFACT] No artifact found for key='{key}'. Workspace may be empty."

    if atype == "LIST_ARTIFACTS":
        items = ws.list_keys()
        if not items:
            return "[WORKSPACE] No artifacts saved yet."
        lines = [f"  [{i['key']}] by {i['agent']} at {i['ts'][:16]} ({i['size']} chars)" for i in items]
        return "[WORKSPACE ARTIFACTS]\n" + "\n".join(lines)

    return None  # Not a workspace action
