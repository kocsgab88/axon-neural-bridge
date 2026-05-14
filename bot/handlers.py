#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AXON Neural Bridge — Telegram Handler Réteg
============================================

Copyright (c) 2026 Kocsis Gábor. All rights reserved.
Licensed under AXON Source Available License v1.0.

This file is part of AXON Neural Bridge.
See LICENSE.md for licensing terms.
Commercial use requires separate license: kocsgab88@gmail.com

---

v9.0

Ez a fájl KIZÁRÓLAG Telegram I/O-t végez:
  - Update fogadás
  - Státusz üzenetek küldése
  - PipelineResult → Telegram üzenet formázása
  - Hibakezelés és user feedback

Üzleti logika NEM kerülhet ide.
Minden pipeline hívás → DeveloperPipeline.run() vagy SimplePipeline.run()
Minden adat → PipelineResult modellből olvasva

Osztályok:
  TelegramSender     – safe_send, update_status, send_file (Telegram I/O primitívek)
  TaskHandler        – handle_task() orkesztrációja (routing, compact, timeout)
  PipelineFormatter  – PipelineResult → Telegram üzenet string
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Awaitable

from telegram import Update
from telegram.ext import ContextTypes

from models import AuditVerdict, Pipeline, PipelineResult, Task

log = logging.getLogger("AXON.Handlers")

# Státusz callback típus — pipeline-ok ezt kapják
StatusCallback = Callable[[str], Awaitable[None]]


# ══════════════════════════════════════════════════════════════
#  TELEGRAM SENDER
#  Felelőssége: minden Telegram I/O primitív egy helyen
# ══════════════════════════════════════════════════════════════

class TelegramSender:
    """
    Telegram üzenet küldés egységes helyen.
    Ha a Telegram API változik, csak ezt az osztályt kell módosítani.
    """

    @staticmethod
    async def safe_send(update: Update, text: str) -> None:
        """
        4000 karakteres chunking, Markdown fallback plain textre.
        Az eredeti safe_send() logika kivonva ide.
        """
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                clean = chunk.replace("*", "").replace("`", "").replace("_", "")
                await update.message.reply_text(clean)

    @staticmethod
    async def update_status(msg, text: str) -> None:
        """Állapot üzenet frissítése. Csendben elnyeli a hibát ha az üzenet törölve lett."""
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    @staticmethod
    async def delete_status(msg) -> None:
        """Státusz üzenet törlése pipeline befejezésekor."""
        try:
            await msg.delete()
        except Exception:
            pass

    @staticmethod
    async def send_file(update: Update, filepath: str, caption: str) -> None:
        """Fájl küldése Telegramon. Nem kritikus — hiba esetén csak logol."""
        try:
            with open(filepath, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=Path(filepath).name,
                    caption=caption,
                    parse_mode="Markdown",
                )
            log.info(f"[FILES] Auto fájlküldés: {Path(filepath).name}")
        except Exception as e:
            log.warning(f"[FILES] Fájlküldési hiba (nem kritikus): {e}")

    @staticmethod
    def make_status_callback(msg) -> StatusCallback:
        """
        Visszaad egy StatusCallback-et ami az adott status_msg-et frissíti.
        A pipeline-ok ezt kapják — nem tudnak a Telegram Update-ről.
        """
        async def _cb(text: str) -> None:
            await TelegramSender.update_status(msg, text)
        return _cb


# ══════════════════════════════════════════════════════════════
#  PIPELINE FORMATTER
#  Felelőssége: PipelineResult → Telegram üzenet string
# ══════════════════════════════════════════════════════════════

