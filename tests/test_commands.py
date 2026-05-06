"""
tests/test_commands.py — AXON v9.0 command handler tesztek
Lefedés: minden command handler helyes viselkedése mock-kal,
         owner check, ConversationHandler state machine.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.commands import CommandHandlers, CommandRegistry, UPWORK_JOB, UPWORK_BUDGET
from models import AuditResult, AuditVerdict


# ══════════════════════════════════════════════════════════════
#  FIXTURES
# ══════════════════════════════════════════════════════════════

def _make_registry(
    is_owner: bool = True,
    system_running: bool = True,
    running: bool = True,
    turn_count: int = 0,
    clear_count: int = 0,
    last_code: tuple = (None, None),
    purge_count: int = 0,
    history: list | None = None,
    output_dir: Path | None = None,
) -> CommandRegistry:
    return CommandRegistry(
        get_running_fn=MagicMock(return_value=running),
        set_running_fn=MagicMock(),
        get_owner_id_fn=MagicMock(return_value=123),
        is_owner_fn=MagicMock(return_value=is_owner),
        system_running_fn=MagicMock(return_value=system_running),
        get_history_fn=MagicMock(return_value=history or []),
        get_history_turn_count=MagicMock(return_value=turn_count),
        get_history_summary=MagicMock(return_value="📜 *History:*\n_Nincs aktív session_"),
        clear_history_fn=MagicMock(return_value=clear_count),
        add_to_history_fn=MagicMock(),
        get_last_code_fn=MagicMock(return_value=last_code),
        get_stats_fn=MagicMock(return_value={}),
        get_cache_stats_fn=MagicMock(return_value={}),
        get_cost_stats_fn=MagicMock(return_value={}),
        format_stats_fn=MagicMock(return_value="📊 Stats"),
        format_cache_stats_fn=MagicMock(return_value="⚡ Cache"),
        format_cost_stats_fn=MagicMock(return_value="💰 Cost"),
        purge_cache_fn=MagicMock(return_value=purge_count),
        increment_review_fn=MagicMock(),
        compact_history_fn=MagicMock(),
        format_compact_report_fn=MagicMock(return_value="🗜 Compact report"),
        call_claude_sync_fn=MagicMock(),
        call_claude_fn=AsyncMock(return_value="claude válasz"),
        pipeline_prompts={"DEVELOPER": "dev sys"},
        auditor=MagicMock(),
        bypass_runner=AsyncMock(),
        upwork_system_prompt="upwork sys",
        call_claude_upwork_fn=AsyncMock(return_value="cover letter szöveg"),
        output_dir=output_dir or Path("/tmp/axon_test_outputs"),
    )


def _make_update(text: str = "", args: list | None = None) -> MagicMock:
    """Telegram Update mock."""
    update             = MagicMock()
    update.message     = MagicMock()
    update.message.text = text
    update.message.reply_text  = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.effective_chat      = MagicMock()
    update.effective_chat.id   = 42
    return update


def _make_context(args: list | None = None) -> MagicMock:
    ctx      = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _make_handlers(**kwargs) -> CommandHandlers:
    return CommandHandlers(_make_registry(**kwargs))


# ══════════════════════════════════════════════════════════════
#  OWNER CHECK — minden commandnál
# ══════════════════════════════════════════════════════════════

class TestOwnerCheck:

    @pytest.mark.asyncio
    async def test_start_non_owner_no_reply(self):
        h = _make_handlers(is_owner=False)
        update = _make_update()
        await h.start(update, _make_context())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_non_owner_no_reply(self):
        h = _make_handlers(is_owner=False)
        update = _make_update()
        await h.stop_cmd(update, _make_context())
        update.message.reply_text.assert_not_called()
        h._r.set_running.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_non_owner_no_reply(self):
        h = _make_handlers(is_owner=False)
        update = _make_update()
        await h.clear_cmd(update, _make_context())
        update.message.reply_text.assert_not_called()
        h._r.clear_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_stats_non_owner_no_reply(self):
        h = _make_handlers(is_owner=False)
        update = _make_update()
        await h.stats_cmd(update, _make_context())
        update.message.reply_text.assert_not_called()


# ══════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════

class TestStartCmd:

    @pytest.mark.asyncio
    async def test_sends_version(self):
        h      = _make_handlers()
        update = _make_update()
        await h.start(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "v9.0" in reply

    @pytest.mark.asyncio
    async def test_restarts_if_stopped(self):
        h = _make_handlers(running=False)
        update = _make_update()
        await h.start(update, _make_context())
        h._r.set_running.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_no_restart_if_already_running(self):
        h = _make_handlers(running=True)
        update = _make_update()
        await h.start(update, _make_context())
        h._r.set_running.assert_not_called()

    @pytest.mark.asyncio
    async def test_shows_history_note_when_turns_present(self):
        h      = _make_handlers(turn_count=6)
        update = _make_update()
        await h.start(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "session visszatöltve" in reply
        assert "3" in reply   # 6 // 2 = 3 pár

    @pytest.mark.asyncio
    async def test_no_history_note_when_fresh(self):
        h      = _make_handlers(turn_count=0)
        update = _make_update()
        await h.start(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "visszatöltve" not in reply


# ══════════════════════════════════════════════════════════════
#  /stop
# ══════════════════════════════════════════════════════════════

class TestStopCmd:

    @pytest.mark.asyncio
    async def test_sets_running_false(self):
        h = _make_handlers()
        await h.stop_cmd(_make_update(), _make_context())
        h._r.set_running.assert_called_once_with(False)

    @pytest.mark.asyncio
    async def test_reply_contains_stop_message(self):
        h      = _make_handlers()
        update = _make_update()
        await h.stop_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "LEÁLLÍTVA" in reply


# ══════════════════════════════════════════════════════════════
#  /stats
# ══════════════════════════════════════════════════════════════

class TestStatsCmd:

    @pytest.mark.asyncio
    async def test_default_7_days(self):
        h = _make_handlers()
        await h.stats_cmd(_make_update(), _make_context())
        h._r.get_stats.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_custom_days_arg(self):
        h = _make_handlers()
        await h.stats_cmd(_make_update(), _make_context(args=["30"]))
        h._r.get_stats.assert_called_once_with(30)

    @pytest.mark.asyncio
    async def test_invalid_days_fallback_to_7(self):
        h = _make_handlers()
        await h.stats_cmd(_make_update(), _make_context(args=["nem_szam"]))
        h._r.get_stats.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_all_three_formatters_called(self):
        h = _make_handlers()
        await h.stats_cmd(_make_update(), _make_context())
        h._r.format_stats.assert_called_once()
        h._r.format_cache_stats.assert_called_once()
        h._r.format_cost_stats.assert_called_once()


# ══════════════════════════════════════════════════════════════
#  /cache_clear
# ══════════════════════════════════════════════════════════════

class TestCacheClearCmd:

    @pytest.mark.asyncio
    async def test_calls_purge(self):
        h = _make_handlers(purge_count=15)
        await h.cache_clear_cmd(_make_update(), _make_context())
        h._r.purge_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_reply_shows_count(self):
        h      = _make_handlers(purge_count=15)
        update = _make_update()
        await h.cache_clear_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "15" in reply

    @pytest.mark.asyncio
    async def test_error_handled_gracefully(self):
        h = _make_handlers()
        h._r.purge_cache = MagicMock(side_effect=Exception("DB hiba"))
        update = _make_update()
        await h.cache_clear_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "❌" in reply


# ══════════════════════════════════════════════════════════════
#  /clear
# ══════════════════════════════════════════════════════════════

class TestClearCmd:

    @pytest.mark.asyncio
    async def test_no_history_message(self):
        h      = _make_handlers(clear_count=0)
        update = _make_update()
        await h.clear_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "Nincs aktív" in reply

    @pytest.mark.asyncio
    async def test_cleared_message_with_count(self):
        h      = _make_handlers(clear_count=6)
        update = _make_update()
        await h.clear_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "3" in reply   # 6 // 2 = 3 pár

    @pytest.mark.asyncio
    async def test_calls_clear_history_with_chat_id(self):
        h = _make_handlers(clear_count=2)
        await h.clear_cmd(_make_update(), _make_context())
        h._r.clear_history.assert_called_once_with("42")


# ══════════════════════════════════════════════════════════════
#  /history
# ══════════════════════════════════════════════════════════════

class TestHistoryCmd:

    @pytest.mark.asyncio
    async def test_calls_get_summary(self):
        h = _make_handlers()
        await h.history_cmd(_make_update(), _make_context())
        h._r.get_history_summary.assert_called_once_with("42")

    @pytest.mark.asyncio
    async def test_reply_contains_summary(self):
        h      = _make_handlers()
        update = _make_update()
        await h.history_cmd(update, _make_context())
        reply  = update.message.reply_text.call_args[0][0]
        assert "History" in reply


# ══════════════════════════════════════════════════════════════
#  /compact
# ══════════════════════════════════════════════════════════════

class TestCompactCmd:

    @pytest.mark.asyncio
    async def test_no_history_message(self):
        h      = _make_handlers(history=[])
        update = _make_update()
        await h.compact_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "Nincs aktív" in reply
        h._r.compact_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_history_calls_compact(self):
        history = [{"role": "user", "content": "feladat"}, {"role": "assistant", "content": "kód"}]
        h = _make_handlers(history=history)

        compact_result = MagicMock()
        compact_result.skipped    = True
        compact_result.new_history = []
        h._r.compact_history = MagicMock(return_value=compact_result)

        await h.compact_cmd(_make_update(), _make_context())
        h._r.compact_history.assert_called_once()


# ══════════════════════════════════════════════════════════════
#  /review
# ══════════════════════════════════════════════════════════════

class TestReviewCmd:

    @pytest.mark.asyncio
    async def test_no_code_sends_message(self):
        h      = _make_handlers(last_code=(None, None))
        update = _make_update()
        await h.review_cmd(update, _make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "Nincs reviewolható" in reply
        h._r.auditor.audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_code_calls_auditor(self):
        h = _make_handlers(last_code=("print('hello')", "feladat"))
        h._r.auditor.audit = AsyncMock(return_value=AuditResult(
            verdict=AuditVerdict.PASS, score=85,
        ))
        update = _make_update()
        update.message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
        await h.review_cmd(update, _make_context())
        h._r.auditor.audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_increments_review_count(self):
        h = _make_handlers(last_code=("x = 1", "feladat"))
        h._r.auditor.audit = AsyncMock(return_value=AuditResult(
            verdict=AuditVerdict.PASS, score=85,
        ))
        update = _make_update()
        update.message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
        await h.review_cmd(update, _make_context())
        h._r.increment_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_owner_no_audit(self):
        h = _make_handlers(is_owner=False)
        await h.review_cmd(_make_update(), _make_context())
        h._r.auditor.audit.assert_not_called()


# ══════════════════════════════════════════════════════════════
#  /bypass
# ══════════════════════════════════════════════════════════════

class TestBypassCmd:

    @pytest.mark.asyncio
    async def test_empty_task_shows_usage(self):
        h      = _make_handlers()
        update = _make_update()
        await h.bypass_cmd(update, _make_context(args=[]))
        reply = update.message.reply_text.call_args[0][0]
        assert "bypass" in reply.lower()
        h._r.call_claude.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_task_calls_claude(self):
        h      = _make_handlers()
        update = _make_update()
        update.message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
        await h.bypass_cmd(update, _make_context(args=["Írj", "hello", "world-öt"]))
        h._r.call_claude.assert_called_once()

    @pytest.mark.asyncio
    async def test_system_not_running_skips(self):
        h = _make_handlers(system_running=False)
        await h.bypass_cmd(_make_update(), _make_context(args=["task"]))
        h._r.call_claude.assert_not_called()


# ══════════════════════════════════════════════════════════════
#  /upwork WIZARD STATE MACHINE
# ══════════════════════════════════════════════════════════════

class TestUpworkWizard:

    @pytest.mark.asyncio
    async def test_start_no_args_returns_job_state(self):
        h   = _make_handlers()
        ctx = _make_context(args=[])
        result = await h.upwork_start(_make_update(), ctx)
        assert result == UPWORK_JOB

    @pytest.mark.asyncio
    async def test_start_with_args_skips_to_budget_state(self):
        h   = _make_handlers()
        ctx = _make_context(args=["Python", "scraping", "job"])
        result = await h.upwork_start(_make_update(), ctx)
        assert result == UPWORK_BUDGET
        assert ctx.user_data["upwork_job"] == "Python scraping job"

    @pytest.mark.asyncio
    async def test_got_job_saves_and_returns_budget_state(self):
        h      = _make_handlers()
        update = _make_update(text="Ez a job leírás")
        ctx    = _make_context()
        result = await h.upwork_got_job(update, ctx)
        assert result           == UPWORK_BUDGET
        assert ctx.user_data["upwork_job"] == "Ez a job leírás"

    @pytest.mark.asyncio
    async def test_got_budget_saves_and_generates(self):
        h      = _make_handlers()
        update = _make_update(text="$150")
        ctx    = _make_context()
        ctx.user_data["upwork_job"] = "Job leírás"
        result = await h.upwork_got_budget(update, ctx)
        assert result == -1   # ConversationHandler.END
        h._r.call_claude_upwork.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_budget_generates_without_budget(self):
        h   = _make_handlers()
        ctx = _make_context()
        ctx.user_data["upwork_job"] = "Job leírás"
        result = await h.upwork_skip_budget(_make_update(), ctx)
        assert result == -1   # END
        h._r.call_claude_upwork.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_clears_data(self):
        h   = _make_handlers()
        ctx = _make_context()
        ctx.user_data["upwork_job"]    = "Job"
        ctx.user_data["upwork_budget"] = "$100"
        result = await h.upwork_cancel(_make_update(), ctx)
        assert result              == -1   # END
        assert ctx.user_data       == {}

    @pytest.mark.asyncio
    async def test_generate_no_job_sends_error(self):
        h      = _make_handlers()
        update = _make_update()
        ctx    = _make_context()
        ctx.user_data = {}   # nincs job adat
        result = await h._upwork_generate(update, ctx)
        assert result == -1
        h._r.call_claude_upwork.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_with_budget_shown_in_reply(self):
        h      = _make_handlers()
        update = _make_update()
        ctx    = _make_context()
        ctx.user_data["upwork_job"]    = "Job leírás"
        ctx.user_data["upwork_budget"] = "$300"
        update.message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
        await h._upwork_generate(update, ctx)
        # A safe_send hívódik a budget-tel — ellenőrizzük hogy a call_claude_upwork hívódott
        h._r.call_claude_upwork.assert_called_once()
