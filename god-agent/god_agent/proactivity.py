"""
god_agent/proactivity.py — Proactive watch engine.

After every user input (from turn 2 onward) the LLM decides:
  - reactive  : handle once, done
  - proactive : keep watching a condition, fire agent chain when triggered

When proactive:
  - Reads screen via Windows Accessibility API first (zero LLM tokens)
  - Only polls web if accessibility tree returns nothing useful
  - Sleeps intelligently between checks
  - Fires full God Agent only when trigger condition is ACTUALLY met (not just "data exists")
  - 300s cooldown after a trigger fires to prevent immediate re-triggering
  - Stops when stop condition is met or user types 'stop watching'
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional, Callable

from utils.llm import call_llm
from utils.json_parser import extract_json
from utils.logger import logger

# ── Prompts ───────────────────────────────────────────────────────────

DECIDER_PROMPT = """\
You decide if a user request is reactive (answer once) or proactive (keep watching).

Reactive: questions, build tasks, research, one-shot commands.
Proactive: monitoring, watching for events, waiting for something to happen.

Examples of proactive:
- "monitor train 12345 and alert me if delayed more than 20 mins"
- "watch my inbox and tell me when X emails me"
- "keep an eye on this stock and notify me if it drops below Y"
- "stand by and alert me if anything changes on screen"

For proactive, decide HOW to check:
- accessibility_tree: reading a visible app/browser window on screen
- web_poll: hitting a URL or API endpoint periodically
- both: check tree first, fall back to web if tree is empty

Respond ONLY with this JSON:
{
  "mode": "reactive | proactive",
  "trigger_condition": "exact anomaly/event that should fire the agents — be very specific",
  "check_interval_seconds": 60,
  "stop_condition": "when to stop watching entirely",
  "check_method": "accessibility_tree | web_poll | both",
  "poll_target": "URL or search query if web_poll, else null",
  "reasoning": "one line"
}

If reactive, set mode=reactive and leave everything else null/0.\
"""

SCREEN_EVAL_PROMPT = """\
You are a precise trigger evaluator. Decide if a SPECIFIC ANOMALY has actually occurred.

Trigger condition: {condition}
Stop condition: {stop}

Current data:
{screen_text}

CRITICAL: Only triggered=true if data DIRECTLY CONFIRMS the specific anomaly.
- "train delayed" → true ONLY if data shows an actual delay with minutes, not just that trains exist
- "email from X" → true ONLY if data shows an unread message from X right now
- "price below Y" → true ONLY if data shows the actual current price IS below Y
- "platform conflict" → true ONLY if data shows two trains at same platform same time

General background info (APIs exist, service is running, data is available) → triggered=false.
Specific anomaly/event confirmed → triggered=true.