class PipelineFormatter:
    """
    A PipelineResult-ból Telegram-barát üzenetet épít.
    Tisztán formázási logika — nincs Telegram API hívás.
    """

    @staticmethod
    def format_developer_result(result: PipelineResult) -> str:
        """DEVELOPER pipeline végeredmény formázása."""
        if not result.success:
            return result.output

        if result.cache_hit:
            return f"⚡ *DEVELOPER* _(cache – sandbox+audit korábban PASS)_:\n\n{result.output}"

        # Sandbox összefoglaló
        sandbox_summary = ""
        if result.sandbox:
            s = result.sandbox
            icon = "✅" if s.success else "❌"
            sandbox_summary = (
                f"{icon} Sandbox: {'PASS' if s.success else 'FAIL'} "
                f"| Tesztek: {s.test_ratio} | {s.attempt}. próba"
            )

        # Audit sor
        audit_line = ""
        if result.audit:
            a = result.audit
            if a.verdict == AuditVerdict.SKIP:
                audit_line = "🔮 Gemini audit: kihagyva (API nem elérhető)"
            else:
                icon = "✅" if a.passed else "⚠️"
                audit_line = f"🔮 Gemini audit: {icon} {getattr(a.verdict, 'value', a.verdict)} ({a.score}/100)"

        # Fájl sor
        file_line    = f"📁 `{result.output_file}`"  if result.output_file  else ""
        readme_line  = result.readme_file             if result.readme_file  else ""

        # Multi-turn jelölő
        is_multiturn = result.task.text != result.output  # közelítő check
        multiturn_note = ""  # a handler tölti fel kontextus alapján

        header = (
            f"🎯 *DEVELOPER* válasza:\n"
            f"{sandbox_summary}\n"
            f"{audit_line}\n"
            f"{file_line}\n"
            f"{readme_line}\n"
        )

        # Fennmaradó Gemini megjegyzések
        if result.audit and not result.audit.passed and result.audit.verdict != AuditVerdict.SKIP:
            if result.audit.issues:
                header += "\n⚠️ *Fennmaradó megjegyzések:*\n"
                for issue in result.audit.issues[:2]:
                    header += f"• {issue}\n"

        # Kód preview (első 15 sor)
        lines         = result.output.splitlines()
        preview_lines = lines[:15]
        preview       = "\n".join(preview_lines)
        total_lines   = len(lines)
        if total_lines > 15:
            preview += f"\n# ... (+{total_lines - 15} sor)"

        # Cost sor
        cost_line = (
            f"💰 *Feladat költsége:* ${result.cost_usd:.4f} "
            f"_({result.tokens_in // 1000}k in / {result.tokens_out // 1000}k out"
            f" · {result.api_calls} hívás)_"
        )

        return header + f"\n```python\n{preview}\n```\n\n{cost_line}"

    @staticmethod
    def format_simple_result(result: PipelineResult) -> str:
        """PLANNER / CREATIVE / ANALYST pipeline végeredmény formázása."""
        if not result.success:
            return result.output

        icon, label = {
            Pipeline.PLANNER:  ("📋", "PLANNER"),
            Pipeline.CREATIVE: ("✍️", "CREATIVE"),
            Pipeline.ANALYST:  ("📊", "ANALYST"),
        }.get(result.pipeline, ("🤖", result.pipeline.value))

        cache_note = " _(cache)_" if result.cache_hit else ""

        cost_line = ""
        if result.cost_usd > 0:
            cost_line = (
                f"\n\n💰 ${result.cost_usd:.4f} "
                f"_({result.tokens_in // 1000}k in / {result.tokens_out // 1000}k out)_"
            )

        return f"{icon} *{label}*{cache_note}:\n\n{result.output}{cost_line}"

    @staticmethod
    def format_error(pipeline: Pipeline, error: Exception) -> str:
        return (
            f"❌ *Váratlan hiba* ({pipeline.value}):\n"
            f"`{str(error)[:300]}`\n\n"
            "Próbáld újra!"
        )

    @staticmethod
    def format_initial_status(
        pipeline: Pipeline,
        icon: str,
        label: str,
        is_multiturn: bool,
        turn_count: int,
        in_no_cache: bool,
    ) -> str:
        """A pipeline elindításakor megjelenő állapot üzenet."""
        validation_hint = "\n1️⃣ 2️⃣ 3️⃣ _3 szintű validáció aktív_" if pipeline == Pipeline.DEVELOPER else ""
        history_hint    = (
            f"\n🧠 _Multi-turn ({turn_count // 2} előző válasz kontextusban)_"
            if is_multiturn else ""
        )
        if in_no_cache:
            cache_hint = "\n_✍️ Egyedi generálás (nincs cache, nincs history)_"
        elif is_multiturn:
            cache_hint = "\n_🔗 Cache bypass (multi-turn session)_"
        else:
            cache_hint = "\n_⚡ Cache ellenőrzés..._"

        return (
            f"⏳ *Feldolgozás...* {icon} _{label} pipeline_"
            f"{validation_hint}{history_hint}{cache_hint}"
        )


