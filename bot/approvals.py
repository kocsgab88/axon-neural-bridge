"""
AXON Neural Bridge — Risk Approval
====================================
v9.0

Kockázatos kód jóváhagyás Telegram inline keyboard-on keresztül.
Kivonva a handlers.py-ból hogy elkerüljük a circular importot.
"""

from __future__ import annotations

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("AXON.Approvals")

# Függő jóváhagyások: task_id → asyncio.Event
_pending_approvals: dict[str, asyncio.Event] = {}
_approval_results:  dict[str, bool]           = {}


async def ask_risk_approval(update: Update, risks: list[str], task_id: str) -> bool:
    """
    Inline keyboard-on kéri a jóváhagyást kockázatos kódhoz.
    Blokkolja a pipeline-t amíg a user válaszol (max 60s).
    """
    risk_list = ", ".join(f"`{r}`" for r in risks[:5])
    keyboard  = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Jóváhagyom", callback_data=f"approve:{task_id}"),
        InlineKeyboardButton("❌ Visszautasítom", callback_data=f"reject:{task_id}"),
    ]])

    await update.message.reply_text(
        f"⚠️ *Kockázatos kód észlelve!*\n\n"
        f"Talált kulcsszavak: {risk_list}\n\n"
        f"Jóváhagyod a futtatást?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    event = asyncio.Event()
    _pending_approvals[task_id] = event

    try:
        await asyncio.wait_for(event.wait(), timeout=60.0)
        return _approval_results.get(task_id, False)
    except asyncio.TimeoutError:
        log.warning(f"[APPROVAL] Timeout: {task_id}")
        return False
    finally:
        _pending_approvals.pop(task_id, None)
        _approval_results.pop(task_id,  None)


async def handle_approval_callback(update: Update, context) -> None:
    """CallbackQueryHandler — approve/reject gomb lenyomásakor hívódik."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, task_id = data.split(":", 1)
    approved = action == "approve"

    _approval_results[task_id] = approved
    event = _pending_approvals.get(task_id)
    if event:
        event.set()

    await query.edit_message_text(
        f"{'✅ Jóváhagyva' if approved else '❌ Visszautasítva'} — pipeline {'folytatódik' if approved else 'leállítva'}.",
    )
    log.info(f"[APPROVAL] task_id={task_id} → {'APPROVED' if approved else 'REJECTED'}")
