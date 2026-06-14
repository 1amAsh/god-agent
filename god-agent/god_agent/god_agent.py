"""
god_agent/god_agent.py — JARVIS orchestrator.

Token optimizations:
  - History summarized after 6 turns
  - Routing capped at 1200 tokens
  - Formatter capped at 1200 tokens
  - Direct response capped at 512 tokens
  - Proactive evaluator capped at 64 tokens
  - Agent context trimmed to 1500 chars before injection
  - Workspace snapshot injected so agents can reference prior work

_auto_persist uses task-slug keys (not output content) so workspace keys
are descriptive and findable. Agents also save intentionally via SAVE_ARTIFACT.
"""
from __future__ import annotations

import os
import re
import sys
import time
import uuid
from typing import Optional

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

from god_agent.prompts import ROUTING_PROMPT, FORMATTER_PROMPT, PROACTIVE_CONTEXT_PROMPT
from god_agent.proactivity import ProactivityDecider, WatchLoop, WatchConfig
from schemas.contract import TaskRequest, AgentResponse
from memory.memory import Memory, Workspace
from utils.llm import call_llm
from utils.json_parser import extract_json
from utils.logger import logger

MAX_CLARIFICATIONS      = int(os.environ.get("MAX_CLARIFICATIONS", "2"))
MAX_AGENT_RETRIES       = int(os.environ.get("MAX_AGENT_RETRIES", "1"))
HISTORY_SUMMARIZE_AFTER = 6


