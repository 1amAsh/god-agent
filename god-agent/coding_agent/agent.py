"""
coding_agent/agent.py — Autonomous coding + file management agent.

Improvements:
  - Full system-wide file access (no workspace sandbox restriction).
  - Accepts TaskRequest / returns AgentResponse (God Agent I/O contract).
  - Injects prior-agent context into both plan and execution prompts.
  - SAVE_ARTIFACT, RECALL_ARTIFACT, LIST_ARTIFACTS — agent decides when to persist.
  - Retry-safe JSON parse with clearer error recovery.
  - MOVE_FILE and COPY_FILE support.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

from coding_agent.tools import ToolKit
from coding_agent.prompts import SYSTEM_PROMPT, PLAN_PROMPT
from schemas.contract import TaskRequest, AgentResponse
from memory.memory import handle_workspace_action
from utils.llm import call_llm
from utils.json_parser import extract_json
from utils.logger import logger, record_task

MAX_STEPS         = 40
DEFAULT_WORKSPACE = str(Path(__file__).parent / "workspace")

_SESSION_ID = str(uuid.uuid4())[:8]


class CodingAgent:
    """
    Autonomous coding and file management agent.
    Conforms to the God Agent I/O contract: run(TaskRequest) → AgentResponse
    """

    def __init__(self, workspace: Optional[str] = None):
        self.workspace = workspace or os.environ.get("CODING_WORKSPACE") or DEFAULT_WORKSPACE
        self.tools     = ToolKit(self.workspace)
        logger.info(f"[coding-agent] workspace={self.workspace}")

    def run(self, request: TaskRequest) -> AgentResponse:
        task    = request.task
        context = request.context or ""
        session = request.metadata.get("session_id", _SESSION_ID)

        logger.info(f"[coding-agent] Task: {task!r}")
        start = time.time()

        # ── Phase 1: Plan ─────────────────────────────────────────────
        workspace_snapshot = self.tools.list_dir(".")
        plan_prompt = (
            PLAN_PROMPT
            .replace("TASK_PLACEHOLDER", task)
            .replace("CONTEXT_PLACEHOLDER", context[:1500] if context else "(none)")
            .replace("WORKSPACE_PLACEHOLDER", workspace_snapshot)
        )

        plan_raw = call_llm(SYSTEM_PROMPT, [{"role": "user", "content": plan_prompt}])
        plan     = extract_json(plan_raw)

        if plan and plan.get("clarification_needed") and plan.get("clarification_question"):
            print(f"\n[CODING AGENT] Clarification needed:\n  {plan['clarification_question']}\nYour answer: ", end="", flush=True)
            try:
                answer = input("").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer:
                task = f"{task}\n\nClarification: {answer}"

        if plan and plan.get("plan"):
            logger.info("[coding-agent] Plan:")
            for s in plan["plan"]:
                logger.info(f"  • {s}")

        # ── Phase 2: Execution loop ───────────────────────────────────
        context_prefix = f"PRIOR CONTEXT:\n{context[:1500]}\n\n" if context else ""
        plan_text      = "\n".join(plan.get("plan", ["Explore and figure it out"])) if plan else "Explore and figure it out"

        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"{context_prefix}"
                    f"TASK: {task}\n\n"
                    f"WORKSPACE: {self.workspace}\n\n"
                    f"PLAN:\n{plan_text}\n\n"
                    f"Begin. Start with LIST_DIR to see the current state."
                ),
            }
        ]

        final_result   = f"Task incomplete after {MAX_STEPS} steps."
        parse_failures = 0

        for step in range(1, MAX_STEPS + 1):
            print(f"[coding step {step:02d}] Thinking...", end=" ", flush=True)

            try:
                raw = call_llm(SYSTEM_PROMPT, messages)
            except Exception as e:
                final_result = f"LLM error at step {step}: {e}"
                break

            parsed = extract_json(raw)
            if not parsed:
                parse_failures += 1
                print(f"parse-error ({parse_failures}/3)")
                if parse_failures >= 3:
                    final_result = "[Agent error: 3 consecutive JSON parse failures]"
                    break
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": "Your last response was not valid JSON. Respond with ONLY a valid JSON object.",
                })
                continue

            parse_failures = 0
            thought = parsed.get("thought", "")
            action  = parsed.get("action", {})
            done    = parsed.get("done", False)
            atype   = action.get("type", "?").upper()

            print(atype)
            if thought:
                print(f"         → {thought.splitlines()[0][:100]}")

            if atype == "FINISH" or done:
                final_result = action.get("summary", thought)
                print(f"\n[coding-agent] ✓ COMPLETE\n{final_result}")
                break

            # ── Workspace actions handled here (before ToolKit dispatch) ──
            ws_result = handle_workspace_action(action, "coding", session)
            if ws_result is not None:
                result     = ws_result
                result_ctx = result if len(result) < 4000 else result[:4000] + "\n... [truncated]"
                print(f"         ← {result_ctx.splitlines()[0][:80]}")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"RESULT:\n{result_ctx}"})
                continue

            result     = self.tools.execute(action)
            result_ctx = result if len(result) < 4000 else result[:4000] + "\n... [truncated]"
            print(f"         ← {result_ctx.splitlines()[0][:80]}")

            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"RESULT:\n{result_ctx}"})

        duration = time.time() - start
        success  = not final_result.startswith("[") or "DONE" in final_result or "complete" in final_result.lower()

        record_task(
            session_id="coding",
            task=task[:300],
            agent="coding",
            result=final_result[:500],
            success=success,
            duration_s=duration,
        )

        return AgentResponse(
            status="success" if success else "fail",
            result=final_result,
            next_hint="Use this result as context for the next step if chaining.",
            agent="coding",
            error="" if success else final_result,
        )