Respond ONLY with JSON (no other text):
{{"triggered": true/false, "stop": true/false, "reason": "one line — what specifically confirmed or denied"}}\
"""


@dataclass
class WatchConfig:
    trigger_condition: str
    check_interval_seconds: int
    stop_condition: str
    check_method: str
    poll_target: Optional[str]


class ProactivityDecider:
    def decide(self, user_input: str) -> tuple[str, Optional[WatchConfig]]:
        raw = call_llm(
            DECIDER_PROMPT,
            [{"role": "user", "content": user_input}],
            max_tokens=256,
        )
        parsed = extract_json(raw)
        if not parsed or parsed.get("mode") == "reactive":
            return "reactive", None

        cfg = WatchConfig(
            trigger_condition=parsed.get("trigger_condition", user_input),
            check_interval_seconds=max(30, int(parsed.get("check_interval_seconds") or 60)),
            stop_condition=parsed.get("stop_condition", "user says stop"),
            check_method=parsed.get("check_method", "both"),
            poll_target=parsed.get("poll_target"),
        )
        logger.info(
            f"[proactive] mode=proactive | interval={cfg.check_interval_seconds}s "
            f"| method={cfg.check_method} | trigger={cfg.trigger_condition!r}"
        )
        return "proactive", cfg


class ScreenReader:
    def read(self, cfg: WatchConfig) -> str:
        parts = []

        if cfg.check_method in ("accessibility_tree", "both"):
            tree_text = self._read_accessibility_tree()
            if tree_text:
                parts.append(f"[SCREEN]\n{tree_text[:3000]}")

        if cfg.check_method in ("web_poll", "both") and cfg.poll_target:
            web_text = self._poll_web(cfg.poll_target)
            if web_text:
                parts.append(f"[WEB]\n{web_text[:3000]}")

        return "\n\n".join(parts) if parts else ""

    def _read_accessibility_tree(self) -> str:
        try:
            import ctypes
            import pywinauto
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            windows = desktop.windows()
            target = None
            for w in windows:
                try:
                    if w.handle == hwnd:
                        target = w
                        break
                except Exception:
                    continue
            if not target and windows:
                target = windows[0]
            if not target:
                return ""

            texts = []
            try:
                wrapper = target.wrapper_object()
                self._collect_text(wrapper, texts, depth=0, max_depth=4)
            except Exception:
                try:
                    texts = [target.window_text()]
                except Exception:
                    pass

            return "\n".join(t for t in texts if t.strip())[:4000]

        except ImportError:
            return ""
        except Exception as e:
            logger.debug(f"[screen-reader] accessibility error: {e}")
            return ""

    def _collect_text(self, element, out: list, depth: int, max_depth: int) -> None:
        if depth > max_depth:
            return
        try:
            text = element.window_text()
            if text and text.strip():
                out.append(text.strip())
        except Exception:
            pass
        try:
            for child in element.children():
                self._collect_text(child, out, depth + 1, max_depth)
        except Exception:
            pass

    def _poll_web(self, target: str) -> str:
        try:
            if target.startswith("http"):
                from research_agent.search import fetch_page
                return fetch_page(target, max_chars=4000)
            else:
                from research_agent.search import web_search
                results = web_search(target, max_results=3)
                if results:
                    return "\n".join(f"{r['title']}: {r['snippet']}" for r in results)
        except Exception as e:
            logger.debug(f"[screen-reader] web poll error: {e}")
        return ""


class TriggerEvaluator:
    def check(self, screen_text: str, cfg: WatchConfig) -> tuple[bool, bool]:
        if not screen_text.strip():
            return False, False

        prompt = SCREEN_EVAL_PROMPT.format(
            condition=cfg.trigger_condition,
            stop=cfg.stop_condition,
            screen_text=screen_text[:2000],
        )
        raw = call_llm(
            "You are a trigger evaluator. Respond only with JSON.",
            [{"role": "user", "content": prompt}],
            max_tokens=64,
        )
        parsed = extract_json(raw)
        if not parsed:
            return False, False
        return bool(parsed.get("triggered")), bool(parsed.get("stop"))


class WatchLoop:
    def __init__(self, cfg: WatchConfig, on_trigger: Callable[[str], str]):
        self.cfg = cfg
        self.on_trigger = on_trigger
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reader = ScreenReader()
        self._evaluator = TriggerEvaluator()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"[watch-loop] Started. Interval={self.cfg.check_interval_seconds}s")
        print(
            f"\n[JARVIS] Now watching: {self.cfg.trigger_condition}\n"
            f"         Checking every {self.cfg.check_interval_seconds}s. "
            f"Type 'stop watching' to cancel.\n"
        )

    def cancel(self) -> None:
        self._stop_event.set()
        logger.info("[watch-loop] Cancelled.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                screen_text = self._reader.read(self.cfg)
                triggered, should_stop = self._evaluator.check(screen_text, self.cfg)

                if triggered:
                    logger.info("[watch-loop] Trigger condition met — firing agent chain")
                    print(f"\n[JARVIS] ⚡ Trigger detected: {self.cfg.trigger_condition}")
                    task = (
                        f"PROACTIVE TRIGGER: {self.cfg.trigger_condition}\n\n"
                        f"CURRENT STATE:\n{screen_text[:2000]}"
                    )
                    result = self.on_trigger(task)
                    print(f"\n[JARVIS] {result}\n")

                    # Cooldown — don't re-trigger for 300s after firing
                    logger.info("[watch-loop] Cooling down 300s after trigger.")
                    cooldown_slept = 0
                    while cooldown_slept < 300 and not self._stop_event.is_set():
                        time.sleep(2)
                        cooldown_slept += 2
                    continue

                if should_stop:
                    logger.info("[watch-loop] Stop condition met.")
                    print(f"\n[JARVIS] Stop condition met. No longer watching.\n")
                    break

            except Exception as e:
                logger.error(f"[watch-loop] Error in cycle: {e}")

            # Smart sleep — 2s chunks so cancel() is always responsive
            interval = self.cfg.check_interval_seconds
            slept = 0
            while slept < interval and not self._stop_event.is_set():
                time.sleep(min(2, interval - slept))
                slept += 2
