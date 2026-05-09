#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AXON Neural Bridge — Command Handlers
=======================================

Copyright (c) 2026 Kocsis Gábor. All rights reserved.
Licensed under AXON Source Available License v1.0.

This file is part of AXON Neural Bridge.
See LICENSE.md for licensing terms.
Commercial use requires separate license: kocsgab88@gmail.com

---

v9.0

Minden Telegram slash command handler egy helyen.
Minden handler: owner check → logika → reply. Max 20 sor egyenként.
Üzleti logika NEM kerülhet ide — csak memory/stats függvények hívása
és Telegram válasz formázása.

Handlerek:
  start, help_cmd, status_cmd, stats_cmd,
  cache_clear_cmd, clear_cmd, history_cmd,
  compact_cmd, stop_cmd, review_cmd,
  files_cmd, bypass_cmd,
  upwork_start, upwork_got_job, upwork_got_budget,
  upwork_skip_budget, upwork_cancel
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers import TelegramSender
from models import Pipeline

log = logging.getLogger("AXON.Commands")

# ConversationHandler state-ek az /upwork wizard-hoz
UPWORK_JOB, UPWORK_BUDGET = range(2)

# Jelenlegi AXON verzió — egy helyen, hogy ne kelljen több fájlban frissíteni
AXON_VERSION = "v9.0"


# ══════════════════════════════════════════════════════════════
#  COMMAND REGISTRY
#  Dependency injection: a bot indításakor töltjük fel
# ══════════════════════════════════════════════════════════════

class CommandRegistry:
    """
    Minden command handler függősége egy helyen.
    A main() létrehozza, átadja az egyes handlereknek.
    Így a handlerek tesztelhetők mock függőségekkel.
    """

    def __init__(
        self,
        # State
        get_running_fn:          Callable,
        set_running_fn:          Callable,
        get_owner_id_fn:         Callable,
        is_owner_fn:             Callable,
        system_running_fn:       Callable,
        # Memory
        get_history_fn:          Callable,
        get_history_turn_count:  Callable,
        get_history_summary:     Callable,
        clear_history_fn:        Callable,
        add_to_history_fn:       Callable,
        get_last_code_fn:        Callable,
        get_stats_fn:            Callable,
        get_cache_stats_fn:      Callable,
        get_cost_stats_fn:       Callable,
        format_stats_fn:         Callable,
        format_cache_stats_fn:   Callable,
        format_cost_stats_fn:    Callable,
        purge_cache_fn:          Callable,
        increment_review_fn:     Callable,
        # Compaction
        compact_history_fn:      Callable,
        format_compact_report_fn: Callable,
        call_claude_sync_fn:     Callable,
        # Pipeline
        call_claude_fn:          Callable,
        pipeline_prompts:        dict,
        auditor,
        # Bypass pipeline runner
        bypass_runner:           Callable,
        # Upwork
        upwork_system_prompt:    str,
        call_claude_upwork_fn:   Callable,
        # Dirs
        output_dir:              Path,
    ) -> None:
        self.get_running         = get_running_fn
        self.set_running         = set_running_fn
        self.get_owner_id        = get_owner_id_fn
        self.is_owner            = is_owner_fn
        self.system_running      = system_running_fn
        self.get_history         = get_history_fn
        self.get_turn_count      = get_history_turn_count
        self.get_history_summary = get_history_summary
        self.clear_history       = clear_history_fn
        self.add_to_history      = add_to_history_fn
        self.get_last_code       = get_last_code_fn
        self.get_stats           = get_stats_fn
        self.get_cache_stats     = get_cache_stats_fn
        self.get_cost_stats      = get_cost_stats_fn
        self.format_stats        = format_stats_fn
        self.format_cache_stats  = format_cache_stats_fn
        self.format_cost_stats   = format_cost_stats_fn
        self.purge_cache         = purge_cache_fn
        self.increment_review    = increment_review_fn
        self.compact_history     = compact_history_fn
        self.format_compact      = format_compact_report_fn
        self.call_claude_sync    = call_claude_sync_fn
        self.call_claude         = call_claude_fn
        self.pipeline_prompts    = pipeline_prompts
        self.auditor             = auditor
        self.bypass_runner       = bypass_runner
        self.upwork_system       = upwork_system_prompt
        self.call_claude_upwork  = call_claude_upwork_fn
        self.output_dir          = output_dir


