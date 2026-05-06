# AXON Neural Bridge

A Telegram-based AI pipeline that generates, validates, and audits Python automation code — built for freelance delivery.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-purple) ![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-green) ![Version](https://img.shields.io/badge/version-9.1-orange) ![Tests](https://img.shields.io/badge/tests-48%2F48-brightgreen)

## What is AXON?

AXON is a Telegram bot that acts as a personal AI development pipeline. You send it a task in plain language. It writes the code, runs it in an isolated sandbox, generates unit tests, cross-audits it with a second AI model, and delivers a validated `.py` file — all automatically.

Built to power freelance Python automation delivery on Upwork: every output is production-ready by design, not by accident.

```
You → Telegram → AXON → Claude writes code
                      → Sandbox runs it
                      → Unit tests validate logic
                      → Gemini audits quality
                      → .py file delivered back to You
```

## Architecture

AXON v9.0 was a full modular refactor — the original 550-line monolith split into 5 isolated classes:

```
core/
  pipeline.py          # 5 classes: CodeGenerator, AuditFixLoop, OutputWriter,
                       #            CostAccumulator, DeveloperPipeline
bot/
  handlers.py          # Telegram I/O only — no business logic
  router.py            # Pipeline routing (keyword match → Claude fallback)
  commands.py          # /commands handlers
  approvals.py         # Inline keyboard approval flows
models.py              # Pydantic v2 data models — all inter-module contracts
main.py                # Entry point, dependency wiring, AppContext
```

Every class is independently testable and runnable outside Telegram. Telegram I/O is strictly isolated in `bot/handlers.py`.

### Three-layer validation pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — SANDBOX          (axon_sandbox_v2.py)            │
│  • Isolated subprocess execution                            │
│  • Static security filter (blocks os.system, subprocess…)  │
│  • Risk approval via Telegram inline button                 │
└──────────────┬──────────────────────────────────────────────┘
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

### Supporting modules

| Module | Role |
|--------|------|
| `axon_memory.py` | SQLite storage: task cache, training data, fix samples, conversation history, API cost tracking |
| `axon_retry.py` | Exponential backoff wrapper for all API calls (max 3 attempts, 200ms–2s) |
| `axon_compaction.py` | Automatic conversation history compaction when history exceeds 6,000 chars |
| `axon_watchman.py` | Background SRE monitor: CPU, RAM, disk, network health checks |
| `axon_context.py` | Shared project context injected into every pipeline prompt |
| `souls/` | Pipeline persona files loaded at startup, with hardcoded fallback |

## Four Pipelines

AXON automatically routes every message to the appropriate pipeline:

| Pipeline | Icon | Use Case | Cache | Validation |
|----------|------|----------|-------|------------|
| DEVELOPER | ⚙️ | Python code generation | ✅ | Sandbox + Unit tests + Gemini |
| PLANNER | 📋 | Architecture plans, sprint docs | ✅ | None (markdown output) |
| CREATIVE | ✍️ | Cover letters, proposals, emails | ❌ | None (always unique) |
| ANALYST | 📊 | Data analysis, market research | ✅ | None |

Routing uses keyword matching first (zero API cost), with Claude fallback classification for ambiguous inputs.

## Key Features

**Task Cache** — Identical tasks return cached results instantly (zero API cost). SHA-256 keyed on pipeline + task, TTL 30 days. Only validated (PASS) outputs cached. Purged automatically on startup.

**Conversation Memory** — Multi-turn conversation history per chat session. "Add logging to the previous code" works — AXON knows what the previous code was. History persists across bot restarts via SQLite.

**SOUL Loader** — Each pipeline reads its system prompt from a `.md` file in `souls/`. Edit `souls/developer.md` to change how AXON writes code — no restart needed.

**Upwork Wizard** — `/upwork` triggers a 3-step ConversationHandler: job description → budget → cover letter generation.

**API Cost Tracking** — Every Claude API call logged with pipeline attribution. `/stats` shows cost breakdown per pipeline.

**Retry & Resilience** — All API calls go through `axon_retry.py`: exponential backoff on HTTP 500/503/529, RateLimitError, APIConnectionError, APITimeoutError.

**Cost Safety** — `CostAccumulator.discard()` ensures token counts are cleared on early exits (empty code, risk rejection, sandbox fail) — no double-billing on failed runs.

## Telegram Commands

| Command | Description |
|---------|-------------|
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

## Project Structure

```
axon-neural-bridge/
├── core/
│   └── pipeline.py             # Pipeline orchestration — 5 isolated classes
├── bot/
│   ├── handlers.py             # Telegram I/O — all user-facing logic
│   ├── router.py               # Pipeline routing
│   ├── commands.py             # /command handlers
│   └── approvals.py            # Inline keyboard flows
├── tests/
│   ├── test_pipeline.py        # 48 tests — pipeline, helpers, OutputWriter
│   ├── test_models.py          # Pydantic model validators
│   ├── test_handlers.py        # Handler logic
│   ├── test_commands.py        # Command handlers
│   └── test_router.py          # Routing logic
├── models.py                   # Pydantic v2 data models
├── main.py                     # Entry point + dependency wiring
├── axon_memory.py              # SQLite layer
├── axon_sandbox_v2.py          # Sandbox executor + unit test runner
├── axon_auditor_v2.py          # Gemini cross-check auditor
├── axon_retry.py               # Exponential backoff retry wrapper
├── axon_compaction.py          # Conversation history compactor
├── axon_watchman.py            # Background SRE health monitor
├── axon_context.py             # Shared project context
├── souls/
│   ├── developer.md            # DEVELOPER pipeline system prompt
│   ├── planner.md              # PLANNER pipeline system prompt
│   ├── creative.md             # CREATIVE pipeline system prompt
│   └── analyst.md              # ANALYST pipeline system prompt
├── CLAUDE.md                   # Claude Code project instructions
├── .env.example                # Environment variable template
├── requirements.txt
└── README.md
```

Runtime directories (auto-created, git-ignored):
```
outputs/                        # Generated .py files
uploads/                        # Telegram file uploads
axon.db                         # SQLite database
```

## Setup

### Prerequisites

- Python 3.10+
- Telegram bot token ([@BotFather](https://t.me/BotFather))
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Google Gemini API key — **paid tier required** ([aistudio.google.com](https://aistudio.google.com))

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
python main.py
```

On first start, send any message to the bot. AXON registers your Telegram chat ID as the owner automatically — only that chat ID can interact with the bot.

### Run tests

```bash
python -m pytest tests/ -v --asyncio-mode=auto
```

## Changelog

### v9.1 — 2026-05-06
- `_extract_code_block` contract fix: returns `str | None` instead of raw text fallback — fixes silent AuditFixLoop failures
- `CostAccumulator.discard()` — token cleanup on early exits; prevents double-billing on failed runs
- `estimate_complexity` false-positive protection: line-level `startswith` check instead of substring match
- `OutputWriter.write()` returns unified timestamp — `.py` and `README` filenames now always match
- `AuditFixLoop` warning log when Claude returns no code block
- Session numbering fix: `1/3–3b/3` → `1/4–3b/4` (COMPLEX is 4 sessions, not 3)
- Cache TTL cleanup on startup via `purge_expired_cache()`
- Dead code removed: `axon_main()` stub deleted
- Test infrastructure: Linux path fix across all 5 test files (Windows-compatible)
- 10 new tests added: `TestOutputWriter`, `test_false_positive_protection`, `test_discard_pops_tokens_without_logging`
- **48/48 tests passing**

### v9.0 — 2026-04-30
- Full modular refactor: 550-line monolith → 5 isolated classes (`CodeGenerator`, `AuditFixLoop`, `OutputWriter`, `CostAccumulator`, `DeveloperPipeline`)
- `bot/` layer: `handlers.py`, `router.py`, `commands.py`, `approvals.py` — Telegram I/O fully separated
- `models.py`: Pydantic v2 data models for all inter-module contracts
- 211 tests passing at release

### v8.4 — 2026-04-09
- History SQLite persistence — conversation history survives bot restarts
- `cleanup_old_history()` — daily JobQueue job, 7-day retention
- All hardcoded Windows paths replaced with `BASE_DIR = Path(__file__).parent`

### v8.3 — 2026-04
- Pipeline-level cost tracking in `/stats` with per-pipeline breakdown

### v8.2 — 2026-04
- SOUL.md loader system (`souls/` directory, hot-reload on restart)
- Auto-compact trigger at 6,000 chars conversation history
- `/upwork` wizard: 3-step ConversationHandler

### v8.0 — 2026-04
- `axon_retry.py` — exponential backoff retry wrapper

### v5.3 — 2026-03-22
- Four pipeline routing: DEVELOPER / PLANNER / CREATIVE / ANALYST

### v5.1 — 2026-03-20
- Task cache: SHA-256, SQLite, 30-day TTL

### v5.0 — 2026-03-19
- `axon_memory.py` — training data collection
- `fix_samples` table — bad→fixed code pairs for future fine-tuning

### v4.0 — 2026-03-18
- Gemini Cross-Check (Layer 3 validation)

### v3.0 — 2026-03-18
- Unit test layer (Layer 2), MagicMock dependency injection

### v2.0 — 2026-03-17
- Sandbox (Layer 1) — isolated subprocess execution

### v1.0 — 2026-03-17
- Telegram bot + Claude API integration

## Roadmap

| Version | Feature | Status |
|---------|---------|--------|
| v9.2 | Agentic pipeline — AXON executes generated code and self-corrects based on real output | 🔜 Next |
| v9.3 | Few-shot learning from `fix_samples` (activates at 30+ samples) | Planned |
| v9.x | `Sandbox`, `Auditor`, `MemoryStore` Protocol definitions — full static type coverage | Planned |

## Design Decisions

**Why two AI models?** Claude writes the code. Gemini audits it. Two independent models catch different classes of errors — Claude's blind spots are not Gemini's blind spots. Cross-model validation is more reliable than self-review.

**Why paid Gemini tier?** Free tier terms allow Google to use prompts for model training. Client code must not enter that pipeline.

**Why cache only validated outputs?** Caching a failed result would serve that same bad output on every repeat call. Only sandbox PASS + Gemini PASS results are stored.

**Why CREATIVE is never cached?** A cover letter written for one job posting must not be reused for another. Every proposal needs fresh generation.

**Why MagicMock for unit tests?** Generated code cannot open real database connections or hit live APIs in a sandbox. MagicMock stubs let the logic be tested without infrastructure dependencies.

**Why modular architecture (v9.0)?** The original monolith made individual components untestable and tightly coupled to Telegram. The 5-class split makes each component independently testable, replaceable, and runnable outside the bot context.

## License

MIT
