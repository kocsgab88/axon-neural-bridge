# AXON Neural Bridge v9.0 — Claude Code Projekt Kontextus

## Projekt áttekintés

**AXON Neural Bridge** egy Telegram bot, ami Claude és Gemini API-t használ Python kód generáláshoz, validáláshoz és auditáláshoz. Egy személyes AI-asszisztens pipeline, amely Upwork feladatok megoldásához és általános automatizáláshoz használt.

- **Tulajdonos:** Kocsis Gábor (Budapest, HU)
- **Futtatási környezet:** Windows 10 / Asus X550JX
- **Bot keretrendszer:** python-telegram-bot (PTB) v20+
- **AI stack:** Claude claude-sonnet-4-6 (generálás), Gemini 2.5 Flash (audit)
- **DB:** SQLite (axon.db)

---

## Projekt struktúra

```
C:\AXON_OPS\AxonV2\
├── main.py                # Belépési pont, AppContext composition root
├── models.py              # Pydantic v2 adatmodellek (SINGLE SOURCE OF TRUTH)
├── core/
│   └── pipeline.py        # DeveloperPipeline + 4 segédosztály
├── bot/
│   ├── handlers.py        # Telegram I/O, TaskHandler, PipelineFormatter
│   ├── commands.py        # Slash command handlerek (/start, /review stb.)
│   ├── router.py          # Pipeline routing (keyword → Claude → fallback)
│   └── approvals.py       # Kockázatos kód jóváhagyás callback
├── axon_memory.py         # SQLite memory, cache, history (legacy, de aktív)
├── axon_auditor_v2.py     # Gemini cross-check auditor (3. validációs szint)
├── axon_sandbox_v2.py     # Statikus szűrő + subprocess sandbox (1-2. szint)
├── axon_compaction.py     # Conversation history tömörítés
├── axon_context.py        # Pipeline context builder
├── axon_retry.py          # API retry wrapper
├── axon_watchman.py       # Rendszer monitoring (CPU/RAM/disk)
├── tests/
│   ├── test_pipeline.py   # core/pipeline.py unit tesztek (pytest + asyncio)
│   ├── test_models.py     # models.py unit tesztek
│   ├── test_handlers.py   # bot/handlers.py tesztek
│   ├── test_commands.py   # bot/commands.py tesztek
│   └── test_router.py     # bot/router.py tesztek
├── outputs/               # Generált .py + README.md fájlok
├── souls/                 # Pipeline system promptok (.md fájlok)
└── portfolio/             # Portfolio projektek (nem az AXON kódja)
```

---

## 4 Pipeline architektúra

| Pipeline | Trigger | Logika | Validáció |
|----------|---------|--------|-----------|
| **DEVELOPER** | Python kód kérés | CodeGenerator → Sandbox → AuditFixLoop → File | 3 szint: statikus szűrő + unit test + Gemini |
| **PLANNER** | Terv, dokumentáció | Claude direct | Cache + History |
| **CREATIVE** | Cover letter, szöveg | Claude direct | Nincs cache, nincs history |
| **ANALYST** | Adatelemzés | Claude direct | Cache + History |

---

## DEVELOPER pipeline részletes flow

```
Task → [Cache check] → Few-shot context → History context
  → estimate_complexity() → SIMPLE (2 session) vagy COMPLEX (4 session)
  → [Risk keyword filter] → Sandbox validate_with_retry()
  → Gemini audit → [AuditFixLoop: max 2 kör]
  → OutputWriter (fájl + README) → CostAccumulator → PipelineResult
```

**Session count:**
- SIMPLE: S1 (kód) + S2 (tesztek) = 2 Claude hívás
- COMPLEX: S1 (1. rész) + S2 (2. rész) + S3a (összefűzés) + S3b (tesztek) = 4 Claude hívás
- Fix loop: +2 Claude hívás /kör (max 2 kör) = max +4

---

## Kulcsdependenciák és típusok

```python
# models.py — ezekből minden import jön
from models import (
    Task, Pipeline, TaskComplexity,
    SandboxResult, AuditResult, AuditVerdict,
    PipelineResult, GenerationResult,
    HistoryTurn, CostEntry, TrainingSample, FixSample,
    RouteDecision, SystemStatus,
)

# StatusCallback — pipeline → Telegram state
StatusCallback = Callable[[str], Awaitable[None]]
```

---

## Kód konvenciók

