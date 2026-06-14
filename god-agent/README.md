# ⚡ JARVIS — God Agent

**A fully autonomous multi-agent AI operating system. Not a chatbot. Not a wrapper. An AI that thinks about which AI to use.**

---

## What Is This?

JARVIS is the **mother OS** for every other software project. Give it any complex goal across any domain — it autonomously decomposes the task, routes it to specialist agents, chains their outputs, and builds something real.

> *"Build me a live railway delay monitor"*
> → Research agent finds a working free Indian Railways API
> → Coding agent writes and runs the integration
> → JARVIS delivers a working Python script with real live data

> *"Monitor the Rajdhani Express and alert me if it's delayed more than 20 minutes"*
> → JARVIS sets a proactive watch loop
> → Research agent polls live status every 60 seconds
> → If triggered: coding agent calculates downstream impact and generates an ops report

**Every other hackathon project is single-purpose. JARVIS builds them all.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         JARVIS (God Agent)                      │
│   LLM-driven routing · Session memory · Shared workspace        │
└───────────┬──────────────────┬──────────────────────────────────┘
            │                  │                  │
   ┌────────▼──────┐  ┌────────▼──────┐  ┌───────▼────────┐
   │ Research Agent│  │ Coding Agent  │  │   App Agent    │
   │               │  │               │  │                │
   │ Web search    │  │ Write files   │  │ GUI automation │
   │ FETCH_PAGE    │  │ Run commands  │  │ Click buttons  │
   │ API scouting  │  │ Debug code    │  │ Type text      │
   │ Data scraping │  │ Install pkgs  │  │ Read screen    │
   └───────────────┘  └───────────────┘  └────────────────┘
            │                  │                  │
            └──────────────────▼──────────────────┘
                     Shared Workspace (SQLite)
              Named artifacts persist across sessions
```

### What Makes This Different

- **Pure LLM routing** — No if-else, no keyword matching. The orchestrator reads agent capability cards and reasons about task decomposition.
- **A2A chaining with context injection** — Research agent output is injected as ground truth into the coding agent. No mock data.
- **API Scout mode** — When research feeds coding, it produces a structured, code-ready API spec (endpoints, Python snippets, response schemas) — not a prose summary.
- **Intentional workspace persistence** — Agents decide when to save artifacts (`SAVE_ARTIFACT`). The coding agent can `RECALL_ARTIFACT` the research agent's spec even in a different session.
- **Proactive watch loop** — Anomaly-only triggering (not "data exists" triggering). 300s cooldown after trigger fires.
- **Free unlimited local fallback** — Ollama (qwen2.5:1.5b) is the last tier. Demo never crashes mid-run.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env .env.local  # already exists with template
# Fill in your keys:
GEMINI_API_KEY=...   # aistudio.google.com — free
GROQ_API_KEY=...     # console.groq.com — free
SERPER_API_KEY=...   # serper.dev — free 2500 searches/month
```

### 3. (Recommended) Set up Ollama local fallback

```bash
# Download Ollama from https://ollama.com
ollama pull qwen2.5:1.5b        # ~900MB — main brain
ollama pull qwen2.5-coder:1.5b  # ~900MB — coding tasks
ollama serve                     # keep running in background
```

Ollama kicks in automatically when cloud providers hit rate limits. No crashes mid-demo.

### 4. Run JARVIS

Terminal 1 (dashboard — optional but impressive):
```bash
python dashboard.py
# Open http://localhost:5000
```

Terminal 2 (JARVIS):
```bash
python main.py
```

---

## Demo Flow (Recommended for Video)

```
You: Build me a live Indian Railways delay monitor for the Rajdhani Express

→ JARVIS routes: research (api_scout mode) → coding (use spec from context)
→ Research agent: finds working free API, saves spec as "indian_railways_api_spec"
→ Coding agent: RECALLs spec, builds Python monitor, runs it with real data
→ JARVIS: delivers working script with actual train status

You: Now monitor train 12301 and alert me if it's more than 20 minutes late

→ JARVIS detects proactive intent, starts watch loop
→ Every 60s: research agent polls live status
→ If delay > 20 min: coding agent calculates downstream impact
→ JARVIS prints ops report with remediation steps

You: Build me a weather dashboard for Hyderabad

→ Research agent: finds open-meteo.com (no auth needed), saves spec
→ Coding agent: builds working Python weather CLI, runs it, shows real data

You: workspace
→ [railway_monitor_complete] by coding | 2024-06-13 | 2847 chars
→ [indian_railways_api_spec] by research | 2024-06-13 | 1923 chars
→ [weather_dashboard_hyderabad] by coding | 2024-06-13 | 1654 chars
```

---

## REPL Commands

| Command | What it does |
|---|---|
| `exit` / `quit` | Shut down |
| `workspace` | List all saved agent artifacts |
| `recall <key>` | Read a specific artifact |
| `memory` | Show conversation history |
| `session` | Show current session ID |
| `stop watching` | Cancel proactive watch loop |

---

## Agent Capabilities

