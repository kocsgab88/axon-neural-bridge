"""
tests/test_models.py — AXON v9.0 model unit tesztek
Lefedés: minden model, minden validator, minden property, minden edge case.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime
from pydantic import ValidationError

from models import (
    AuditResult, AuditVerdict, CostEntry, FixSample,
    HistoryTurn, Pipeline, PipelineResult, Role,
    SandboxResult, SystemStatus, Task, TaskComplexity,
)


# ── Enums ────────────────────────────────────────────────────

class TestEnums:
    def test_pipeline_string_values(self):
        assert Pipeline.DEVELOPER == "DEVELOPER"
        assert Pipeline.PLANNER   == "PLANNER"
        assert Pipeline.CREATIVE  == "CREATIVE"
        assert Pipeline.ANALYST   == "ANALYST"

    def test_pipeline_from_string(self):
        assert Pipeline("DEVELOPER") == Pipeline.DEVELOPER

    def test_invalid_pipeline_raises(self):
        with pytest.raises(ValueError):
            Pipeline("INVALID")

    def test_audit_verdict_values(self):
        assert AuditVerdict.PASS == "PASS"
        assert AuditVerdict.FAIL == "FAIL"
        assert AuditVerdict.SKIP == "SKIP"

    def test_role_values(self):
        assert Role.USER      == "user"
        assert Role.ASSISTANT == "assistant"

    def test_task_complexity_values(self):
        assert TaskComplexity.SIMPLE  == "SIMPLE"
        assert TaskComplexity.COMPLEX == "COMPLEX"


# ── Task ─────────────────────────────────────────────────────

class TestTask:
    def test_valid_task(self):
        t = Task(text="Írj kódot", chat_id="123", pipeline=Pipeline.DEVELOPER)
        assert t.text     == "Írj kódot"
        assert t.chat_id  == "123"
        assert t.pipeline == Pipeline.DEVELOPER
        assert t.complexity is None
        assert isinstance(t.created_at, datetime)

    def test_text_stripped(self):
        t = Task(text="  hello  ", chat_id="1", pipeline=Pipeline.PLANNER)
        assert t.text == "hello"

    def test_empty_text_raises(self):
        with pytest.raises(ValidationError) as exc:
            Task(text="", chat_id="1", pipeline=Pipeline.DEVELOPER)
        assert "Task text" in str(exc.value)

    def test_whitespace_only_text_raises(self):
        with pytest.raises(ValidationError):
            Task(text="   ", chat_id="1", pipeline=Pipeline.DEVELOPER)

    def test_empty_chat_id_raises(self):
        with pytest.raises(ValidationError):
            Task(text="valami", chat_id="", pipeline=Pipeline.DEVELOPER)

    def test_model_copy_preserves_original(self):
        t1 = Task(text="feladat", chat_id="1", pipeline=Pipeline.DEVELOPER)
        t2 = t1.model_copy(update={"complexity": TaskComplexity.SIMPLE})
        assert t2.complexity == TaskComplexity.SIMPLE
        assert t1.complexity is None   # eredeti nem változott

    def test_all_pipelines_accepted(self):
        for p in Pipeline:
            t = Task(text="x", chat_id="1", pipeline=p)
            assert t.pipeline == p


# ── SandboxResult ────────────────────────────────────────────

class TestSandboxResult:
    def test_success(self):
        r = SandboxResult(success=True, message="OK", tests_passed=3, tests_total=3)
        assert r.test_ratio  == "3/3"
        assert r.retry_count == 0

    def test_failure_with_retry(self):
        r = SandboxResult(success=False, message="SyntaxError", attempt=3)
        assert r.retry_count == 2

    def test_tests_passed_gt_total_raises(self):
        with pytest.raises(ValidationError) as exc:
            SandboxResult(success=True, message="OK", tests_passed=5, tests_total=3)
        assert "tests_passed" in str(exc.value)

    def test_zero_tests_ok(self):
        r = SandboxResult(success=True, message="OK")
        assert r.test_ratio == "0/0"

    def test_attempt_zero_raises(self):
        with pytest.raises(ValidationError):
            SandboxResult(success=True, message="OK", attempt=0)

    def test_defaults(self):
        r = SandboxResult(success=True, message="OK")
        assert r.stdout == "" and r.stderr == ""
        assert r.mock_mode is False
        assert r.mock_libs == [] and r.risk_keywords == []


# ── AuditResult ──────────────────────────────────────────────

class TestAuditResult:
    def test_pass(self):
        r = AuditResult(verdict=AuditVerdict.PASS, score=87)
        assert r.passed is True

    def test_fail(self):
        r = AuditResult(verdict=AuditVerdict.FAIL, score=40)
        assert r.passed is False

    def test_skip_not_passed(self):
        r = AuditResult(verdict=AuditVerdict.SKIP, score=0)
        assert r.passed is False

    def test_score_above_100_raises(self):
        with pytest.raises(ValidationError):
            AuditResult(verdict=AuditVerdict.PASS, score=101)

    def test_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            AuditResult(verdict=AuditVerdict.FAIL, score=-1)

    def test_score_boundaries_ok(self):
        AuditResult(verdict=AuditVerdict.FAIL, score=0)
        AuditResult(verdict=AuditVerdict.PASS, score=100)

    def test_factory_skipped(self):
        r = AuditResult.skipped("rate limit")
        assert r.verdict     == AuditVerdict.SKIP
        assert r.skip_reason == "rate limit"
        assert r.score       == 0

    def test_factory_failed(self):
        r = AuditResult.failed(score=35, issues=["nincs logging", "nincs type hint"])
        assert r.verdict     == AuditVerdict.FAIL
        assert r.score       == 35
        assert len(r.issues) == 2

    def test_telegram_summary_pass_contains_score(self):
        msg = AuditResult(verdict=AuditVerdict.PASS, score=91).telegram_summary
        assert "91" in msg and "PASS" in msg and "✅" in msg

    def test_telegram_summary_fail_shows_first_issue(self):
        msg = AuditResult(
            verdict=AuditVerdict.FAIL, score=42,
            issues=["Hiányzó error handling"]
        ).telegram_summary
        assert "Hiányzó error handling" in msg

    def test_telegram_summary_skip_shows_reason(self):
        msg = AuditResult.skipped("API timeout").telegram_summary
        assert "API timeout" in msg


# ── PipelineResult ───────────────────────────────────────────

class TestPipelineResult:
    def _task(self):
        return Task(text="teszt", chat_id="42", pipeline=Pipeline.DEVELOPER)

    def test_cache_hit_fully_passed(self):
        r = PipelineResult(
            task=self._task(), pipeline=Pipeline.DEVELOPER,
            success=True, output="cached", cache_hit=True,
        )
        assert r.fully_passed is True

    def test_fully_passed_both_ok(self):
        r = PipelineResult(
            task=self._task(), pipeline=Pipeline.DEVELOPER, success=True, output="x",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=88),
        )
        assert r.fully_passed is True

    def test_fully_passed_false_sandbox_fail(self):
        r = PipelineResult(
            task=self._task(), pipeline=Pipeline.DEVELOPER, success=False, output="",
            sandbox=SandboxResult(success=False, message="FAIL"),
            audit=AuditResult(verdict=AuditVerdict.PASS, score=90),
        )
        assert r.fully_passed is False

    def test_fully_passed_false_audit_fail(self):
        r = PipelineResult(
            task=self._task(), pipeline=Pipeline.DEVELOPER, success=True, output="x",
            sandbox=SandboxResult(success=True, message="OK"),
            audit=AuditResult(verdict=AuditVerdict.FAIL, score=30),
        )
        assert r.fully_passed is False

    def test_duration_non_negative(self):
        r = PipelineResult(
            task=self._task(), pipeline=Pipeline.DEVELOPER,
            success=True, output="x",
        )
        assert r.duration_seconds >= 0.0

    def test_negative_cost_raises(self):
        with pytest.raises(ValidationError):
            PipelineResult(
                task=self._task(), pipeline=Pipeline.DEVELOPER,
                success=True, output="x", cost_usd=-0.001,
            )

    def test_negative_tokens_raises(self):
        with pytest.raises(ValidationError):
            PipelineResult(
                task=self._task(), pipeline=Pipeline.DEVELOPER,
                success=True, output="x", tokens_in=-1,
            )


# ── HistoryTurn ──────────────────────────────────────────────

class TestHistoryTurn:
    def test_valid_user_turn(self):
        t = HistoryTurn(role=Role.USER, content="Írj kódot", pipeline=Pipeline.DEVELOPER)
        assert t.char_count == len("Írj kódot")
        assert t.task is None

    def test_assistant_turn_with_task(self):
        t = HistoryTurn(
            role=Role.ASSISTANT, content="print('hi')",
            pipeline=Pipeline.DEVELOPER, task="hello world",
        )
        assert t.task == "hello world"

    def test_to_claude_message(self):
        t = HistoryTurn(role=Role.USER, content="feladat", pipeline=Pipeline.DEVELOPER)
        assert t.to_claude_message() == {"role": "user", "content": "feladat"}

    def test_empty_content_raises(self):
        with pytest.raises(ValidationError):
            HistoryTurn(role=Role.USER, content="", pipeline=Pipeline.DEVELOPER)

    def test_whitespace_content_raises(self):
        with pytest.raises(ValidationError):
            HistoryTurn(role=Role.USER, content="   ", pipeline=Pipeline.DEVELOPER)

    def test_ts_auto_positive(self):
        t = HistoryTurn(role=Role.USER, content="x", pipeline=Pipeline.DEVELOPER)
        assert t.ts > 0


# ── CostEntry ────────────────────────────────────────────────

class TestCostEntry:
    def test_total_tokens(self):
        c = CostEntry(task="x", input_tok=1000, output_tok=500, cost_usd=0.002)
        assert c.total_tokens == 1500

    def test_default_pipeline_developer(self):
        c = CostEntry(task="x", input_tok=100, output_tok=50, cost_usd=0.001)
        assert c.pipeline == Pipeline.DEVELOPER

    def test_negative_input_tok_raises(self):
        with pytest.raises(ValidationError):
            CostEntry(task="x", input_tok=-1, output_tok=50, cost_usd=0.001)

    def test_negative_cost_raises(self):
        with pytest.raises(ValidationError):
            CostEntry(task="x", input_tok=100, output_tok=50, cost_usd=-0.001)

    def test_date_format(self):
        c = CostEntry(task="x", input_tok=100, output_tok=50, cost_usd=0.001)
        assert len(c.date) == 10
        parts = c.date.split("-")
        assert len(parts) == 3


# ── FixSample ────────────────────────────────────────────────

class TestFixSample:
    def test_list_issues(self):
        f = FixSample(bad_code="b", gemini_issues=["issue1", "issue2"], fixed_code="f")
        assert len(f.gemini_issues) == 2

    def test_string_issues_auto_list(self):
        f = FixSample(bad_code="b", gemini_issues="egyetlen hiba", fixed_code="f")
        assert f.gemini_issues == ["egyetlen hiba"]

    def test_abstract_lesson(self):
        f = FixSample(
            bad_code="b", gemini_issues=["i"], fixed_code="f",
            abstract_lesson="Mindig definiáld a változót",
        )
        assert "definiáld" in f.abstract_lesson

    def test_fix_succeeded_default_true(self):
        f = FixSample(bad_code="b", gemini_issues=["i"], fixed_code="f")
        assert f.fix_succeeded is True

    def test_score_above_100_raises(self):
        with pytest.raises(ValidationError):
            FixSample(bad_code="b", gemini_issues=["i"], fixed_code="f", bad_score=101)


# ── SystemStatus ─────────────────────────────────────────────

class TestSystemStatus:
    def test_normal_icons(self):
        s = SystemStatus(cpu_percent=45.0, ram_percent=60.0, disk_percent=55.0)
        assert s.cpu_icon  == "📊"
        assert s.ram_icon  == "🧠"
        assert s.disk_icon == "💾"

    def test_high_load_icons(self):
        s = SystemStatus(cpu_percent=85.0, ram_percent=85.0, disk_percent=95.0)
        assert s.cpu_icon  == "🔥"
        assert s.ram_icon  == "🔥"
        assert s.disk_icon == "🔥"

    def test_cpu_boundary_80_is_hot(self):
        s = SystemStatus(cpu_percent=80.0, ram_percent=0.0, disk_percent=0.0)
        assert s.cpu_icon == "🔥"

    def test_cpu_79_9_is_normal(self):
        s = SystemStatus(cpu_percent=79.9, ram_percent=0.0, disk_percent=0.0)
        assert s.cpu_icon == "📊"

    def test_above_100_raises(self):
        with pytest.raises(ValidationError):
            SystemStatus(cpu_percent=101.0, ram_percent=50.0, disk_percent=50.0)

    def test_negative_raises(self):
        with pytest.raises(ValidationError):
            SystemStatus(cpu_percent=-1.0, ram_percent=50.0, disk_percent=50.0)