def _load_agent_cards() -> str:
    import json
    from pathlib import Path
    cards_dir = Path(__file__).parent.parent / "agent_cards"
    cards = []
    for f in sorted(cards_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            aid  = d.get("agent_id", f.stem)
            desc = d.get("description", "")[:200]
            caps = ", ".join(d.get("capabilities", [])[:5])
            cards.append(f"[{aid}] {desc}\nCapabilities: {caps}")
        except Exception:
            pass
    return "\n\n".join(cards)


def _get_agent(agent_id: str):
    agent_id = agent_id.lower().strip()
    if agent_id == "coding":
        from coding_agent.agent import CodingAgent
        return CodingAgent(workspace=os.environ.get("CODING_WORKSPACE", "coding_agent/workspace"))
    if agent_id == "research":
        from research_agent.agent import ResearchAgent
        return ResearchAgent()
    if agent_id == "app":
        from app_agent.agent import AppAgent
        return AppAgent()
    raise ValueError(f"Unknown agent: {agent_id!r}")


def _task_slug(agent: str, task: str) -> str:
    """Generate a descriptive workspace key from agent name + task description."""
    # Use first 50 chars of task (not output) — so the key is human-readable
    task_part = re.sub(r"[^a-z0-9]+", "_", task.lower().strip())[:50].strip("_")
    return f"{agent}_{task_part}"[:80]


class GodAgent:
    def __init__(self):
        self.session_id   = str(uuid.uuid4())[:8]
        self.memory       = Memory()
        self.workspace    = Workspace()
        self._clarification_count = 0
        self._agent_cards = _load_agent_cards()
        self._decider     = ProactivityDecider()
        self._watch_loop: Optional[WatchLoop] = None
        self._history_summary = ""
        self._turn_count  = 0
        logger.info(f"[god-agent] Session: {self.session_id}")

    # ── Main entry ────────────────────────────────────────────────────

    def process(self, user_input: str) -> str:
        if any(p in user_input.lower() for p in ("stop watching", "stop monitor", "cancel watch")):
            if self._watch_loop and self._watch_loop.is_running():
                self._watch_loop.cancel()
                return "Watch loop cancelled."

        self.memory.save(self.session_id, "user", user_input)
        self._turn_count += 1

        # Proactivity decision (skip on first turn)
        mode, watch_cfg = "reactive", None
        if self._turn_count > 1:
            mode, watch_cfg = self._decider.decide(user_input)

        # Build routing context
        context_text = self._get_context()
        ws_snapshot  = self.workspace.snapshot()

        routing_system = ROUTING_PROMPT.format(
            agent_cards=self._agent_cards,
            max_clarifications=MAX_CLARIFICATIONS,
        )
        routing_user = (
            f"WORKSPACE (already saved artifacts — use these before rebuilding anything):\n"
            f"{ws_snapshot}\n\n"
            f"HISTORY:\n{context_text}\n\n"
            f"REQUEST: {user_input}"
        )

        raw = call_llm(routing_system, [{"role": "user", "content": routing_user}], max_tokens=1200)
        decision = extract_json(raw)

        if decision is None:
            resp = self._direct_response(user_input, context_text)
            self._save_and_maybe_summarize("assistant", resp)
            return resp

        # Clarification
        if decision.get("needs_clarification") and self._clarification_count < MAX_CLARIFICATIONS:
            q = decision.get("clarification_question", "Could you clarify?")
            self._clarification_count += 1
            self.memory.save(self.session_id, "assistant", q)
            return f"[JARVIS] {q}"
        self._clarification_count = 0

        task_type = decision.get("task_type", "DIRECT")

        if task_type == "DIRECT" or decision.get("direct_response"):
            resp = decision.get("direct_response") or self._direct_response(user_input, context_text)
            self._save_and_maybe_summarize("assistant", resp)
            if mode == "proactive" and watch_cfg:
                self._start_watch(watch_cfg)
            return resp

        tasks_config = decision.get("tasks", [])
        if not tasks_config:
            resp = self._direct_response(user_input, context_text)
            self._save_and_maybe_summarize("assistant", resp)
            return resp

        if task_type == "CHAIN":
            results = self._run_chain(tasks_config)
        else:
            results = self._run_parallel(tasks_config)

        # Auto-persist agent outputs to shared workspace (safety net)
        # Keys are based on TASK description, not output content, so they're meaningful
        self._auto_persist(results, tasks_config)

        formatted = self._format_results(user_input, results)
        self._save_and_maybe_summarize("assistant", formatted)

        if mode == "proactive" and watch_cfg:
            self._start_watch(watch_cfg)

        return formatted

    # ── Workspace auto-persistence ────────────────────────────────────

    def _auto_persist(self, responses: list[AgentResponse], tasks_config: list[dict]) -> None:
        """
        Safety-net persistence: save substantial agent outputs to workspace.
        Key is derived from the TASK description (not output), making it human-readable
        and findable by the routing LLM in future turns.

        This is a backstop — agents are also taught to SAVE_ARTIFACT themselves
        via their system prompts when they judge their output is worth keeping.
        """
        for i, r in enumerate(responses):
            if r.succeeded and len(r.result) > 300:
                # Use the task description for a meaningful key
                task_desc = ""
                if i < len(tasks_config):
                    task_desc = tasks_config[i].get("task", "")
                if not task_desc:
                    task_desc = r.result[:40]
                slug = _task_slug(r.agent, task_desc)
                # Only auto-save if this key doesn't already exist (agent-saved takes priority)
                if not self.workspace.read(slug):
                    self.workspace.write(slug, r.result, r.agent, self.session_id)
                    logger.info(f"[god-agent] Auto-persisted: {slug!r}")

    # ── Proactive watch ───────────────────────────────────────────────

    def _start_watch(self, cfg: WatchConfig) -> None:
        if self._watch_loop and self._watch_loop.is_running():
            self._watch_loop.cancel()

        def on_trigger(task: str) -> str:
            full_task = f"{PROACTIVE_CONTEXT_PROMPT}\n\n{task}"
            return self.process(full_task)

        self._watch_loop = WatchLoop(cfg, on_trigger)
        self._watch_loop.start()

    # ── History management ────────────────────────────────────────────

    def _get_context(self) -> str:
        if self._history_summary:
            recent = self.memory.context_text(self.session_id, limit=3)
            return f"[Earlier summary]: {self._history_summary}\n\n[Recent]:\n{recent}"
        return self.memory.context_text(self.session_id, limit=6)

    def _save_and_maybe_summarize(self, role: str, content: str) -> None:
        self.memory.save(self.session_id, role, content)
        if self._turn_count % HISTORY_SUMMARIZE_AFTER == 0:
            self._compress_history()

    def _compress_history(self) -> None:
        full = self.memory.context_text(self.session_id, limit=12)
        if not full or full == "(no prior conversation)":
            return
        summary_raw = call_llm(
            "Summarize this conversation in 3 sentences max. Be factual and dense.",
            [{"role": "user", "content": full}],
            max_tokens=120,
        )
        self._history_summary = summary_raw.strip()

    # ── Execution ─────────────────────────────────────────────────────

    def _run_chain(self, tasks_config: list[dict]) -> list[AgentResponse]:
        results, ctx = [], ""
        for i, cfg in enumerate(tasks_config):
            req = TaskRequest(
                task=cfg.get("task", ""),
                context=ctx[:1500],
                metadata={**cfg.get("metadata", {}), "session_id": self.session_id},
            )
            logger.info(f"[god-agent] CHAIN {i+1}/{len(tasks_config)}: {cfg.get('agent')}")
            resp = self._run_with_retry(cfg.get("agent", ""), req)
            results.append(resp)
            if resp.succeeded:
                ctx = (ctx + f"\n[{cfg.get('agent')} result]:\n{resp.result[:1500]}").strip()
        return results

    def _run_parallel(self, tasks_config: list[dict]) -> list[AgentResponse]:
        results = []
        for cfg in tasks_config:
            req = TaskRequest(task=cfg.get("task", ""), metadata={**cfg.get("metadata", {}), "session_id": self.session_id})
            logger.info(f"[god-agent] PARALLEL: {cfg.get('agent')}")
            results.append(self._run_with_retry(cfg.get("agent", ""), req))
        return results

    def _run_with_retry(self, agent_id: str, request: TaskRequest) -> AgentResponse:
        for attempt in range(1, MAX_AGENT_RETRIES + 2):
            try:
                agent = _get_agent(agent_id)
                resp  = agent.run(request)
                if resp.succeeded or attempt > MAX_AGENT_RETRIES:
                    return resp
                logger.warning(f"[god-agent] {agent_id} failed attempt {attempt}, retrying")
                request = TaskRequest(
                    task=request.task,
                    context=f"RETRY — previous attempt failed: {resp.error[:300]}\n{request.context}",
                    metadata=request.metadata,
                )
                time.sleep(2)
            except ValueError as e:
                return AgentResponse(status="fail", result="", agent=agent_id, error=str(e))
            except Exception as e:
                if attempt > MAX_AGENT_RETRIES:
                    return AgentResponse(status="fail", result="", agent=agent_id, error=str(e))
                time.sleep(2)
        return AgentResponse(status="fail", result="", agent=agent_id, error="Max retries exhausted.")

    # ── Formatting ────────────────────────────────────────────────────

    def _format_results(self, original_request: str, responses: list[AgentResponse]) -> str:
        summaries = []
        for r in responses:
            if r.succeeded:
                summaries.append(f"[{r.agent}] SUCCESS:\n{r.result[:2000]}")
            else:
                summaries.append(f"[{r.agent}] FAILED:\n{r.error[:300]}")

        return call_llm(
            FORMATTER_PROMPT,
            [{"role": "user", "content": (
                f"REQUEST: {original_request}\n\n"
                f"RESULTS:\n" + "\n\n".join(summaries)
            )}],
            max_tokens=1200,
        )

    def _direct_response(self, user_input: str, context_text: str) -> str:
        system = (
            "You are JARVIS (Iron Man's AI). Knowledgeable, efficient, slightly formal. "
            "Refer to yourself as JARVIS not I."
        )
        msg = f"HISTORY:\n{context_text}\n\nUSER: {user_input}" if context_text != "(none)" else user_input
        return call_llm(system, [{"role": "user", "content": msg}], max_tokens=512)
