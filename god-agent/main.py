"""
main.py — JARVIS God Agent entry point.

Usage:
  python main.py                    # interactive REPL
  python main.py "build a todo app" # single task
  python main.py --session abc123   # resume session
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

from god_agent.god_agent import GodAgent

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗                   ║
║      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝                   ║
║      ██║███████║██████╔╝██║   ██║██║███████╗                   ║
║ ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║                   ║
║ ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║                   ║
║  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝                   ║
║                                                                  ║
║         God Agent — Multi-Agent AI Operating System             ║
║         Coding  ·  Research  ·  GUI Automation                  ║
║                                                                  ║
║  Commands:                                                       ║
║    exit / quit   — shut down                                     ║
║    memory        — show conversation history                     ║
║    workspace     — show saved agent artifacts                    ║
║    recall <key>  — read a workspace artifact                     ║
║    session       — show session ID                               ║
║    stop watching — cancel proactive watch loop                   ║
╚══════════════════════════════════════════════════════════════════╝
"""


def _check_env() -> list[str]:
    warnings = []
    if not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
        warnings.append("⚠  No cloud LLM key found. Set GROQ_API_KEY or GEMINI_API_KEY in .env")
        warnings.append("   Ollama local fallback will be used if running (ollama serve)")
    if not os.environ.get("SERPER_API_KEY"):
        warnings.append("ℹ  SERPER_API_KEY not set — research agent will use DuckDuckGo fallback.")
    return warnings


def _repl(session_id: str | None = None) -> None:
    print(BANNER)

    for w in _check_env():
        print(f"  {w}")

    agent = GodAgent()
    if session_id:
        agent.session_id = session_id
        print(f"  Resuming session: {agent.session_id}")
    else:
        print(f"  New session: {agent.session_id}")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[JARVIS] Standing by. Goodbye.")
            break

        if not user_input:
            continue

        low = user_input.lower()

        if low in ("exit", "quit", "q", "bye"):
            print("[JARVIS] Goodbye, sir.")
            break

        if low == "session":
            print(f"[JARVIS] Session ID: {agent.session_id}")
            continue

        if low == "memory":
            history = agent.memory.recent(agent.session_id, limit=10)
            if not history:
                print("[JARVIS] No conversation history yet.")
            else:
                for m in history:
                    tag = "You" if m["role"] == "user" else "JARVIS"
                    print(f"  {tag}: {m['content'][:200]}")
            continue

        if low == "workspace":
            items = agent.workspace.list_keys()
            if not items:
                print("[JARVIS] Workspace is empty.")
            else:
                print("[JARVIS] Workspace artifacts:")
                for item in items:
                    print(f"  [{item['key']}] by {item['agent']} | {item['ts'][:16]} | {item['size']} chars")
            continue

        if low.startswith("recall "):
            key = user_input[7:].strip()
            content = agent.workspace.read(key)
            if content:
                print(f"[JARVIS] {key}:\n{content[:3000]}")
            else:
                print(f"[JARVIS] Nothing found for key: {key!r}")
                items = agent.workspace.list_keys()
                if items:
                    print("  Available keys: " + ", ".join(i['key'] for i in items[:8]))
            continue

        if low == "clear":
            agent.memory.clear(agent.session_id)
            print("[JARVIS] Memory cleared.")
            continue

        print()
        try:
            response = agent.process(user_input)
            print(f"\n[JARVIS] {response}\n")
        except KeyboardInterrupt:
            # Ctrl+C from user keyboard — don't exit, keep REPL alive
            print("\n[JARVIS] Task interrupted. Continuing session.")
            continue
        except Exception as e:
            print(f"\n[JARVIS] An error occurred: {e}\n")


def main() -> None:
    args = sys.argv[1:]
    session_id = None
    cleaned = []
    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        else:
            cleaned.append(args[i])
            i += 1

    if not cleaned:
        _repl(session_id)
        return

    task = " ".join(cleaned)
    print(f"[JARVIS] Processing: {task!r}\n")
    agent = GodAgent()
    if session_id:
        agent.session_id = session_id
    try:
        response = agent.process(task)
        print(f"\n[JARVIS] {response}")
    except Exception as e:
        print(f"[JARVIS] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
