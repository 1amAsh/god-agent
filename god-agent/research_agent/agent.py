"""
research_agent/agent.py — Autonomous research and scraping agent.

Improvements:
  - Accepts TaskRequest / returns AgentResponse (God Agent I/O contract).
  - Injects prior-agent context into research task.
  - Mode auto-detection: research / scrape / api_scout.
  - SAVE_ARTIFACT, RECALL_ARTIFACT, LIST_ARTIFACTS — agent decides when to persist.
  - Retry logic for parse failures.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

from research_agent.search import web_search, fetch_page
from research_agent.prompts import RESEARCH_PROMPT, SCRAPE_PROMPT, API_SCOUT_PROMPT
from schemas.contract import TaskRequest, AgentResponse
from memory.memory import handle_workspace_action
from utils.llm import call_llm
from utils.json_parser import extract_json
from utils.logger import logger, record_task

MAX_STEPS    = 40
RESULT_TRIM  = 12_000
CONTEXT_TRIM = 5_000

_SESSION_ID = str(uuid.uuid4())[:8]  # module-level session for workspace writes

_SCRAPE_HINTS = {
    "scrape", "extract", "get all", "list all", "download data",
    "parse", "crawl", "fetch prices", "get prices", "get table",
}

_API_SCOUT_HINTS = {
    "find api", "find an api", "what api", "which api", "discover api",
    "api for", "how to get data from", "how to access", "integrate with",
    "build integration", "real-time data for", "live data for",
}


def _detect_mode(task: str, metadata: dict) -> str:
    if metadata.get("mode"):
        return metadata["mode"]
    lowered = task.lower()
    if any(h in lowered for h in _API_SCOUT_HINTS):
        return "api_scout"
    if any(h in lowered for h in _SCRAPE_HINTS):
        return "scrape"
    return "research"


def _execute(action: dict, session_id: str) -> str:
    atype = action.get("type", "").upper()

    # ── Workspace actions — agent decides when to save/recall ─────────
    ws_result = handle_workspace_action(action, "research", session_id)
    if ws_result is not None:
        return ws_result

    # ── Web actions ───────────────────────────────────────────────────
    if atype == "SEARCH":
        query = action.get("query", "").strip()
        if not query:
            return "[SEARCH error: empty query]"
        max_r = min(int(action.get("max_results", 10)), 10)
        results = web_search(query, max_r)
        if not results:
            for suffix in [" overview", " wikipedia", " explained"]:
                results = web_search(query + suffix, max_r)
                if results:
                    break
            if not results:
                return f"[SEARCH error: no results for {query!r}]"
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. **{r['title']}**\n"
                f"   URL: {r['url']}\n"
                f"   {r['snippet']}"
            )
        return "\n\n".join(lines)

    if atype == "FETCH_PAGE":
        url = action.get("url", "").strip()
        if not url:
            return "[FETCH_PAGE error: no URL provided]"
        return fetch_page(url, max_chars=RESULT_TRIM)

    if atype == "FINISH":
        return action.get("output", "")

    return f"[ERROR] Unknown action: {atype!r}"


class ResearchAgent:
    """
    Autonomous web research and scraping agent.
    Conforms to the God Agent I/O contract: run(TaskRequest) → AgentResponse
    """

    def run(self, request: TaskRequest) -> AgentResponse:
        task     = request.task
        context  = request.context or ""
        mode     = _detect_mode(task, request.metadata)
        session  = request.metadata.get("session_id", _SESSION_ID)

        logger.info(f"[research-agent] Mode={mode} Task={task!r}")
        start = time.time()

        _PROMPT_MAP = {
            "research":  RESEARCH_PROMPT,
            "scrape":    SCRAPE_PROMPT,
            "api_scout": API_SCOUT_PROMPT,
        }
        system_prompt  = _PROMPT_MAP.get(mode, RESEARCH_PROMPT)
        context_prefix = f"PRIOR CONTEXT (from earlier agents):\n{context[:1500]}\n\n" if context else ""

        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"{context_prefix}"
                    f"TASK: {task}\n\n"
                    f"Begin your {mode}."
                ),
            }
        ]
        final_output = f"[{mode} incomplete — reached {MAX_STEPS} step limit]"
        parse_failures = 0

        for step in range(1, MAX_STEPS + 1):
            print(f"[research step {step:02d}] Thinking...", end=" ", flush=True)

            try:
                raw = call_llm(system_prompt, messages)
            except Exception as exc:
                final_output = f"[LLM error at step {step}: {exc}]"
                break

            parsed = extract_json(raw)
            if not parsed:
                parse_failures += 1
                print(f"parse-error ({parse_failures}/3)")
                if parse_failures >= 3:
                    final_output = "[Agent error: 3 consecutive JSON parse failures]"
                    break
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": "Your response was not valid JSON. Respond with ONLY a single valid JSON object.",
                })
                continue

            parse_failures = 0
            thought = parsed.get("thought", "")
            action  = parsed.get("action", {})
            done    = parsed.get("done", False)
            atype   = action.get("type", "?").upper()

            print(atype)
            if thought:
                print(f"         → {thought.splitlines()[0][:120]}")

            if atype == "FINISH" or done:
                final_output = action.get("output", thought)
                print(f"\n[research-agent] ✓ COMPLETE")
                break

            result     = _execute(action, session)
            result_ctx = result if len(result) <= CONTEXT_TRIM else result[:CONTEXT_TRIM] + "\n[… truncated]"
            print(f"         ← {result_ctx.splitlines()[0][:100]}")

            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"RESULT:\n{result_ctx}"})

        duration = time.time() - start
        success  = not final_output.startswith("[") or "DONE" in final_output

        record_task(
            session_id="research",
            task=task[:300],
            agent="research",
            result=final_output[:500],
            success=success,
            duration_s=duration,
        )

        return AgentResponse(
            status="success" if success else "fail",
            result=final_output,
            next_hint="Research output can be passed as context to the coding agent to build something with this data.",
            agent="research",
            error="" if success else final_output,
        )
