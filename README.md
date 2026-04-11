# AXON Neural Bridge

> A Telegram-based AI pipeline that generates, validates, and audits Python automation code — built for freelance delivery.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-orange.svg)](https://anthropic.com)
[![Gemini](https://img.shields.io/badge/Audit-Gemini%202.5%20Flash-green.svg)](https://deepmind.google)
[![Version](https://img.shields.io/badge/Version-v8.4-gold.svg)](#changelog)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

---

## What is AXON?

AXON is a Telegram bot that acts as a personal AI development pipeline. You send it a task in plain language. It writes the code, runs it in an isolated sandbox, generates unit tests, cross-audits it with a second AI model, and delivers a validated `.py` file — all automatically.

It was built to power freelance Python automation delivery on Upwork: every output is production-ready by design, not by accident.

```
You → Telegram → AXON → Claude writes code
                      → Sandbox runs it
                      → Unit tests validate logic
                      → Gemini audits quality
                      → .py file delivered back to You
```

---

## Architecture

AXON uses a **three-layer validation pipeline** for every code generation task:

```
┌─────────────────────────────────────────────────────────────┐
│                        TELEGRAM BOT                         │
│                   (axon_telegram_v6.py)                     │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                   PIPELINE ROUTER                           │
│  DEVELOPER │ PLANNER │ CREATIVE │ ANALYST                   │
│  (keyword match → Claude fallback classification)           │
└──────────────┬──────────────────────────────────────────────┘
               │  (DEVELOPER pipeline only)
               ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1 — SANDBOX          (axon_sandbox_v2.py)            │
│  • Isolated subprocess execution                            │
│  • Static security filter (blocks os.system, subprocess…)  │
│  • Risk approval via Telegram inline button                 │
└──────────────┬───────────────────────────────────────────────┘
               │ PASS
               ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 2 — UNIT TESTS       (axon_sandbox_v2.py)            │
│  • MagicMock-based dependency injection                     │
│  • Tests run without live DB / API connections              │
│  • Auto-generated test suite per task                       │
└──────────────┬───────────────────────────────────────────────┘
               │ PASS
               ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 3 — GEMINI AUDIT     (axon_auditor_v2.py)            │
│  • Cross-model logical review (Google Gemini 2.5 Flash)     │
│  • Scores 0–100, threshold: 55                              │
│  • On FAIL → Claude fix round (max 2 retries)               │
└──────────────┬───────────────────────────────────────────────┘
               │ PASS
               ▼
        Validated .py file → Telegram
```

**Supporting modules:**

| Module | Role |
|---|---|
| `axon_memory.py` | SQLite storage: task cache, training data, fix samples, conversation history, API cost tracking |
| `axon_retry.py` | Exponential backoff wrapper for all API calls (max 3 attempts, 200ms–2s) |
| `axon_compaction.py` | Automatic conversation history compaction when history exceeds 6,000 chars |
| `axon_watchman.py` | Background SRE monitor: CPU, RAM, disk, network health checks |
| `axon_context.py` | Shared project context injected into every pipeline prompt |
| `souls/` | Pipeline persona files loaded at startup, with hardcoded fallback |

---

## Four Pipelines

AXON automatically routes every message to the appropriate pipeline:

| Pipeline | Icon | Use Case | Cache | Validation |
|---|---|---|---|---|
| `DEVELOPER` | ⚙️ | Python code generation | ✅ | Sandbox + Unit tests + Gemini |
| `PLANNER` | 📋 | Architecture plans, sprint docs | ✅ | None (markdown output) |
| `CREATIVE` | ✍️ | Cover letters, proposals, emails | ❌ | None (always unique) |
| `ANALYST` | 📊 | Data analysis, market research | ✅ | None |

Routing uses keyword matching first (zero API cost), with Claude fallback classification for ambiguous inputs.

---

## Key Features

### Task Cache
Identical tasks return cached results instantly — zero API cost on repeat runs. Cache is SHA-256 keyed on `pipeline + task`, TTL 30 days. Only validated (PASS) outputs are cached. Cache is invalidated automatically when `CONTEXT_VERSION` changes.

### Conversation Memory
AXON maintains multi-turn conversation history per chat session. "Add logging to the previous code" works — it knows what the previous code was. History persists across bot restarts via SQLite. Sessions auto-expire after 2 hours of inactivity.

### SOUL Loader
Each pipeline reads its system prompt from a `.md` file in `souls/`. Edit `souls/developer.md` to change how AXON writes code — no restart needed. Falls back to hardcoded prompts if files are missing.

### Upwork Wizard
`/upwork` triggers a 3-step ConversationHandler: job description → budget → cover letter generation. The CREATIVE pipeline generates human-sounding, non-AI-patterned letters.

### API Cost Tracking
Every Claude API call is logged with pipeline attribution. `/stats` shows cost breakdown per pipeline over configurable time windows.

### Retry & Resilience
All API calls go through `axon_retry.py`: exponential backoff on HTTP 500/503/529, `RateLimitError`, `APIConnectionError`, `APITimeoutError`.

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Initialize bot, restore previous session history |
| `/stop` | Kill switch — pause all processing |
| `/status` | System status, active pipeline, conversation turns |
| `/stats [days]` | API cost + cache stats, default 7 days |
| `/upwork` | Cover letter generation wizard |
| `/compact` | Manually trigger conversation history compaction |
| `/clear` | Clear current conversation history |
| `/history` | Show active context summary |
| `/review` | Deep Gemini re-audit on last generated code |
| `/bypass [task]` | Generate code without validation (use with care) |
| `/cache_clear` | Wipe task cache |
| `/list_outputs` | List all generated .py files |

---

## Project Structure

```
axon-neural-bridge/
├── axon_telegram_v6.py     # Main bot — pipeline orchestration
├── axon_memory.py          # SQLite layer — cache, history, costs, training data
├── axon_sandbox_v2.py      # Sandbox executor + unit test runner
├── axon_auditor_v2.py      # Gemini cross-check auditor
├── axon_retry.py           # Exponential backoff retry wrapper
├── axon_compaction.py      # Conversation history compactor
├── axon_watchman.py        # Background SRE health monitor
├── axon_context.py         # Shared project context
├── souls/
│   ├── developer.md        # DEVELOPER pipeline system prompt
│   ├── planner.md          # PLANNER pipeline system prompt
│   ├── creative.md         # CREATIVE pipeline system prompt
│   └── analyst.md          # ANALYST pipeline system prompt
├── .env.example            # Environment variable template
├── requirements.txt
└── README.md
```

Runtime directories (auto-created, git-ignored):
```
outputs/                    # Generated .py files
uploads/                    # Telegram file uploads
axon.db                     # SQLite database
```

---

## Setup

### Prerequisites
- Python 3.11+
- Telegram bot token ([@BotFather](https://t.me/BotFather))
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Google Gemini API key — **paid tier required** ([aistudio.google.com](https://aistudio.google.com/app/apikey))

> **Why paid Gemini?** The free tier allows Google to use prompt data for model training. Client code and business logic must not go there.

### Installation

```bash
git clone https://github.com/kocsgab88/axon-neural-bridge.git
cd axon-neural-bridge

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in your API keys
```

### Configuration

```env
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_KEY=your_anthropic_api_key
GEMINI_KEY=your_gemini_api_key_paid_tier
```

### Run

```bash
python axon_telegram_v6.py
```

On first start, send any message to the bot. AXON registers your Telegram chat ID as the owner automatically — only that chat ID can interact with the bot.

---

## Customizing Pipeline Prompts

Edit the files in `souls/` to change how each pipeline behaves:

```
souls/developer.md    →  How AXON writes Python code
souls/planner.md      →  How AXON structures documents
souls/creative.md     →  How AXON writes cover letters
souls/analyst.md      →  How AXON analyzes data
```

Changes take effect on bot restart. If a soul file is missing, the hardcoded fallback in `axon_telegram_v6.py` activates automatically.

---

## Changelog

### v8.4 — 2026-04-09
- **History SQLite persistence** — conversation history survives bot restarts
- `restore_history()` called on `/start`, user notified if previous session found
- `cleanup_old_history()` — daily JobQueue job, 7-day retention
- All hardcoded Windows paths replaced with `BASE_DIR = Path(__file__).parent`
- Bug fix: auto-compact attribute errors (`new_history`, `original_chars`, `new_chars`)
- Bug fix: `persist_history` was not imported or called — history was never actually saved
- Bug fix: `log_task_cost` missing `pipeline` param + `ALTER TABLE` migration for existing DBs

### v8.3 — 2026-04
- Pipeline-level cost tracking in `/stats` with per-pipeline breakdown and icons

### v8.2 — 2026-04
- SOUL.md loader system (`souls/` directory, hot-reload on restart)
- Auto-compact trigger at 6,000 chars conversation history
- `/upwork` wizard: 3-step ConversationHandler (job → budget → generate), `/skip` + `/cancel`, 300s timeout
- Watchman migrated to PTB native `job_queue.run_repeating()`

### v8.1 — 2026-04
- `axon_compaction.py` — automatic history compaction
- `/compact` manual trigger command

### v8.0 — 2026-04
- `axon_retry.py` — exponential backoff retry wrapper
- Covers HTTP 500/503/529, RateLimitError, APIConnectionError, APITimeoutError
- Max 3 attempts, 200ms–2s delay range

### v6.0 — 2026-03-26
- Multi-turn conversation memory (in-memory, per chat_id)
- Session timeout: 2h inactivity → auto clear + Telegram notification
- `/clear` and `/history` commands
- DEVELOPER history stores `validated_code`, not Telegram-formatted output
- Cache bypass when conversation history is active (context-dependent code)

### v5.3 — 2026-03-22
- Four pipeline routing: DEVELOPER / PLANNER / CREATIVE / ANALYST
- Keyword-first routing (zero API cost), Claude fallback for ambiguous input
- CREATIVE pipeline never cached

### v5.2 — 2026-03-21
- `OWNER_CHAT_ID` persisted in SQLite — survives restarts
- Multi-session code generation: SIMPLE → 2 sessions, COMPLEX → 3 sessions
- Gemini audit threshold: 55/100

### v5.1 — 2026-03-20
- Task cache: SHA-256, SQLite, 30-day TTL
- Only validated outputs cached
- Cache stats in `/stats`

### v5.0 — 2026-03-19
- `axon_memory.py` — training data collection
- `axon_watchman.py` — SRE background monitor
- `fix_samples` table — bad→fixed code pairs for future fine-tuning

### v4.0 — 2026-03-18
- Gemini Cross-Check (Layer 3 validation)
- `axon_auditor_v2.py` — Gemini 2.5 Flash integration
- On FAIL: Claude fix round, max 2 retries

### v3.0 — 2026-03-18
- Unit test layer (Layer 2)
- `axon_sandbox_v2.py` — MagicMock dependency injection
- Kill switch: `/stop` / `/start`

### v2.0 — 2026-03-17
- Sandbox (Layer 1) — isolated subprocess execution
- Static security filter
- Risk approval via inline keyboard

### v1.0 — 2026-03-17
- Telegram bot + Claude API integration
- Owner registration on first message

---

## Roadmap

| Version | Feature | Status |
|---|---|---|
| **v8.5** | Few-shot learning from `fix_samples` — abstract lesson extraction + HU→EN keyword normalization | 🔜 Next |
| **v8.6** | Mini Claude pre-selection for few-shot samples (activates at 30+ samples) | Planned |
| **v9.0** | Service layer refactor — `task_service.py`, `pipeline_service.py`, clean separation of concerns | Planned |
| **v9.1** | Pydantic data models, TaskMemory, TaskOutcome tracking | Planned |
| **v9.x** | Security audit pipeline, rate limiting, sandbox hardening | Q3 2026 |

---

## Design Decisions

**Why two AI models?**
Claude writes the code. Gemini audits it. Two independent models catch different classes of errors — Claude's blind spots are not Gemini's. Cross-model validation is more reliable than self-review.

**Why paid Gemini tier?**
Free tier terms allow Google to use prompts for model training. Client code must not enter that pipeline.

**Why cache only validated outputs?**
Caching a failed or mediocre result would serve that same bad output on every repeat call. Only sandbox PASS + Gemini PASS results are stored.

**Why CREATIVE is never cached?**
A cover letter written for one job posting must not be reused for another. Every proposal needs fresh generation.

**Why MagicMock for unit tests?**
Generated code cannot open real database connections or hit live APIs in a sandbox environment. MagicMock stubs let the logic be tested without infrastructure dependencies.

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built by [Kocsis Gábor](https://github.com/kocsgab88) · Budapest · Python Automation Specialist*