### Research Agent
- Web search (Serper/Google with DuckDuckGo fallback)
- Full page fetch with BeautifulSoup content extraction
- Three modes: `research` (deep synthesis), `scrape` (structured extraction), `api_scout` (code-ready API spec)
- `SAVE_ARTIFACT` — saves research output to shared workspace
- `RECALL_ARTIFACT` — loads prior research from workspace (avoids re-searching)

### Coding Agent  
- Read/write/edit/delete files across the entire filesystem
- Run shell commands with timeout
- Move/copy files, grep search, find files system-wide
- `RECALL_ARTIFACT` — loads API spec or data from research agent
- `SAVE_ARTIFACT` — saves built scripts/integrations for later use

### App Agent (Windows)
- List open windows, read accessibility tree
- Click, double-click, type text, keyboard shortcuts
- Launch applications, focus windows
- Terminal windows are automatically blocked — can't self-destruct
- Requires: `pip install pywinauto` on Windows

---

## LLM Fallback Chain

```
Gemini 2.5 Flash (primary, fast, smart)
    ↓ [rate limit / quota]
Groq llama-3.3-70b (fast inference)
    ↓ [rate limit]
OpenRouter (optional, very cheap)
    ↓ [not configured]
Ollama qwen2.5:1.5b (local, FREE, unlimited)
```

JARVIS never crashes due to token exhaustion — it falls through the chain automatically.

---

## Environment Variables

```bash
# LLM Providers
GEMINI_API_KEY=          # google ai studio (free)
GROQ_API_KEY=            # groq console (free)
OPENROUTER_API_KEY=      # openrouter.ai (optional, $2 credit lasts forever)

# Research
SERPER_API_KEY=          # serper.dev (free 2500/month)

# Model selection
GOD_LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash
GROQ_MODEL=llama-3.3-70b-versatile

# Ollama (local fallback)
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_CODING_MODEL=qwen2.5-coder:1.5b

# Config
MAX_CLARIFICATIONS=2
MAX_AGENT_RETRIES=1
CODING_WORKSPACE=coding_agent/workspace
MEMORY_DB=memory/jarvis.db
LOG_DIR=logs
```

---

## Project Structure

```
jarvis/
├── main.py                    # Entry point / REPL
├── dashboard.py               # Live Flask dashboard (localhost:5000)
├── requirements.txt
├── .env                       # Your API keys
│
├── god_agent/
│   ├── god_agent.py           # Orchestrator — routing, chaining, memory
│   ├── prompts.py             # SELF_AWARENESS_BLOCK + ROUTING_PROMPT
│   └── proactivity.py        # Watch loop, trigger evaluation, cooldown
│
├── research_agent/
│   ├── agent.py               # Agentic loop with SAVE/RECALL workspace actions
│   ├── prompts.py             # research / scrape / api_scout mode prompts
│   └── search.py              # Serper + DDG web search + page fetch
│
├── coding_agent/
│   ├── agent.py               # Agentic loop with SAVE/RECALL workspace actions
│   ├── prompts.py             # Full system prompt + plan prompt
│   └── tools.py               # File ops, shell commands, system-wide access
│
├── app_agent/
│   ├── agent.py               # I/O contract wrapper
│   ├── core.py                # Agentic loop (self-contained, no external deps)
│   ├── prompts.py             # GUI automation prompt + terminal safety
│   └── tools.py               # pywinauto wrapper, terminal window blocklist
│
├── memory/
│   └── memory.py              # Memory (SQLite) + Workspace + handle_workspace_action
│
├── schemas/
│   └── contract.py            # TaskRequest / AgentResponse I/O contract
│
├── utils/
│   ├── llm.py                 # LLM fallback chain (Gemini → Groq → OpenRouter → Ollama)
│   ├── json_parser.py         # Robust JSON extraction from LLM outputs
│   └── logger.py              # Structured logging + task_log.jsonl
│
├── agent_cards/               # Agent capability descriptors (read by router)
│   ├── coding_agent.json
│   ├── research_agent.json
│   └── app_agent.json
│
└── logs/
    ├── god_agent.log
    └── task_log.jsonl         # Machine-readable event stream (read by dashboard)
```

---

## FAR AWAY Hackathon — Judging Criteria

| Criterion | How JARVIS addresses it |
|---|---|
| **Innovation & Technical Depth** | LLM-driven routing without hardcoding; A2A chaining with context injection; API scout mode that produces code-ready specs; intentional workspace persistence across sessions |
| **Engineering Quality** | Clean I/O contracts (TaskRequest/AgentResponse); structured logging; fallback LLM chain; graceful degradation when agents unavailable |
| **Real-World Impact** | Live railway monitoring with autonomous delay detection and ops report generation; applicable to any real-time data domain |
| **Scalability** | Pluggable agent architecture — add a new agent by dropping a JSON card and implementing the interface |
| **Design & UX** | Live terminal UI + Flask dashboard; REPL commands for workspace, memory, recall; self-explanatory output |
| **Execution Quality** | Runs locally on Windows; Ollama fallback means demo never dies mid-run; watch loop has 300s cooldown to prevent spam |