# ══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════

class CommandHandlers:
    """
    Minden slash command handler mint metódus.
    Konstruktorban kapja a CommandRegistry-t.
    """

    def __init__(self, reg: CommandRegistry) -> None:
        self._r = reg

    # ── /start ───────────────────────────────────────────────

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        if not self._r.get_running():
            self._r.set_running(True)
            log.info("AXON újraindítva.")

        # History visszatöltés (v8.4)
        chat_id = str(update.effective_chat.id)
        turn_count = self._r.get_turn_count(chat_id)
        history_note = (
            f"\n\n🧠 _Előző session visszatöltve: {turn_count // 2} kérdés-válasz pár_"
            if turn_count > 0 else ""
        )

        await update.message.reply_text(
            f"🤖 *AXON {AXON_VERSION} ONLINE*{history_note}\n\n"
            "📋 *Parancsok:*\n"
            "/start – Indítás / újraindítás\n"
            "/help – Példák\n"
            "/status – Rendszer állapot\n"
            "/stats – Statisztikák + Cache info\n"
            "/upwork – Cover letter generálás wizard\n"
            "/history – Aktív conversation kontextus\n"
            "/clear – Conversation history törlése\n"
            "/compact – History tömörítése\n"
            "/review – Utolsó kód mély Gemini re-audit\n"
            "/files – outputs/ mappa listája\n"
            "/cache\\_clear – Cache törlése\n"
            "/stop – Kill switch\n"
            "/bypass [feladat] – Validáció nélkül\n\n"
            "🔬 *Kód validáció (DEVELOPER) – 3 szint:*\n"
            "1️⃣ Statikus biztonsági szűrő\n"
            "2️⃣ Unit teszt futtatás\n"
            "3️⃣ Gemini logikai audit\n\n"
            "🧠 *Multi-expert routing:*\n"
            "⚙️ DEVELOPER – Python kód (sandbox + Gemini)\n"
            "📋 PLANNER   – Tervek, dokumentáció\n"
            "✍️ CREATIVE  – Cover letter, szövegek\n"
            "📊 ANALYST   – Adatelemzés, számítások",
            parse_mode="Markdown",
        )

    # ── /help ────────────────────────────────────────────────

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        await update.message.reply_text(
            "💡 *Példák:*\n\n"
            "⚙️ *DEVELOPER*\n"
            "`Írj Python kódot ami megszámolja egy CSV sorait`\n"
            "   └ 3 szintű validáció automatikusan\n\n"
            "⚙️ *DEVELOPER – multi-turn*\n"
            "`Adj hozzá loggingot az előző kódhoz`\n"
            "   └ AXON emlékszik az előző kódra\n\n"
            "📋 *PLANNER*\n"
            "`Generálj strukturált AXON fejlesztési sprint tervet`\n"
            "   └ Markdown dokumentum, nincs sandbox\n\n"
            "✍️ *CREATIVE*\n"
            "`Írj Upwork cover lettert Python automatizálás munkához`\n"
            "   └ Egyedi szöveg, nincs cache, nincs history\n\n"
            "📊 *ANALYST*\n"
            "`Elemezd melyik Upwork kategória fizet legjobban`\n"
            "   └ Adatelemzés, táblázatos kimenet\n\n"
            "⚡ `/bypass Kód ami törli a temp fájlokat`\n"
            "   └ Validáció NÉLKÜL, saját felelősségre\n\n"
            "🔍 `/review` – Utolsó kód mély Gemini re-audit (70/100 küszöb)\n"
            "🧹 `/clear` – Conversation history törlése\n"
            "📜 `/history` – Mit tud most az AXON a sessionből",
            parse_mode="Markdown",
        )

    # ── /status ──────────────────────────────────────────────

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        chat_id    = str(update.effective_chat.id)
        turn_count = self._r.get_turn_count(chat_id)
        running    = self._r.get_running()

        # Watchman státusz formázás az auditorból
        try:
            from axon_watchman import get_system_status_message
            sys_status = get_system_status_message()
        except Exception:
            sys_status = "⚠️ Watchman nem elérhető"

        await update.message.reply_text(
            f"{sys_status}\n\n"
            f"⛔ Kill switch: {'AKTÍV' if not running else 'Készen'}\n"
            f"🧠 *Conversation history:* {turn_count // 2} kérdés-válasz pár aktív",
            parse_mode="Markdown",
        )

    # ── /stats ───────────────────────────────────────────────

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        days = 7
        if context.args:
            try:
                days = int(context.args[0])
            except ValueError:
                pass

        stats      = self._r.get_stats(days)
        cache_stats = self._r.get_cache_stats(days)
        cost_stats  = self._r.get_cost_stats(days)

        await update.message.reply_text(
            self._r.format_stats(stats) + "\n\n" +
            self._r.format_cache_stats(cache_stats) + "\n\n" +
            self._r.format_cost_stats(cost_stats),
            parse_mode="Markdown",
        )

    # ── /cache_clear ─────────────────────────────────────────

    async def cache_clear_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        try:
            purged = self._r.purge_cache()
            await update.message.reply_text(
                f"🗑️ *Cache törölve!* ({purged} bejegyzés)\n"
                "Következő feladatok újra API hívással futnak.",
                parse_mode="Markdown",
            )
            log.info(f"[CACHE] Manuális törlés: {purged} bejegyzés")
        except Exception as e:
            await update.message.reply_text(f"❌ Cache törlési hiba: {str(e)[:200]}")

    # ── /clear ───────────────────────────────────────────────

    async def clear_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        chat_id = str(update.effective_chat.id)
        count   = self._r.clear_history(chat_id)

        if count == 0:
            await update.message.reply_text(
                "📭 *Nincs aktív conversation history.*\nFriss session már fut.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"🧹 *Conversation history törölve!*\n"
                f"_{count // 2} kérdés-válasz pár eltávolítva._\n\n"
                "Következő üzenet friss kontextussal indul.",
                parse_mode="Markdown",
            )
        log.info(f"[HISTORY] /clear – {count} turn törölve | chat: {chat_id}")

    # ── /history ─────────────────────────────────────────────

    async def history_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        chat_id = str(update.effective_chat.id)
        summary = self._r.get_history_summary(chat_id)
        await update.message.reply_text(summary, parse_mode="Markdown")

    # ── /compact ─────────────────────────────────────────────

    async def compact_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        chat_id = str(update.effective_chat.id)
        history = self._r.get_history(chat_id)

        if not history:
            await update.message.reply_text(
                "📭 *Nincs aktív conversation history.*", parse_mode="Markdown",
            )
            return

        await update.message.reply_text("🗜 Tömörítés folyamatban...", parse_mode="Markdown")

        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self._r.compact_history, history, self._r.call_claude_sync, chat_id,
        )

        if not result.skipped:
            self._r.clear_history(chat_id)
            for turn in result.new_history:
                self._r.add_to_history(
                    chat_id, turn["role"], turn["content"],
                    turn.get("pipeline", "DEVELOPER"),
                )
            log.info(f"[COMPACT] /compact – {result.original_chars} → {result.new_chars} kar")

        await update.message.reply_text(
            self._r.format_compact(result), parse_mode="Markdown",
        )

    # ── /stop ────────────────────────────────────────────────

    async def stop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return
        self._r.set_running(False)
        log.warning("KILL SWITCH AKTIVÁLVA!")
        await update.message.reply_text(
            "⛔ *AXON LEÁLLÍTVA*\n\nÚjraindítás: `/start`",
            parse_mode="Markdown",
        )

    # ── /review ──────────────────────────────────────────────

    async def review_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update) or not self._r.system_running(update):
            return

        chat_id              = str(update.effective_chat.id)
        last_code, last_task = self._r.get_last_code(chat_id)

        if not last_code:
            await update.message.reply_text(
                "📭 *Nincs reviewolható kód.*\n\n"
                "A `/review` az aktuális session utolsó DEVELOPER kódját auditálja újra.\n"
                "Küldj előbb egy Python kód feladatot!",
                parse_mode="Markdown",
            )
            return

        task_display = (
            (last_task[:80] + "…") if last_task and len(last_task) > 80
            else (last_task or "ismeretlen feladat")
        )
        msg = await update.message.reply_text(
            f"🔍 *Mély Gemini review indul...*\n"
            f"_Feladat: {task_display}_\n\n"
            "⏳ Gemini elemez (szigorúbb küszöb: 70/100)...",
            parse_mode="Markdown",
        )

        review_task = (
            f"{last_task or 'Python kód'}\n\n"
            "[MÉLY REVIEW MÓD] Légy extra kritikus. Keress edge case-eket, "
            "biztonsági réseket és kód minőségi problémákat. Küszöb: 70/100."
        )

        audit_result = await self._r.auditor.audit(
            code=last_code, task=review_task,
            test_result="Manuális review – sandbox korábban lefutott",
        )

        # Szigorúbb PASS küszöb (70 vs alap 55)
        from models import AuditVerdict
        if audit_result.verdict != AuditVerdict.SKIP and audit_result.score < 70:
            audit_result = audit_result.model_copy(
                update={"passed": False, "verdict": AuditVerdict.FAIL}
            ) if hasattr(audit_result, 'model_copy') else audit_result

        self._r.increment_review()

        verdict_icon = "✅" if audit_result.passed else "❌"
        skip_note    = " _(Gemini nem elérhető)_" if audit_result.verdict == AuditVerdict.SKIP else ""

        reply = (
            f"🔍 *Mély Gemini Review eredménye*{skip_note}\n\n"
            f"{verdict_icon} *Verdikt:* {getattr(audit_result.verdict, 'value', audit_result.verdict)} ({audit_result.score}/100)\n"
            f"_Küszöb: 70/100 (szigorúbb mint az alap 55/100)_\n\n"
        )

        if audit_result.issues:
            reply += "*🔴 Talált problémák:*\n"
            for issue in audit_result.issues:
                reply += f"• {issue}\n"
            reply += "\n"

        if audit_result.suggestions:
            reply += "*💡 Javaslatok:*\n"
            for s in audit_result.suggestions:
                reply += f"• {s}\n"
            reply += "\n"

        if audit_result.passed and not audit_result.issues:
            reply += "✨ *Nem talált problémát.*\n"

        reply += f"\n_Reviewolt kód: {len(last_code)} kar | Feladat: {task_display}_"

        await TelegramSender.delete_status(msg)
        await TelegramSender.safe_send(update, reply)
        log.info(f"[REVIEW] {getattr(audit_result.verdict, 'value', audit_result.verdict)} ({audit_result.score}/100) | chat: {chat_id}")

    # ── /files ───────────────────────────────────────────────

    async def files_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update):
            return

        output_dir = self._r.output_dir
        if not output_dir.exists():
            await update.message.reply_text(
                "📂 *outputs/ mappa nem létezik még.*\nGenerálj először egy kódot!",
                parse_mode="Markdown",
            )
            return

        all_files = sorted(
            [f for f in output_dir.iterdir() if f.suffix in (".py", ".md")],
            key=lambda f: f.stat().st_mtime, reverse=True,
        )[:20]

        if not all_files:
            await update.message.reply_text(
                "📂 *Nincs fájl az outputs/ mappában.*", parse_mode="Markdown",
            )
            return

        arg = " ".join(context.args).strip().lower() if context.args else ""

        if arg == "last":
            py_files = [f for f in all_files if f.suffix == ".py"]
            if py_files:
                await TelegramSender.send_file(update, str(py_files[0]), f"📎 `{py_files[0].name}`")
            return

        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(all_files):
                f = all_files[idx]
                await TelegramSender.send_file(update, str(f), f"📎 `{f.name}`")
            else:
                await update.message.reply_text(
                    f"❌ Érvénytelen szám. 1–{len(all_files)} között adj meg egyet.",
                )
            return

        # Lista
        lines = ["📂 *outputs/ – legutóbbi fájlok:*\n"]
        for i, f in enumerate(all_files[:10], 1):
            size_kb = f.stat().st_size // 1024
            icon    = "🐍" if f.suffix == ".py" else "📄"
            lines.append(f"`{i}.` {icon} `{f.name[:55]}`  _{size_kb}KB_")

        lines.append(
            f"\n_Küldés: `/files [szám]` vagy `/files last`_\n"
            f"_Összes fájl: {len(all_files)}_"
        )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ── /bypass ──────────────────────────────────────────────

    async def bypass_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._r.is_owner(update) or not self._r.system_running(update):
            return

        task = " ".join(context.args).strip()
        if not task:
            await update.message.reply_text("Használat: `/bypass [feladat]`", parse_mode="Markdown")
            return

        msg    = await update.message.reply_text("⚡ *Bypass mód...*", parse_mode="Markdown")
        result = await self._r.call_claude(
            self._r.pipeline_prompts.get("DEVELOPER", ""), task,
        )
        await TelegramSender.delete_status(msg)
        await TelegramSender.safe_send(update, "⚡ *DEVELOPER (bypass):*\n\n" + result)

    # ── /upwork WIZARD ───────────────────────────────────────

    async def upwork_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not self._r.is_owner(update) or not self._r.system_running(update):
            return ConversationHandler.END

        if context.args:
            context.user_data["upwork_job"] = " ".join(context.args).strip()
            await update.message.reply_text(
                "📋 *Job leírás rögzítve.*\n\n"
                "Mekkora a hirdetett budget? _(Skip: `/skip`)_",
                parse_mode="Markdown",
            )
            return UPWORK_BUDGET

        await update.message.reply_text(
            "✍️ *Upwork Cover Letter Wizard*\n\n"
            "📋 *1. lépés:* Másold be a job leírást!\n\n"
            "_A teljes hirdetés szövege, minél több annál jobb._",
            parse_mode="Markdown",
        )
        return UPWORK_JOB

    async def upwork_got_job(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not self._r.is_owner(update):
            return ConversationHandler.END
        context.user_data["upwork_job"] = update.message.text.strip()
        await update.message.reply_text(
            "💰 *2. lépés:* Mekkora a hirdetett budget?\n\n"
            "_Pl: $150, $300 fixed, $25/hr — vagy `/skip` ha nincs megadva._",
            parse_mode="Markdown",
        )
        return UPWORK_BUDGET

    async def upwork_got_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not self._r.is_owner(update):
            return ConversationHandler.END
        context.user_data["upwork_budget"] = update.message.text.strip()
        return await self._upwork_generate(update, context)

    async def upwork_skip_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not self._r.is_owner(update):
            return ConversationHandler.END
        context.user_data["upwork_budget"] = None
        return await self._upwork_generate(update, context)

    async def upwork_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        await update.message.reply_text(
            "❌ *Upwork wizard megszakítva.*\n`/upwork` az újraindításhoz.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    async def _upwork_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Belső: cover letter generálás az összegyűjtött adatokból."""
        job    = context.user_data.get("upwork_job", "")
        budget = context.user_data.get("upwork_budget")

        if not job:
            await update.message.reply_text("❌ Nincs job leírás. Indítsd újra: `/upwork`")
            return ConversationHandler.END

        budget_line = f"\nHirdetett budget: {budget}" if budget else ""
        msg = await update.message.reply_text(
            "✍️ *Cover letter generálás...*\n_CREATIVE pipeline – egyedi, személyes levél_",
            parse_mode="Markdown",
        )

        prompt = (
            f"Írj Upwork cover lettert erre a hirdetésre:\n\n"
            f"{job}{budget_line}\n\n"
            "SZABÁLYOK:\n"
            "- Angolul írj\n"
            "- Max 130 szó — minden szó számít\n"
            "- Első mondat: azonnal a lényeg\n"
            "- Csak VALÓS tapasztalat (Python, automatizálás, API integráció, Telegram bot, n8n, AI pipeline)\n"
            "- CTA a végén: egy konkrét kérdés vagy ajánlat\n"
            "- TILOS: 'I am writing to apply', 'I would love to', bulletpoint lista\n"
            "- Úgy hangozzon mintha egy fejlesztő gyorsan begépelte volna, nem mintha AI írta volna"
        )

        try:
            response = await self._r.call_claude_upwork(self._r.upwork_system, prompt, max_tokens=600)
            await TelegramSender.delete_status(msg)
            budget_display = f"💰 Budget: {budget}\n" if budget else ""
            await TelegramSender.safe_send(
                update,
                f"✍️ *Cover Letter*\n"
                f"{budget_display}"
                f"_{job[:80]}{'...' if len(job) > 80 else ''}_\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{response}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 _Másold be az Upwork üzenetmezőbe_",
            )
            log.info(f"[UPWORK] Cover letter generálva ({len(response)} kar)")

        except Exception as e:
            await TelegramSender.delete_status(msg)
            await update.message.reply_text(f"❌ Hiba: {str(e)[:200]}")
            log.error(f"[UPWORK] Hiba: {e}")

        context.user_data.clear()
        return ConversationHandler.END
