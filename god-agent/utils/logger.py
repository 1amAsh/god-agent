"""
utils/logger.py — Structured logging for the God Agent system.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path


LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def _setup() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("god-agent")
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File
    fh = logging.FileHandler(LOG_DIR / "god_agent.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


logger = _setup()


def record_task(
    session_id: str,
    task: str,
    agent: str,
    result: str,
    success: bool,
    duration_s: float,
) -> None:
    """Append a structured JSONL record to the task log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "session": session_id,
        "agent": agent,
        "task": task[:400],
        "success": success,
        "result_preview": result[:300],
        "duration_s": round(duration_s, 2),
    }
    with open(LOG_DIR / "task_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