- **Dependency injection:** minden függőség konstruktorban, nincs globális state (kivéve `AppContext._task_tokens`)
- **Async:** asyncio + `run_in_executor` a szinkron Claude hívásokhoz
- **Logging:** `log = logging.getLogger("AXON.<Modul>")` — minden fájlban saját logger
- **Pydantic v2:** `model_copy(update={...})`, `field_validator`, `model_validator`
- **Path:** `pathlib.Path` mindenhol, nem `os.path`
- **Tesztek:** `pytest` + `pytest-asyncio`, `AsyncMock` Telegram/Claude mockhoz
- **Nyelv:** Magyar kommentek + docstringek, angol kód

---

## Ismétlődő feladatok és ajánlott megközelítések

### Code Review (`/review` parancs analógiájára)
```bash
# Fut a bot-on belül: /review
# Kézi audit: olvasd el a core/pipeline.py + az érintett modult
```

### Tesztek futtatása
```bash
# Alap teszt futtatás
cd C:\AXON_OPS\AxonV2
python -m pytest tests/ -v

# Csak pipeline tesztek
python -m pytest tests/test_pipeline.py -v

# Async tesztek
python -m pytest tests/ -v --asyncio-mode=auto
```

**Fontos:** `tests/test_pipeline.py` és `test_models.py` tartalmaz hardcoded Linux path-ot:
`sys.path.insert(0, "/home/claude/axon_v9")` — Windows rendszeren ez nem működik,
le kell cserélni: `sys.path.insert(0, str(Path(__file__).parent.parent))`

### Bot indítás
```bash
cd C:\AXON_OPS\AxonV2
python main.py
```

### Új pipeline prompt testreszabás
A `souls/` mappában: `developer.md`, `planner.md`, `creative.md`, `analyst.md`
Ha nem létezik, a hardcoded fallback az `AppContext._load_pipeline_prompts()`-ban lép életbe.

---

## Ismert technikai adósságok és figyelmeztetések

1. **`_extract_code_block` kontrakt mismatch** — az implementáció `""` vagy `text.strip()`-et ad vissza,
   de a tesztek `None`-t várnak. Ez a tesztek egy részét törné ha valóban futnának.

2. **Timestamp mismatch** — `OutputWriter.write()` saját timestamp-et generál, a `DeveloperPipeline.run()`
   egy másikat a README-hez → a .py fájl neve és a README neve eltérő timestampet kaphat.

3. **`axon_main()`** — dead code a `main.py`-ban, eltávolítandó.

4. **`asyncio.get_event_loop()`** a `AppContext.system_running()`-ban — Python 3.10+ deprecated.

5. **`SANDBOX_MAX_RETRIES = 3`** a `pipeline.py`-ban — ez az érték SOHA nem kontrollálja ténylegesen
   a sandbox retry-okat (azt az `AxonSandbox.validate_with_retry` végzi), csak az error üzenetben jelenik meg.

6. **`_task_tokens` class variable** — a `main.py`-ban class-szintű dict, nem instance-szintű.

---

## Skill definíciók ehhez a projekthez

### Code Review
Amikor pipeline.py, handlers.py, vagy más core modul változik:
- Ellenőrizd: StatusCallback típus helyes-e
- Ellenőrizd: PipelineResult mezők mind kitöltve-e
- Ellenőrizd: async/await konzisztencia
- Futtasd: `python -m pytest tests/test_pipeline.py -v`

### Refactor
- A `models.py` a single source of truth — ne duplikálj típusokat
- DeveloperPipeline konstruktorba ne adj több paramétert — helyette dict/dataclass
- Lazy import (`import json` függvény belsejében) kerülendő

### Test generálás
- `pytest` + `pytest-asyncio` + `AsyncMock` a standard
- Minden async teszt: `@pytest.mark.asyncio`
- Telegram Update/Context: mindig mock, soha valódi PTB objektum
- Teszt fájl eleje: `sys.path.insert(0, str(Path(__file__).parent.parent))`

### Dokumentáció
- Magyar docstringek az AXON-specifikus logikához
- Modul szintű docstring: osztályok listája + verzió

### Pipeline bővítés (új pipeline hozzáadása)
1. `models.py` → `Pipeline` enum bővítése
2. `bot/router.py` → `_KEYWORD_RULES` bővítése
3. `bot/handlers.py` → `PIPELINE_META` bővítése
4. `main.py` → handler regisztráció + pipeline_prompts
5. `souls/` → új pipeline `.md` system prompt

---

## Környezeti változók (`.env`)

```
TELEGRAM_TOKEN=...
ANTHROPIC_KEY=...
GEMINI_KEY=...
```

Hiányzó változó esetén `Config.from_env()` `ValueError`-t dob és a bot nem indul el.
