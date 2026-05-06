"""
AXON Neural Bridge — Application Entry Point
=============================================
v9.0

Ez a fájl az egyetlen "composition root":
  - Minden dependency itt jön létre (egyszer)
  - Minden modul innen kapja a függőségeit (injection)
  - Lifecycle itt van kezelve (init → run → shutdown)

Nincs globális változó. Nincs implicit dependency.
Ha tesztelni kell: AppContext mock-kal cserélhető.

Struktúra:
  Config          – .env → typed config
  AppContext      – minden dependency egy helyen
  axon_main()     – async belépési pont
  main()          – sync wrapper
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler,
    CommandHandler, ConversationHandler,
    MessageHandler, filters,
)

# ── AXON modulok ─────────────────────────────────────────────
from models import Pipeline

# Core
from core.pipeline import (
    AuditFixLoop, CodeGenerator, CostAccumulator,
    DeveloperPipeline, OutputWriter,
)

# Bot
from bot.approvals import handle_approval_callback
from bot.commands import CommandHandlers, CommandRegistry, UPWORK_JOB, UPWORK_BUDGET
from bot.handlers import SimplePipelineRunner, TaskHandler, TelegramSender
from bot.router import PipelineRouter

# Legacy modulok (még nem refaktorált, de izoláltan importálva)
from axon_memory import (
    add_to_history, clear_history, get_cached_response,
    get_cache_stats, get_cost_stats, get_history,
    get_history_summary, get_history_turn_count,
    get_last_code, get_relevant_few_shot_samples,
    get_stats, get_successful_patterns,
    format_cache_stats_message, format_cost_stats_message,
    format_stats_message, init_db,
    log_task_cost, persist_history, purge_expired_cache, purge_all_cache,
    restore_history, save_cached_response, save_fix_sample,
    save_training_sample, was_timeout_cleared,
    increment_review_count,
)
from axon_auditor_v2 import AxonAuditor
from axon_compaction import compact_history, format_compact_report
from axon_context import get_context_for_pipeline
from axon_retry import call_with_retry as with_retry
from axon_sandbox_v2 import AxonSandbox, format_sandbox_report
from axon_watchman import AxonWatchman

log = logging.getLogger("AXON.Main")

# ── AXON verzió ───────────────────────────────────────────────
AXON_VERSION = "v9.0"
RISK_KEYWORDS = [
    "os.system", "subprocess", "shutil.rmtree", "__import__",
    "exec(", "eval(", "open('/", "rm -rf",
]


# ══════════════════════════════════════════════════════════════
#  CONFIG
#  .env → typed, validált konfiguráció
# ══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Config:
    """
    Immutable konfiguráció — induláskor egyszer töltődik be.
    frozen=True: senki sem módosíthatja futás közben.
    """
    telegram_token:   str
    anthropic_key:    str
    gemini_key:       str
    base_dir:         Path
    output_dir:       Path
    uploads_dir:      Path
    souls_dir:        Path
    db_path:          Path

    @classmethod
    def from_env(cls, base_dir: Path) -> Config:
        """
        .env fájlból tölti be a konfigurációt.
        Hiányzó kötelező értéknél ValueError-t dob — nem indul el a bot.
        """
        def require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise ValueError(
                    f"Hiányzó kötelező környezeti változó: {key}\n"
                    f"Ellenőrizd a .env fájlt!"
                )
            return val

        return cls(
            telegram_token = require("TELEGRAM_TOKEN"),
            anthropic_key  = require("ANTHROPIC_KEY"),
            gemini_key     = require("GEMINI_KEY"),
            base_dir       = base_dir,
            output_dir     = base_dir / "outputs",
            uploads_dir    = base_dir / "uploads",
            souls_dir      = base_dir / "souls",
            db_path        = base_dir / "axon.db",
        )


# ══════════════════════════════════════════════════════════════
#  APP STATE
#  Egyetlen mutable state objektum — nem globális változók
# ══════════════════════════════════════════════════════════════

@dataclass
class AppState:
    running:      bool = True
    owner_chat_id: int | None = None


# ══════════════════════════════════════════════════════════════
#  APP CONTEXT
#  Minden dependency egy helyen, egyszer példányosítva
# ══════════════════════════════════════════════════════════════

class AppContext:
    """
    Composition root — minden dependency itt jön létre.

    Nincs globális változó. A handlerek, pipeline-ok és
    commandok innen kapják a függőségeiket.

    Lifecycle:
      ctx = AppContext(config)
      await ctx.initialize()   # DB init, history restore
      # ... fut a bot ...
      await ctx.shutdown()     # graceful leállás
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state  = AppState()

        # ── Claude client ────────────────────────────────────
        import anthropic
        self._anthropic = anthropic.Anthropic(api_key=config.anthropic_key)

        # ── Gemini auditor ───────────────────────────────────
        self.auditor = AxonAuditor(gemini_api_key=config.gemini_key)

        # ── Sandbox ──────────────────────────────────────────
        self.sandbox = AxonSandbox()

        # ── Soul loader (pipeline promptok) ──────────────────
        self.pipeline_prompts = self._load_pipeline_prompts()

        # ── Dirs létrehozása ─────────────────────────────────
        config.output_dir.mkdir(parents=True, exist_ok=True)
        config.uploads_dir.mkdir(parents=True, exist_ok=True)

    # ── Claude hívó függvények ────────────────────────────────

    def _claude_call_sync(self, system: str, user_msg: str, max_tokens: int = 4000) -> str:
        """Sync Claude hívás — executor-ban fut."""
        resp = self._anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text

    async def call_claude(self, system: str, user_msg: str, max_tokens: int = 4000) -> str:
        """Async Claude hívás retry-jal."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: with_retry(lambda: self._claude_call_sync(system, user_msg, max_tokens))
        )

    async def call_claude_tracked(
        self, system: str, user_msg: str, max_tokens: int, chat_id: str
    ) -> str:
        """Token-tracking Claude hívás a DEVELOPER pipeline-hoz."""
        loop = asyncio.get_running_loop()

        def _tracked():
            resp = self._anthropic.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            self._accumulate_tokens(
                chat_id, resp.usage.input_tokens, resp.usage.output_tokens
            )
            return resp.content[0].text

        return await loop.run_in_executor(
            None, lambda: with_retry(_tracked)
        )

    async def call_claude_with_history(
        self, system: str, messages: list[dict], max_tokens: int = 4000
    ) -> str:
        """Multi-turn Claude hívás history-val."""
        loop = asyncio.get_running_loop()

        def _with_history():
            resp = self._anthropic.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return resp.content[0].text

        return await loop.run_in_executor(
            None, lambda: with_retry(_with_history)
        )

    # ── Token akkumulátor (v8.x kompatibilis) ────────────────

    _task_tokens: dict = {}

    def _accumulate_tokens(self, chat_id: str, inp: int, out: int) -> None:
        if chat_id not in self._task_tokens:
            self._task_tokens[chat_id] = {"input": 0, "output": 0, "calls": 0}
        self._task_tokens[chat_id]["input"]  += inp
        self._task_tokens[chat_id]["output"] += out
        self._task_tokens[chat_id]["calls"]  += 1

    def pop_tokens(self, chat_id: str) -> dict:
        return self._task_tokens.pop(chat_id, {"input": 0, "output": 0, "calls": 0})

    @staticmethod
    def tokens_to_usd(inp: int, out: int) -> float:
        return (inp * 3.0 + out * 15.0) / 1_000_000

    # ── Soul loader ───────────────────────────────────────────

    def _load_pipeline_prompts(self) -> dict[str, str]:
        """souls/ mappából tölti be a pipeline promptokat, fallback: hardcoded."""
        hardcoded = {
            "DEVELOPER": (
                "Senior Python fejlesztő vagy, 10+ év tapasztalattal production rendszereken. "
                "Upwork-ön $200-300 értékű feladatokat oldasz meg, ezért enterprise szintű kódot írsz.\n"
                "KÖTELEZŐ ELVEK:\n"
                "1. Teljes, futtatható kód – soha nem csonkítasz\n"
                "2. Strukturált error handling – minden I/O try/except blokkban\n"
                "3. Logging – logging modul, ne print()\n"
                "4. Type hints – minden függvény annotált\n"
                "5. Konfigurálhatóság – env változók, ne hardcode\n"
                "6. Docstring – minden publikus függvényhez\n"
                "7. Edge case-ek – üres lista, None, encoding, timeout kezelve\n"
                "8. Clean kód – DRY, max 50 sor / függvény"
            ),
            "PLANNER": (
                "Tapasztalt szoftver architect és projekt menedzser vagy. "
                "Strukturált, részletes terveket, fejlesztési ütemterveket, sprint terveket készítesz. "
                "Markdown formátumban dolgozol: fejlécek, listák, prioritások. "
                "Válaszolj magyarul."
            ),
            "CREATIVE": (
                "Profi szövegíró és kommunikációs szakértő vagy. "
                "Cover lettereket, emaileket, hirdetéseket, prezentációkat írsz. "
                "Stílusod: professzionális de személyes, konkrét, nem általánoskodó. "
                "Minden szöveg egyedi és személyre szabott."
            ),
            "ANALYST": (
                "Adatelemző és üzleti stratéga vagy. "
                "Számokat, trendeket, piaci adatokat elemzel. "
                "Strukturált, pontos válaszokat adsz táblázatokkal és összefoglalókkal ahol releváns. "
                "Válaszolj magyarul."
            ),
        }

        prompts = {}
        for pipeline, fallback in hardcoded.items():
            soul_path = self.config.souls_dir / f"{pipeline.lower()}.md"
            try:
                content = soul_path.read_text(encoding="utf-8").strip()
                if content:
                    prompts[pipeline] = content
                    log.info(f"[SOUL] Betöltve: {soul_path.name} ({len(content)} kar)")
                    continue
            except FileNotFoundError:
                pass
            except Exception as e:
                log.warning(f"[SOUL] Olvasási hiba ({soul_path}): {e}")
            prompts[pipeline] = fallback
            log.debug(f"[SOUL] Fallback: {pipeline}")

        return prompts

    # ── State accessors ───────────────────────────────────────

    def get_running(self) -> bool:
        return self.state.running

    def set_running(self, value: bool) -> None:
        self.state.running = value

    def get_owner_id(self) -> int | None:
        return self.state.owner_chat_id

    def is_owner(self, update) -> bool:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if self.state.owner_chat_id is None:
            self.state.owner_chat_id = chat_id
            self._persist_owner(chat_id)
            log.info(f"[AUTH] Owner regisztrálva: {chat_id}")
            return True
        return chat_id == self.state.owner_chat_id

    def system_running(self, update) -> bool:
        if not self.state.running:
            asyncio.get_event_loop().create_task(
                update.message.reply_text(
                    "⛔ *AXON leállítva.* Újraindítás: `/start`",
                    parse_mode="Markdown",
                )
            )
        return self.state.running

    def _persist_owner(self, chat_id: int) -> None:
        """Owner ID mentése DB-be (v8.x kompatibilis)."""
        try:
            import sqlite3
            db = sqlite3.connect(str(self.config.db_path))
            db.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('owner_chat_id', ?)",
                (str(chat_id),)
            )
            db.commit()
            db.close()
        except Exception as e:
            log.error(f"[AUTH] Owner mentési hiba: {e}")

    # ── Lifecycle ─────────────────────────────────────────────

    async def initialize(self) -> None:
        """DB init, history restore, owner betöltés."""
        init_db()
        log.info("[INIT] DB inicializálva")

        # Owner visszatöltés
        try:
            import sqlite3
            db = sqlite3.connect(str(self.config.db_path))
            row = db.execute(
                "SELECT value FROM config WHERE key='owner_chat_id'"
            ).fetchone()
            db.close()
            if row:
                self.state.owner_chat_id = int(row[0])
                log.info(f"[INIT] Owner visszatöltve: {self.state.owner_chat_id}")
        except Exception as e:
            log.warning(f"[INIT] Owner betöltési hiba: {e}")

    async def shutdown(self) -> None:
        """Graceful leállás — history persistence."""
        log.info("[SHUTDOWN] AXON leáll...")
        try:
            from axon_memory import get_history_turn_count
            if self.state.owner_chat_id:
                chat_id = str(self.state.owner_chat_id)
                if get_history_turn_count(chat_id) > 0:
                    persist_history(chat_id)
                    log.info("[SHUTDOWN] History perzisztálva")
        except Exception as e:
            log.warning(f"[SHUTDOWN] History persist hiba: {e}")

    # ── Pipeline builder ──────────────────────────────────────

    def build_developer_pipeline(self) -> DeveloperPipeline:
        """DeveloperPipeline összerakása — dependency injection."""
        generator = CodeGenerator(
            call_claude_tracked=self.call_claude_tracked,
            pipeline_prompt=self.pipeline_prompts.get("DEVELOPER", ""),
        )
        fix_loop = AuditFixLoop(
            call_claude=self.call_claude,
            sandbox=self.sandbox,
            auditor=self.auditor,
            save_fix_sample=save_fix_sample,
            format_audit_for_fix=self._format_audit_for_fix,
        )
        writer = OutputWriter(
            output_dir=self.config.output_dir,
            generate_readme_fn=self._generate_readme,
        )
        cost = CostAccumulator(
            pop_tokens_fn=self.pop_tokens,
            tokens_to_usd_fn=self.tokens_to_usd,
            log_cost_fn=log_task_cost,
        )
        return DeveloperPipeline(
            generator=generator,
            fix_loop=fix_loop,
            writer=writer,
            cost=cost,
            sandbox=self.sandbox,
            auditor=self.auditor,
            get_cached_response=get_cached_response,
            save_cached_response=save_cached_response,
            get_history_turn_count=get_history_turn_count,
            get_last_code=get_last_code,
            add_to_history=add_to_history,
            save_training_sample=save_training_sample,
            get_successful_patterns=get_successful_patterns,
            get_relevant_few_shot=get_relevant_few_shot_samples,
            ai_fix_callback=self._ai_fix_callback,
            format_sandbox_report=format_sandbox_report,
            risk_keywords=RISK_KEYWORDS,
        )

    def build_simple_runner(self) -> SimplePipelineRunner:
        return SimplePipelineRunner(
            call_claude_tracked=self.call_claude_tracked,
            call_claude_with_history=self.call_claude_with_history,
            pipeline_prompts=self.pipeline_prompts,
            get_cached_response=get_cached_response,
            save_cached_response=save_cached_response,
            get_history=get_history,
            add_to_history=add_to_history,
            save_training_sample=save_training_sample,
            pop_tokens_fn=self.pop_tokens,
            tokens_to_usd_fn=self.tokens_to_usd,
            log_cost_fn=log_task_cost,
            no_cache_pipelines={Pipeline.CREATIVE},
            history_enabled_pipelines={Pipeline.PLANNER, Pipeline.ANALYST},
        )

    def build_router(self) -> PipelineRouter:
        return PipelineRouter(call_claude_fn=self.call_claude)

    def build_command_registry(self, auditor) -> CommandRegistry:
        return CommandRegistry(
            get_running_fn=self.get_running,
            set_running_fn=self.set_running,
            get_owner_id_fn=self.get_owner_id,
            is_owner_fn=self.is_owner,
            system_running_fn=self.system_running,
            get_history_fn=get_history,
            get_history_turn_count=get_history_turn_count,
            get_history_summary=get_history_summary,
            clear_history_fn=clear_history,
            add_to_history_fn=add_to_history,
            get_last_code_fn=get_last_code,
            get_stats_fn=get_stats,
            get_cache_stats_fn=get_cache_stats,
            get_cost_stats_fn=get_cost_stats,
            format_stats_fn=format_stats_message,
            format_cache_stats_fn=format_cache_stats_message,
            format_cost_stats_fn=format_cost_stats_message,
            purge_cache_fn=purge_all_cache,
            increment_review_fn=increment_review_count,
            compact_history_fn=compact_history,
            format_compact_report_fn=format_compact_report,
            call_claude_sync_fn=self._claude_call_sync,
            call_claude_fn=self.call_claude,
            pipeline_prompts=self.pipeline_prompts,
            auditor=auditor,
            bypass_runner=self.call_claude,
            upwork_system_prompt=self._upwork_system_prompt(),
            call_claude_upwork_fn=self.call_claude,
            output_dir=self.config.output_dir,
        )

    # ── Belső helper függvények ───────────────────────────────

    async def _ai_fix_callback(self, fix_prompt: str) -> str:
        """Sandbox fix callback — Claude javítja a hibás kódot."""
        return await self.call_claude(
            system="Senior Python fejlesztő vagy. Javítsd a megadott kódot. "
                   "Adj vissza teljes, futtatható kódot ```python blokkban.",
            user_msg=fix_prompt,
        )

    @staticmethod
    def _format_audit_for_fix(audit_result, validated_code: str, task: str) -> str:
        """Gemini audit FAIL → Claude fix prompt."""
        from axon_auditor_v2 import format_audit_for_fix_prompt
        return format_audit_for_fix_prompt(audit_result, validated_code, task)

    async def _generate_readme(self, **kwargs) -> str:
        """
        README.md generálás a kész kódhoz.
        Claude-dal generált, a kód mellé mentett dokumentáció.
        """
        try:
            task       = kwargs.get("task", "")
            main_code  = kwargs.get("main_code", "")
            filename   = kwargs.get("filename", "output.py")
            output_dir = kwargs.get("output_dir", str(self.config.output_dir))
            timestamp  = kwargs.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
            safe_task  = kwargs.get("safe_task", "task")
            audit_result   = kwargs.get("audit_result")
            sandbox_result = kwargs.get("sandbox_result")

            audit_str = ""
            if audit_result:
                audit_str = f"Gemini: {audit_result.verdict.value} ({audit_result.score}/100)"

            sandbox_str = ""
            if sandbox_result:
                sandbox_str = (
                    f"Sandbox: {'PASS' if sandbox_result.success else 'FAIL'} | "
                    f"Tesztek: {getattr(sandbox_result, 'tests_passed', 0)}/"
                    f"{getattr(sandbox_result, 'tests_total', 0)}"
                )

            readme_prompt = (
                f"Feladat: {task}\n\n"
                f"Kód ({len(main_code.splitlines())} sor):\n"
                f"```python\n{main_code[:2000]}\n```\n\n"
                "Írj egy rövid README.md-t ehhez a Python scripthez.\n"
                "Tartalmazza: Mit csinál, Hogyan futtatható, Függőségek (ha vannak).\n"
                "Max 20 sor, markdown formátum."
            )

            readme_content = await self.call_claude(
                system="Technikai dokumentáció írója vagy. Rövid, pontos README-ket írsz.",
                user_msg=readme_prompt,
                max_tokens=500,
            )

            readme_path = (
                Path(output_dir) /
                f"{timestamp}_{safe_task}_README.md"
            )
            readme_path.write_text(
                f"# {filename}\n\n"
                f"**Generálva:** {timestamp}\n"
                f"**{sandbox_str}** | **{audit_str}**\n\n"
                f"{readme_content}",
                encoding="utf-8",
            )
            log.info(f"[README] Generálva: {readme_path.name}")
            return f"📄 `{readme_path.name}`"

        except Exception as e:
            log.warning(f"[README] Generálás hiba: {e}")
            return ""

    @staticmethod
    def _upwork_system_prompt() -> str:
        return (
            "Te Kocsis Gábor vagy, Budapest. Nappal villamos elosztó tábla szerelő "
            "csoportvezető, szabadidőben Python fejlesztő és automatizálás specialista.\n\n"
            "VALÓS HÁTTÉR:\n"
            "- Python automatizálás, Telegram bot (AXON), n8n, Make.com\n"
            "- SQLite, CSV/JSON, Claude API, Gemini API\n"
            "- Logistics & Supply Chain Automation niche\n\n"
            "TILOS: kitalált referencia, 'I would love to', bulletpoint lista\n"
            "HANGNEM: rövid, tömör, technikai, magabiztos, max 130 szó"
        )


# ══════════════════════════════════════════════════════════════
#  LOGGING SETUP
#  Strukturált, request_id-vel gazdagított log formátum
# ══════════════════════════════════════════════════════════════

def setup_logging() -> None:
    """
    Strukturált logging setup.
    Minden log sor tartalmaz timestamp-et, level-t és modult.
    Production-ban JSON formátumra cserélhető.
    """
    fmt = "%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # PTB és httpx logokat lecsöndesítjük
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════════
#  WATCHMAN JOB
# ══════════════════════════════════════════════════════════════

def build_watchman_job(ctx: AppContext) -> tuple:
    """
    Watchman JobQueue job factory.
    Returns: (job_fn, owner_getter) — a post_init-ben regisztrálva.
    """
    async def send_alert(msg: str) -> None:
        owner = ctx.state.owner_chat_id
        if owner:
            # Az application objektum a post_init-ből jön
            pass  # a job_fn closure-ban kezeljük

    watchman = AxonWatchman(alert_callback=send_alert)
    return watchman


# ══════════════════════════════════════════════════════════════
#  AXON MAIN
# ══════════════════════════════════════════════════════════════

def main() -> None:
    """
    Belépési pont — PTB-native asyncio kezelés.

    Python 3.10 + PTB: NEM szabad asyncio.run() + run_polling() kombinációt
    használni — a PTB run_polling() maga kezeli az event loop-ot.

    Minden async init a post_init callback-ben történik.
    """
    setup_logging()

    base_dir = Path(__file__).parent
    load_dotenv(dotenv_path=base_dir / ".env")

    try:
        config = Config.from_env(base_dir)
    except ValueError as e:
        log.critical(f"Konfiguráció hiba: {e}")
        sys.exit(1)

    # AppContext szinkron része (soul loader, dirs)
    ctx = AppContext(config)

    # DB init + owner betöltés szinkron
    import sqlite3
    init_db()
    log.info("[INIT] DB inicializálva")
    purged = purge_expired_cache()
    if purged:
        log.info(f"[INIT] Cache TTL cleanup: {purged} lejárt bejegyzés törölve")
    try:
        db = sqlite3.connect(str(config.db_path))
        row = db.execute("SELECT value FROM config WHERE key='owner_chat_id'").fetchone()
        db.close()
        if row:
            ctx.state.owner_chat_id = int(row[0])
            log.info(f"[INIT] Owner visszatöltve: {ctx.state.owner_chat_id}")
    except Exception as e:
        log.warning(f"[INIT] Owner betöltési hiba: {e}")

    # Pipeline-ok összerakása (szinkron)
    dev_pipeline  = ctx.build_developer_pipeline()
    simple_runner = ctx.build_simple_runner()
    router        = ctx.build_router()
    cmd_registry  = ctx.build_command_registry(ctx.auditor)
    cmd_handlers  = CommandHandlers(cmd_registry)

    task_handler = TaskHandler(
        developer_pipeline=dev_pipeline,
        simple_pipeline_runner=simple_runner.run,
        detect_pipeline_fn=router.route,
        is_owner_fn=ctx.is_owner,
        system_running_fn=ctx.system_running,
        was_timeout_cleared_fn=was_timeout_cleared,
        get_history_fn=get_history,
        get_history_turn_count_fn=get_history_turn_count,
        compact_history_fn=compact_history,
        call_claude_sync_fn=ctx._claude_call_sync,
        clear_history_fn=clear_history,
        add_to_history_fn=add_to_history,
        save_cached_response_fn=save_cached_response,
        output_dir=config.output_dir,
    )

    # Telegram Application
    app = ApplicationBuilder().token(config.telegram_token).build()

    # Handler regisztráció
    upwork_wizard = ConversationHandler(
        entry_points=[CommandHandler("upwork", cmd_handlers.upwork_start)],
        states={
            UPWORK_JOB: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.upwork_got_job),
            ],
            UPWORK_BUDGET: [
                CommandHandler("skip", cmd_handlers.upwork_skip_budget),
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.upwork_got_budget),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_handlers.upwork_cancel)],
        conversation_timeout=300,
    )

    app.add_handler(upwork_wizard)
    app.add_handler(CommandHandler("start",       cmd_handlers.start))
    app.add_handler(CommandHandler("help",        cmd_handlers.help_cmd))
    app.add_handler(CommandHandler("status",      cmd_handlers.status_cmd))
    app.add_handler(CommandHandler("stats",       cmd_handlers.stats_cmd))
    app.add_handler(CommandHandler("stop",        cmd_handlers.stop_cmd))
    app.add_handler(CommandHandler("bypass",      cmd_handlers.bypass_cmd))
    app.add_handler(CommandHandler("cache_clear", cmd_handlers.cache_clear_cmd))
    app.add_handler(CommandHandler("clear",       cmd_handlers.clear_cmd))
    app.add_handler(CommandHandler("history",     cmd_handlers.history_cmd))
    app.add_handler(CommandHandler("compact",     cmd_handlers.compact_cmd))
    app.add_handler(CommandHandler("review",      cmd_handlers.review_cmd))
    app.add_handler(CommandHandler("files",       cmd_handlers.files_cmd))
    app.add_handler(CallbackQueryHandler(handle_approval_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, task_handler.handle))

    # post_init — async inicializálás a PTB event loop-ján belül
    async def post_init(application) -> None:
        # History visszatöltés
        if ctx.state.owner_chat_id:
            restore_history(str(ctx.state.owner_chat_id))
            log.info(f"[INIT] History visszatöltve: {ctx.state.owner_chat_id}")

        # Watchman
        watchman = AxonWatchman(
            alert_callback=lambda msg: application.bot.send_message(
                chat_id=ctx.state.owner_chat_id,
                text=msg, parse_mode="Markdown",
            ) if ctx.state.owner_chat_id else None
        )

        async def watchman_job(job_context):
            await watchman._check_once()

        application.job_queue.run_repeating(
            watchman_job, interval=60, first=10, name="watchman",
        )

        log.info("═" * 55)
        log.info(f"  AXON Neural Bridge {AXON_VERSION} — ONLINE")
        log.info(f"  Output dir : {config.output_dir}")
        log.info(f"  DB         : {config.db_path}")
        log.info("═" * 55)

    app.post_init = post_init

    log.info("✅ Bot indul... (Ctrl+C a leállításhoz)")
    app.run_polling()


if __name__ == "__main__":
    main()