# ══════════════════════════════════════════════════════════════
#  TASK HANDLER
#  Felelőssége: handle_task() orchestrációja
#  — session timeout, auto-compact, routing, pipeline hívás
# ══════════════════════════════════════════════════════════════

class TaskHandler:
    """
    A Telegram handle_task() logikájának otthona.
    Dependency injection: minden függőség konstruktorban jön,
    így tesztelhetőés kicserélhető.
    """

    # Pipeline meta: ikon + label
    PIPELINE_META = {
        Pipeline.DEVELOPER: ("⚙️", "DEVELOPER"),
        Pipeline.PLANNER:   ("📋", "PLANNER"),
        Pipeline.CREATIVE:  ("✍️", "CREATIVE"),
        Pipeline.ANALYST:   ("📊", "ANALYST"),
    }

    NO_CACHE_PIPELINES    = {Pipeline.CREATIVE}
    HISTORY_ENABLED_PIPELINES = {Pipeline.DEVELOPER, Pipeline.PLANNER, Pipeline.ANALYST}

    def __init__(
        self,
        developer_pipeline,          # DeveloperPipeline instance
        simple_pipeline_runner,      # Callable: (pipeline, task, status_cb) → PipelineResult
        detect_pipeline_fn: Callable,
        is_owner_fn: Callable,
        system_running_fn: Callable,
        was_timeout_cleared_fn: Callable,
        get_history_fn: Callable,
        get_history_turn_count_fn: Callable,
        compact_history_fn: Callable,
        call_claude_sync_fn: Callable,
        clear_history_fn: Callable,
        add_to_history_fn: Callable,
        save_cached_response_fn: Callable,
        output_dir: Path,
    ) -> None:
        self._dev_pipeline        = developer_pipeline
        self._simple_runner       = simple_pipeline_runner
        self._detect_pipeline     = detect_pipeline_fn
        self._is_owner            = is_owner_fn
        self._system_running      = system_running_fn
        self._was_timeout_cleared = was_timeout_cleared_fn
        self._get_history         = get_history_fn
        self._turn_count          = get_history_turn_count_fn
        self._compact_history     = compact_history_fn
        self._call_claude_sync    = call_claude_sync_fn
        self._clear_history       = clear_history_fn
        self._add_to_history      = add_to_history_fn
        self._save_cached         = save_cached_response_fn
        self._output_dir          = output_dir

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Belépési pont: Telegram üzenet érkezésekor hívódik.
        1. Owner + running check
        2. Session timeout értesítő
        3. Auto-compact ha szükséges
        4. Pipeline routing
        5. Pipeline futtatás
        6. Eredmény küldése
        7. Auto fájlküldés ha sikeres DEVELOPER
        """
        if not self._is_owner(update) or not self._system_running(update):
            return

        task_text = update.message.text
        chat_id   = str(update.effective_chat.id)
        log.info(f"[HANDLER] Feladat: {task_text[:60]}...")

        # ── 1. Session timeout értesítő ──────────────────────
        if self._was_timeout_cleared(chat_id):
            await update.message.reply_text(
                "🔄 *Új session kezdődött* _(2 óra inaktivitás után)_\n"
                "Az előző conversation history törölve.",
                parse_mode="Markdown",
            )

        # ── 2. Auto-compact ───────────────────────────────────
        await self._maybe_compact(update, chat_id)

        # ── 3. Pipeline routing ───────────────────────────────
        # Task előre létrehozva — a router Task-ot vár (request_id, text)
        # Pipeline ideiglenesen DEVELOPER, routing után felülírjuk
        _temp_task   = Task(text=task_text, chat_id=chat_id, pipeline=Pipeline.DEVELOPER)
        route_decision = await self._detect_pipeline(_temp_task)

        # _detect_pipeline visszaadhat RouteDecision-t vagy stringet is
        if hasattr(route_decision, 'pipeline'):
            pipeline = route_decision.pipeline
        else:
            pipeline = Pipeline(route_decision)

        icon, label  = self.PIPELINE_META[pipeline]
        log.info(f"[ROUTER] Pipeline: {pipeline.value}")

        in_no_cache  = pipeline in self.NO_CACHE_PIPELINES
        use_history  = pipeline in self.HISTORY_ENABLED_PIPELINES
        turn_count   = self._turn_count(chat_id) if use_history else 0
        is_multiturn = use_history and turn_count > 0

        # ── 4. Státusz üzenet ────────────────────────────────
        status_msg = await update.message.reply_text(
            PipelineFormatter.format_initial_status(
                pipeline, icon, label, is_multiturn, turn_count, in_no_cache,
            ),
            parse_mode="Markdown",
        )

        status_cb = TelegramSender.make_status_callback(status_msg)

        # ── 5. Pipeline futtatás ──────────────────────────────
        try:
            task = Task(text=task_text, chat_id=chat_id, pipeline=pipeline)

            if pipeline == Pipeline.DEVELOPER:
                result = await self._dev_pipeline.run(
                    task=task,
                    status_cb=status_cb,
                    risk_approval=self._make_risk_approval(update),
                )
            else:
                result = await self._simple_runner(
                    pipeline=pipeline,
                    task=task,
                    status_cb=status_cb,
                )

        except Exception as e:
            await TelegramSender.delete_status(status_msg)
            await TelegramSender.safe_send(
                update, PipelineFormatter.format_error(pipeline, e)
            )
            log.error(f"[HANDLER] Hiba: {e}", exc_info=True)
            return

        # ── 6. Státusz törlése + eredmény küldése ────────────
        await TelegramSender.delete_status(status_msg)

        if pipeline == Pipeline.DEVELOPER:
            reply = PipelineFormatter.format_developer_result(result)
        else:
            reply = PipelineFormatter.format_simple_result(result)

        await TelegramSender.safe_send(update, reply)

        # ── 7. Cache mentés ha sikeres és friss session ───────
        if result.fully_passed and not is_multiturn and pipeline == Pipeline.DEVELOPER:
            self._save_cached("developer", task_text, reply)

        # ── 8. Auto fájlküldés sikeres DEVELOPER esetén ───────
        if (
            pipeline == Pipeline.DEVELOPER
            and result.fully_passed
            and result.output_file
        ):
            filepath = self._output_dir / result.output_file
            if filepath.exists():
                audit_info = ""
                if result.audit:
                    audit_info = f"Gemini {getattr(result.audit.verdict, 'value', result.audit.verdict)} ({result.audit.score}/100)"
                await TelegramSender.send_file(
                    update=update,
                    filepath=str(filepath),
                    caption=f"📎 *{result.output_file}*\n_Sandbox ✅ | {audit_info}_",
                )

    async def _maybe_compact(self, update: Update, chat_id: str) -> None:
        """Auto-compact ha a history meghaladja a 6000 karaktert."""
        history = self._get_history(chat_id)
        if not history:
            return

        history_size = sum(len(t.get("content", "")) for t in history)
        if history_size <= 6000:
            return

        log.info(f"[AUTO-COMPACT] History: {history_size} kar → tömörítés")
        loop           = asyncio.get_running_loop()
        compact_result = await loop.run_in_executor(
            None, self._compact_history, history, self._call_claude_sync, chat_id
        )

        if not compact_result.skipped:
            self._clear_history(chat_id)
            for turn in compact_result.new_history:
                self._add_to_history(
                    chat_id, turn["role"], turn["content"],
                    turn.get("pipeline", "DEVELOPER"),
                )
            await update.message.reply_text(
                f"🗜 _Auto-compact: history {compact_result.original_chars:,} → "
                f"{compact_result.new_chars:,} kar_",
                parse_mode="Markdown",
            )
            log.info(f"[AUTO-COMPACT] Kész: {compact_result.original_chars} → {compact_result.new_chars}")

    def _make_risk_approval(self, update: Update) -> Callable:
        """
        Visszaad egy risk approval callbacket ami az adott update-hez van kötve.
        A DeveloperPipeline ezt kapja — nem tud a Telegram Update-ről.
        """
        # Import itt, hogy elkerüljük a circular importot
        from bot.approvals import ask_risk_approval

        async def _approval(risks: list[str], task_id: str) -> bool:
            return await ask_risk_approval(update, risks, task_id)

        return _approval


# ══════════════════════════════════════════════════════════════
#  SIMPLE PIPELINE RUNNER
#  PLANNER / CREATIVE / ANALYST — nincs sandbox, nincs audit
# ══════════════════════════════════════════════════════════════

class SimplePipelineRunner:
    """
    A három nem-DEVELOPER pipeline orchestrátora.
    Sokkal egyszerűbb mint a DEVELOPER: Claude → output, kész.
    """

    def __init__(
        self,
        call_claude_tracked: Callable,
        call_claude_with_history: Callable,
        pipeline_prompts: dict,
        get_cached_response: Callable,
        save_cached_response: Callable,
        get_history: Callable,
        add_to_history: Callable,
        save_training_sample: Callable,
        pop_tokens_fn: Callable,
        tokens_to_usd_fn: Callable,
        log_cost_fn: Callable,
        no_cache_pipelines: set,
        history_enabled_pipelines: set,
    ) -> None:
        self._call_tracked       = call_claude_tracked
        self._call_with_history  = call_claude_with_history
        self._prompts            = pipeline_prompts
        self._get_cached         = get_cached_response
        self._save_cached        = save_cached_response
        self._get_history        = get_history
        self._add_history        = add_to_history
        self._save_training      = save_training_sample
        self._pop_tokens         = pop_tokens_fn
        self._to_usd             = tokens_to_usd_fn
        self._log_cost           = log_cost_fn
        self._no_cache           = no_cache_pipelines
        self._history_enabled    = history_enabled_pipelines

    async def run(
        self,
        pipeline: Pipeline,
        task: Task,
        status_cb: StatusCallback,
    ) -> PipelineResult:
        """PLANNER / CREATIVE / ANALYST futtatása."""
        icon, label = {
            Pipeline.PLANNER:  ("📋", "PLANNER"),
            Pipeline.CREATIVE: ("✍️", "CREATIVE"),
            Pipeline.ANALYST:  ("📊", "ANALYST"),
        }.get(pipeline, ("🤖", pipeline.value))

        in_no_cache = pipeline in self._no_cache
        use_history = pipeline in self._history_enabled

        # Cache check (CREATIVE soha nem cached)
        if not in_no_cache:
            cached = self._get_cached(pipeline.value.lower(), task.text)
            if cached:
                log.info(f"[{pipeline.value}] Cache HIT")
                return PipelineResult(
                    task=task, pipeline=pipeline,
                    success=True, output=cached, cache_hit=True,
                )

        await status_cb(f"⏳ *{icon} {label} pipeline fut...*")

        # History-aware generálás
        system_prompt = self._prompts.get(pipeline.value, "")
        if use_history:
            history = self._get_history(task.chat_id)
            if history:
                response = await self._call_with_history(
                    system=system_prompt,
                    messages=history + [{"role": "user", "content": task.text}],
                    max_tokens=4000,
                )
            else:
                response = await self._call_tracked(
                    system_prompt, task.text,
                    max_tokens=4000, chat_id=task.chat_id,
                )
        else:
            response = await self._call_tracked(
                system_prompt, task.text,
                max_tokens=4000, chat_id=task.chat_id,
            )

        # Token + cost
        tokens   = self._pop_tokens(task.chat_id)
        cost_usd = self._to_usd(tokens["input"], tokens["output"])
        self._log_cost(
            task=task.text, input_tokens=tokens["input"],
            output_tokens=tokens["output"], cost_usd=cost_usd, calls=tokens["calls"],
        )

        # History mentés (CREATIVE-nél nem)
        if use_history:
            self._add_history(task.chat_id, "user",      task.text, pipeline.value)
            self._add_history(task.chat_id, "assistant", response,  pipeline.value)

        # Training data
        self._save_training(
            expert_mode=pipeline.value.lower(),
            prompt=task.text,
            generated_code=response,
            success=True,
        )

        # Cache mentés
        if not in_no_cache:
            self._save_cached(pipeline.value.lower(), task.text, response)

        return PipelineResult(
            task=task, pipeline=pipeline,
            success=True, output=response,
            cost_usd=cost_usd,
            tokens_in=tokens["input"],
            tokens_out=tokens["output"],
            api_calls=tokens["calls"],
        )
