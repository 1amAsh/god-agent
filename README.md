# JARVIS — Autonomous Multi-Agent Orchestrator

> Give JARVIS a goal in plain English. It figures out which of its agents to call, in what order — research finds real APIs, coding writes and runs real integrations, and the system remembers everything it builds. No hardcoding. No templates. One system that builds other projects.

JARVIS is a local, autonomous multi-agent system built entirely on **free-tier LLM APIs**. Instead of being a single chatbot, it's an orchestrator ("god agent") that routes natural-language tasks to specialized agents — each running its own think → act → observe loop — and shares memory between them through a persistent workspace.

---

## Why JARVIS?

Most AI assistants can write you code. They can't run it, fix it when it breaks, remember what they built last time, or act outside of a chat window. JARVIS does all three:

- **Acts on your machine.** The coding agent writes files, runs commands, reads the output, and iterates — not a code block you copy-paste.
- **Remembers across tasks.** A shared workspace lets agents save and recall artifacts (API specs, scripts, research) across sessions, so later tasks build on earlier ones.
- **Routes itself.** One prompt in — JARVIS decides whether the task needs research, coding, desktop automation, or some chain of all three.
- **Runs on free tiers.** A multi-provider LLM fallback chain (Gemini → Groq → OpenRouter → Ollama) means no subscription and no per-token billing. If one provider hits a rate limit, JARVIS keeps going.
- **Controls the desktop (experimental).** Beyond the terminal, an app agent can drive the actual OS — clicking, typing, launching applications — via the Windows accessibility layer.

---

## Architecture

```
                ┌─────────────────────┐
   user prompt  │      god_agent       │  ← routes & chains tasks
  ─────────────▶│   (orchestrator)     │
                └──────────┬───────────┘
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                     ▼
┌─────────────┐     ┌──────────────┐      ┌─────────────┐
│ research_   │     │ coding_agent  │      │  app_agent  │
│ agent       │     │               │      │ (desktop)   │
│             │     │ think→act→    │      │             │
│ finds &     │     │ observe loop  │      │ UIA-based   │
│ verifies    │     │ writes/runs   │      │ GUI control │
│ real APIs   │     │ real code     │      │             │
└──────┬──────┘     └──────┬────────┘      └──────┬──────┘
       │                    │                       │
       └────────────────────┼───────────────────────┘
                            ▼
                ┌──────────────────────┐
                │  memory / workspace   │  ← shared SQLite store
                │  (jarvis.db)          │     SAVE / RECALL / LIST
                └──────────────────────┘
                            │
                            ▼
                ┌──────────────────────┐
                │  dashboard.py          │  ← live activity view
                │  (localhost:5000)     │
                └──────────────────────┘
```

Each agent runs an **agentic loop** — think, act, observe, repeat — until it finishes or hands off to another agent. The god agent decides routing (single agent vs. a chain like research → coding) and injects shared context (including workspace contents) into each agent's task.

---

## Agents

### `god_agent` — Orchestrator
Reads the user's request, decides which agent(s) are needed and in what order, injects session/workspace context into each sub-task, and formats the final response.

### `research_agent`
Searches the web, fetches real endpoints, and verifies they return real data before reporting back. In "API scout" mode it produces structured, code-ready specs (endpoints, exact field names, working request snippets) rather than prose — and can `SAVE_ARTIFACT` those specs to the shared workspace for the coding agent to use directly.

### `coding_agent`
A senior-engineer-style agent with full file system access. Writes files, runs commands, installs dependencies, executes and verifies its own output. Can `LIST_ARTIFACTS` / `RECALL_ARTIFACT` from the workspace to use specs the research agent already verified, avoiding redundant research.

### `app_agent` (experimental)
Controls the desktop directly via Windows UI Automation (pywinauto) — reading the accessibility tree, clicking elements, typing, launching applications, and sending hotkeys. The one hard safety rule: it will never send terminal-kill hotkeys (Ctrl+C/Z/D/Break) to a terminal window, to avoid killing JARVIS itself. Everything else is unrestricted. **Status: functional but inconsistent** — see [Known Limitations](#known-limitations).

### `memory` / Workspace
A shared SQLite store (`jarvis.db`) holding two things: per-session conversation history, and a cross-session **workspace** of named artifacts any agent can write to or read from (`SAVE_ARTIFACT`, `RECALL_ARTIFACT`, `LIST_ARTIFACTS`).

### `dashboard`
A Flask app (`localhost:5000`) showing live agent activity, task durations, success/failure status, and current workspace contents.

---

## Setup

### Requirements
- Python 3.10+
- [Ollama](https://ollama.com) installed locally (used as the final fallback LLM — free and unlimited)
- Free API keys for at least one of: Gemini, Groq (OpenRouter optional)
- Windows (required only for the `app_agent` desktop automation features — `pywinauto`)

### Installation

```bash
git clone https://github.com/<your-username>/jarvis.git
cd jarvis
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
OPENROUTER_API_KEY=        # optional — leave blank to skip
NASA_API_KEY=DEMO_KEY       # replace with a real key for heavier use
```

LLM calls fall back in this order: **Gemini → Groq → OpenRouter (if configured) → Ollama**. If every cloud provider is rate-limited, JARVIS keeps running on local Ollama.

### Running

```bash
# Terminal 1 — local model fallback
ollama serve

# Terminal 2 — live dashboard
python dashboard.py
# → http://localhost:5000

# Terminal 3 — JARVIS
python main.py
```

---

## Usage

Just describe what you want. Examples:

```text
> find me a free weather API and confirm it returns live data right now

> write a python script that prints the current date and time, then run it

> set up a basic Django project with a clean landing page and get it running on localhost:8000

> I want JARVIS to act like a mission operations assistant for low-earth orbit.
  Find out where the ISS is right now, check whether any near-earth asteroids
  are making a close approach today and whether any are flagged as potentially
  hazardous, and check the current geomagnetic activity level. Put it all
  together into a short risk briefing with your reasoning, as a script I can
  re-run.
```

### REPL commands

| Command | Description |
|---|---|
| `workspace` | List all saved artifacts (key, agent, timestamp, size) |
| `recall <key>` | Print the full content of a saved artifact |
| `memory` | Show current session conversation history |

---

## Known Limitations

- **`app_agent` is experimental.** Desktop automation via the accessibility tree works inconsistently depending on the target application — some tasks complete fully, others stall partway through (e.g. reading a browser's accessibility tree). This is the most active area of development.
- **Free-tier rate limits.** Public demo APIs (e.g. NASA's `DEMO_KEY`) have low hourly limits. Use a personal free API key for anything beyond light testing.
- **Windows-only desktop automation.** `app_agent` relies on `pywinauto` and the Windows UI Automation API; the rest of JARVIS is cross-platform.

---

## Roadmap

- **Self-improvement loop** — give the coding agent a sandboxed copy of JARVIS's own source in a separate environment so it can write, test, and (after verification) merge new agents into itself.
- **More specialized agents** — email handling, calendar/schedule management, and file organization are next; the orchestration layer already supports adding new agents without structural changes.
- **More reliable desktop automation** — stabilizing `app_agent` across more applications.
- **Keep everything on free tiers** — accessibility is a deliberate constraint, not an afterthought.

---

## Contributing

Issues and PRs welcome. If you're adding a new agent, follow the existing pattern: an agentic loop (`think → act → observe`), a dedicated `prompts.py`, and workspace integration via `memory.handle_workspace_action`.

---

## License

[Choose a license — e.g. MIT] — add a `LICENSE` file to the repo root.
