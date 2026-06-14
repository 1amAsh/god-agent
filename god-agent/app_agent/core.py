"""
app_agent/core.py — Self-contained App Agent agentic loop.

Hybrid mode: accessibility tree (pywinauto) + Puter AI vision (pyautogui).
The LLM decides which perception mode to use per step based on what works.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_agent.tools import GUIToolKit
from app_agent.vision_puter import PUTER_AVAILABLE
from app_agent.prompts import APP_AGENT_PROMPT
from utils.llm import call_llm
from utils.json_parser import extract_json
from utils.logger import logger

MAX_STEPS = 30


class AppAgentCore:
    """
    Autonomous GUI automation agent.
    run(task: str) → str  (result summary or error message)
    """

    def __init__(self) -> None:
        self.tools = GUIToolKit()

    def run(self, task: str) -> str:
        logger.info(f"[app-agent-core] Task: {task!r}")
        if PUTER_AVAILABLE:
            logger.info("[app-agent-core] Puter AI vision: ENABLED")
        else:
            logger.warning("[app-agent-core] Puter AI vision: DISABLED (set PUTER_AUTH_TOKEN in .env)")

        start = time.time()

        # Opening instruction — steer agent based on task type
        _web_keywords = (
            "chrome", "gmail", "google", "youtube", "browser",
            "website", "http", "www", ".com", "open url", "navigate to",
            "mail", "compose", "email",
        )
        _task_lower = task.lower()
        _is_web_task = any(kw in _task_lower for kw in _web_keywords)

        if _is_web_task:
            opening = (
                f"TASK: {task}\n\n"
                "This is a WEB/BROWSER task. Strategy:\n"
                "1. Use LIST_WINDOWS to check what's open.\n"
                "2. If Chrome is already open (any window), use FOCUS_WINDOW with a "
                "   short keyword like 'Chrome' — it will pick the first non-terminal match automatically.\n"
                "3. Immediately after focusing, use VISION_HOTKEY [ctrl, l] to focus the address bar "
                "   (do NOT try READ_TREE on Chrome — it won't work).\n"
                "4. Type the URL, press Enter, wait, then use SCREENSHOT to see the page.\n"
                "5. Use VISION_CLICK for ALL interactions on web pages.\n"
                "DO NOT attempt LAUNCH_APP chrome unless LIST_WINDOWS shows zero Chrome windows."
            )
        else:
            opening = (
                f"TASK: {task}\n\n"
                "Begin: use LIST_WINDOWS to see open apps, then decide whether to use "
                "accessibility (READ_TREE) or vision (SCREENSHOT) based on what's open."
            )

        messages: list[dict] = [{"role": "user", "content": opening}]
        final_result = f"[Task incomplete after {MAX_STEPS} steps]"
        parse_failures = 0

        for step in range(1, MAX_STEPS + 1):
            print(f"[app step {step:02d}] Thinking...", end=" ", flush=True)

            try:
                raw = call_llm(APP_AGENT_PROMPT, messages, max_tokens=1000)
            except Exception as exc:
                final_result = f"[LLM error at step {step}: {exc}]"
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
                    "content": "Your response was not valid JSON. Reply with ONLY a single JSON object.",
                })
                continue

            parse_failures = 0
            thought = parsed.get("thought", "")
            action = parsed.get("action", {})
            done = parsed.get("done", False)
            atype = action.get("type", "?").upper()

            print(atype)
            if thought:
                print(f"         → {thought.splitlines()[0][:100]}")

            if atype == "FINISH" or done:
                final_result = action.get("summary", thought)
                print(f"\n[app-agent] ✓ COMPLETE\n{final_result}")
                break

            result = self.tools.execute(action)
            # Truncate very long vision outputs to avoid flooding the context
            result_for_context = result[:4000] if len(result) > 4000 else result
            print(f"         ← {result.splitlines()[0][:90]}")

            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"RESULT:\n{result_for_context}"})

        return final_result