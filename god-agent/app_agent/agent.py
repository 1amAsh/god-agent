"""
app_agent/agent.py — App Agent conforming to the God Agent I/O contract.

Wraps app_agent/core.py (self-contained, no external folder dependency).
Injects terminal-safety rules and prior agent context before delegating.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

from schemas.contract import TaskRequest, AgentResponse
from utils.logger import logger, record_task

_TERMINAL_SAFETY = (
    "TERMINAL SAFETY RULES (ABSOLUTE — NEVER BREAK THESE):\n"
    "- NEVER send Ctrl+C, Ctrl+Z, Ctrl+D, or Ctrl+Break to any window.\n"
    "- NEVER interact with Windows Terminal, PowerShell, CMD, Python terminal, or any console.\n"
    "- The terminal running JARVIS is OFF LIMITS. Do not focus it. Do not send any keys to it.\n"
    "- If only terminal windows are open: report no GUI target available and FINISH immediately.\n"
    "- Code execution belongs to the CODING AGENT. You only operate the GUI.\n\n"
)


class AppAgent:
    """
    Windows GUI automation agent.
    Conforms to God Agent I/O contract: run(TaskRequest) → AgentResponse
    """

    def __init__(self) -> None:
        self._core = None
        self._available = False
        try:
            from app_agent.core import AppAgentCore
            self._core = AppAgentCore()
            self._available = self._core.tools.available
            if self._available:
                logger.info("[app-agent] pywinauto available — GUI automation ready.")
            else:
                logger.warning("[app-agent] pywinauto NOT installed. GUI automation disabled.")
                logger.warning("[app-agent] On Windows, install with: pip install pywinauto")
        except Exception as e:
            logger.warning(f"[app-agent] Could not load core: {e}")

    def run(self, request: TaskRequest) -> AgentResponse:
        task = request.task
        context = request.context or ""
        start = time.time()

        if not self._available or self._core is None:
            msg = (
                "App Agent is not available in this environment. "
                "It requires Windows with pywinauto installed.\n"
                "Install: pip install pywinauto\n"
                "Then restart JARVIS."
            )
            record_task("app", task[:300], "app", msg, False, time.time() - start)
            return AgentResponse(
                status="fail",
                result="",
                agent="app",
                error=msg,
            )

        # Build full task with safety rules and prior context
        full_task = _TERMINAL_SAFETY
        if context:
            full_task += f"CONTEXT FROM PRIOR AGENTS:\n{context[:1200]}\n\nYOUR TASK: {task}"
        else:
            full_task += f"YOUR TASK: {task}"

        logger.info(f"[app-agent] Task: {task!r}")

        try:
            raw_result = self._core.run(full_task)
            duration = time.time() - start

            failed = (
                raw_result.startswith("[Task incomplete")
                or raw_result.startswith("[Agent error")
                or raw_result.startswith("[LLM error")
                or raw_result.startswith("[ABORTED]")
            )

            record_task(
                session_id="app",
                task=task[:300],
                agent="app",
                result=raw_result[:500],
                success=not failed,
                duration_s=duration,
            )

            return AgentResponse(
                status="fail" if failed else "success",
                result=raw_result,
                next_hint="GUI task completed. Desktop state has been modified.",
                agent="app",
                error=raw_result if failed else "",
            )

        except Exception as exc:
            duration = time.time() - start
            error_msg = f"App agent raised an exception: {exc}"
            logger.error(f"[app-agent] {error_msg}")
            record_task("app", task[:300], "app", error_msg, False, duration)
            return AgentResponse(
                status="fail",
                result="",
                agent="app",
                error=error_msg,
            )
