"""
tests/test_handlers.py — AXON v9.0 handler unit tesztek
Lefedés: PipelineFormatter minden ága, TelegramSender logika,
         SimplePipelineRunner cache/no-cache logika.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models import (
    AuditResult, AuditVerdict, Pipeline, PipelineResult,
    SandboxResult, Task,
)
from bot.handlers import PipelineFormatter, SimplePipelineRunner


# ══════════════════════════════════════════════════════════════
#  PIPELINE FORMATTER
# ══════════════════════════════════════════════════════════════

def _task(pipeline: Pipeline = Pipeline.DEVELOPER) -> Task:
    return Task(text="Írj kódot", chat_id="1", pipeline=pipeline)


class TestPipelineFormatterDeveloper:

    def test_cache_hit_contains_cache_word(self):
        r   = PipelineResult(task=_task(), pipeline=Pipeline.DEVELOPER, success=True, output="cached", cache_hit=True)
        msg = PipelineFormatter.format_developer_result(r)
        assert "cache" in msg.lower()

    def test_failed_result_returns_output(self):
        r   = PipelineResult(task=_task(), pipeline=Pipeline.DEVELOPER, success=False, output="❌ Sandbox sikertelen")
        msg = PipelineFormatter.format_developer_result(r)
        assert msg == "❌ Sandbox sikertelen"

    def test_full_result_contains_score(self):
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output="print('hello')",
            sandbox=SandboxResult(success=True, message="OK", tests_passed=2, tests_total=2),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=91),
            cost_usd=0.0042, tokens_in=1000, tokens_out=500, api_calls=3,
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "91"     in msg
        assert "PASS"   in msg
        assert "0.0042" in msg

    def test_full_result_contains_file_line(self):
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output="x = 1",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=80),
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
            output_file="20260411_feladat.py",
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "20260411_feladat.py" in msg

    def test_audit_skip_shows_skip_text(self):
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output="x = 1",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult.skipped("API timeout"),
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "kihagyva" in msg

    def test_failed_audit_shows_issues(self):
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output="x = 1",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(
                verdict=AuditVerdict.FAIL, score=40,
                issues=["Nincs error handling", "Nincs logging"],
            ),
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "Nincs error handling" in msg

    def test_code_preview_max_15_lines(self):
        long_code = "\n".join([f"line_{i} = {i}" for i in range(30)])
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output=long_code,
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=85),
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "+15 sor" in msg   # a "... (+X sor)" szöveg megjelenik

    def test_short_code_no_truncation(self):
        r = PipelineResult(
            task=_task(), pipeline=Pipeline.DEVELOPER, success=True,
            output="x = 1\nprint(x)",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=85),
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
        )
        msg = PipelineFormatter.format_developer_result(r)
        assert "sor)" not in msg   # nincs csonkítás


class TestPipelineFormatterSimple:

    def _result(self, pipeline: Pipeline, cache_hit: bool = False) -> PipelineResult:
        t = _task(pipeline)
        return PipelineResult(
            task=t, pipeline=pipeline, success=True, output="válasz szöveg",
            cost_usd=0.001, tokens_in=100, tokens_out=50, api_calls=1,
            cache_hit=cache_hit,
        )

    def test_planner_contains_icon(self):
        msg = PipelineFormatter.format_simple_result(self._result(Pipeline.PLANNER))
        assert "📋" in msg

    def test_creative_contains_icon(self):
        msg = PipelineFormatter.format_simple_result(self._result(Pipeline.CREATIVE))
        assert "✍️" in msg

    def test_analyst_contains_icon(self):
        msg = PipelineFormatter.format_simple_result(self._result(Pipeline.ANALYST))
        assert "📊" in msg

    def test_cache_hit_note_shown(self):
        msg = PipelineFormatter.format_simple_result(self._result(Pipeline.PLANNER, cache_hit=True))
        assert "cache" in msg.lower()

    def test_output_present(self):
        msg = PipelineFormatter.format_simple_result(self._result(Pipeline.ANALYST))
        assert "válasz szöveg" in msg

    def test_zero_cost_no_cost_line(self):
        t = _task(Pipeline.PLANNER)
        r = PipelineResult(task=t, pipeline=Pipeline.PLANNER, success=True, output="x", cost_usd=0.0)
        msg = PipelineFormatter.format_simple_result(r)
        assert "💰" not in msg

    def test_failed_result_returns_output(self):
        t = _task(Pipeline.PLANNER)
        r = PipelineResult(task=t, pipeline=Pipeline.PLANNER, success=False, output="❌ Hiba")
        msg = PipelineFormatter.format_simple_result(r)
        assert msg == "❌ Hiba"


class TestPipelineFormatterStatus:

    def test_developer_has_validation_hint(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.DEVELOPER, "⚙️", "DEVELOPER", False, 0, False,
        )
        assert "3 szintű validáció" in msg

    def test_planner_no_validation_hint(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.PLANNER, "📋", "PLANNER", False, 0, False,
        )
        assert "3 szintű validáció" not in msg

    def test_multiturn_shows_count(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.DEVELOPER, "⚙️", "DEVELOPER", True, 6, False,
        )
        assert "Multi-turn" in msg
        assert "3" in msg   # 6 // 2 = 3 kérdés-válasz pár

    def test_no_cache_pipeline_shows_unique(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.CREATIVE, "✍️", "CREATIVE", False, 0, True,
        )
        assert "Egyedi generálás" in msg

    def test_multiturn_shows_cache_bypass(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.DEVELOPER, "⚙️", "DEVELOPER", True, 2, False,
        )
        assert "Cache bypass" in msg

    def test_fresh_session_shows_cache_check(self):
        msg = PipelineFormatter.format_initial_status(
            Pipeline.DEVELOPER, "⚙️", "DEVELOPER", False, 0, False,
        )
        assert "Cache ellenőrzés" in msg


class TestPipelineFormatterError:

    def test_error_contains_pipeline_name(self):
        msg = PipelineFormatter.format_error(Pipeline.DEVELOPER, Exception("valami elromlott"))
        assert "DEVELOPER"          in msg
        assert "valami elromlott"   in msg

    def test_long_error_truncated(self):
        long_error = "x" * 500
        msg = PipelineFormatter.format_error(Pipeline.PLANNER, Exception(long_error))
        # str(e)[:300] → max 300 kar az error szövegből
        assert len(msg) < 600


# ══════════════════════════════════════════════════════════════
#  SIMPLE PIPELINE RUNNER
# ══════════════════════════════════════════════════════════════

def _make_runner(
    cached_response: str | None = None,
    claude_response: str = "Claude válasz",
) -> SimplePipelineRunner:
    return SimplePipelineRunner(
        call_claude_tracked=AsyncMock(return_value=claude_response),
        call_claude_with_history=AsyncMock(return_value=claude_response),
        pipeline_prompts={
            "PLANNER":  "planner sys",
            "CREATIVE": "creative sys",
            "ANALYST":  "analyst sys",
        },
        get_cached_response=MagicMock(return_value=cached_response),
        save_cached_response=MagicMock(),
        get_history=MagicMock(return_value=[]),
        add_to_history=MagicMock(),
        save_training_sample=MagicMock(),
        pop_tokens_fn=MagicMock(return_value={"input": 100, "output": 50, "calls": 1}),
        tokens_to_usd_fn=MagicMock(return_value=0.001),
        log_cost_fn=MagicMock(),
        no_cache_pipelines={Pipeline.CREATIVE},
        history_enabled_pipelines={Pipeline.PLANNER, Pipeline.ANALYST},
    )


class TestSimplePipelineRunner:

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self):
        runner = _make_runner(cached_response="cached válasz")
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        result = await runner.run(Pipeline.PLANNER, task, AsyncMock())
        assert result.cache_hit  is True
        assert result.output     == "cached válasz"

    @pytest.mark.asyncio
    async def test_creative_never_cached(self):
        """CREATIVE pipeline: cache_hit=False még ha van is cached válasz."""
        runner = _make_runner(cached_response="cached válasz")
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.CREATIVE)
        result = await runner.run(Pipeline.CREATIVE, task, AsyncMock())
        assert result.cache_hit is False
        assert result.output    == "Claude válasz"

    @pytest.mark.asyncio
    async def test_no_cache_calls_claude(self):
        runner     = _make_runner(cached_response=None)
        task       = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        result     = await runner.run(Pipeline.PLANNER, task, AsyncMock())
        assert result.output == "Claude válasz"
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_success_result_has_cost(self):
        runner = _make_runner()
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.ANALYST)
        result = await runner.run(Pipeline.ANALYST, task, AsyncMock())
        assert result.cost_usd    == pytest.approx(0.001)
        assert result.tokens_in   == 100
        assert result.tokens_out  == 50
        assert result.api_calls   == 1

    @pytest.mark.asyncio
    async def test_history_enabled_pipeline_adds_to_history(self):
        runner = _make_runner()
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        await runner.run(Pipeline.PLANNER, task, AsyncMock())
        assert runner._add_history.call_count == 2   # user + assistant

    @pytest.mark.asyncio
    async def test_creative_does_not_add_history(self):
        runner = _make_runner()
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.CREATIVE)
        await runner.run(Pipeline.CREATIVE, task, AsyncMock())
        runner._add_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_planner_saves_to_cache(self):
        runner = _make_runner(cached_response=None)
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        await runner.run(Pipeline.PLANNER, task, AsyncMock())
        runner._save_cached.assert_called_once()

    @pytest.mark.asyncio
    async def test_creative_not_saved_to_cache(self):
        runner = _make_runner(cached_response=None)
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.CREATIVE)
        await runner.run(Pipeline.CREATIVE, task, AsyncMock())
        runner._save_cached.assert_not_called()

    @pytest.mark.asyncio
    async def test_training_sample_saved(self):
        runner = _make_runner()
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.ANALYST)
        await runner.run(Pipeline.ANALYST, task, AsyncMock())
        runner._save_training.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_callback_called(self):
        runner    = _make_runner()
        task      = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        status_cb = AsyncMock()
        await runner.run(Pipeline.PLANNER, task, status_cb)
        status_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_history_aware_uses_history_when_present(self):
        """Ha van history, call_claude_with_history hívódik."""
        runner = _make_runner()
        runner._get_history = MagicMock(return_value=[
            {"role": "user", "content": "előző kérdés"},
            {"role": "assistant", "content": "előző válasz"},
        ])
        task = Task(text="folytatás", chat_id="1", pipeline=Pipeline.PLANNER)
        await runner.run(Pipeline.PLANNER, task, AsyncMock())
        runner._call_with_history.assert_called_once()
        runner._call_tracked.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_history_uses_tracked(self):
        """Ha nincs history, call_claude_tracked hívódik."""
        runner = _make_runner()
        task   = Task(text="feladat", chat_id="1", pipeline=Pipeline.PLANNER)
        await runner.run(Pipeline.PLANNER, task, AsyncMock())
        runner._call_tracked.assert_called_once()
        runner._call_with_history.assert_not_called()
