"""
tests/test_pipeline.py — AXON v9.0 pipeline unit tesztek
Lefedés: helper függvények, CodeGenerator, AuditFixLoop, CostAccumulator.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock

from models import (
    AuditResult, AuditVerdict,
    Pipeline, Task, TaskComplexity,
)
from core.pipeline import (
    _extract_code_block, _build_pattern_block, _build_fix_block,
    AuditFixLoop, CodeGenerator, CostAccumulator, OutputWriter,
)


# ══════════════════════════════════════════════════════════════
#  HELPER: _extract_code_block
# ══════════════════════════════════════════════════════════════

class TestExtractCodeBlock:
    def test_python_fenced_block(self):
        assert _extract_code_block("```python\nprint('hi')\n```") == "print('hi')"

    def test_plain_fenced_block(self):
        assert _extract_code_block("```\nsome code\n```") == "some code"

    def test_no_block_returns_none(self):
        assert _extract_code_block("nincs kód blokk") is None

    def test_empty_string_returns_none(self):
        assert _extract_code_block("") is None

    def test_none_returns_none(self):
        assert _extract_code_block(None) is None

    def test_multiline_preserved(self):
        code = "def foo():\n    return 42"
        assert _extract_code_block(f"```python\n{code}\n```") == code

    def test_whitespace_stripped(self):
        assert _extract_code_block("```python\n\n  x = 1  \n\n```") == "x = 1"

    def test_prefers_python_over_plain(self):
        text = "```python\nprint('py')\n```\n\n```\nplain\n```"
        assert _extract_code_block(text) == "print('py')"

    def test_code_with_single_quotes(self):
        text = "```python\nx = 'hello'\n```"
        assert _extract_code_block(text) == "x = 'hello'"


# ══════════════════════════════════════════════════════════════
#  HELPER: _build_pattern_block
# ══════════════════════════════════════════════════════════════

class TestBuildPatternBlock:
    def test_empty_returns_empty(self):
        assert _build_pattern_block([]) == ""

    def test_single_pattern_contains_fields(self):
        result = _build_pattern_block([
            {"similarity": 0.85, "prompt": "CSV beolvasás", "code_snippet": "import csv"}
        ])
        assert "CSV beolvasás" in result
        assert "import csv"    in result
        assert "85%"           in result

    def test_multiple_patterns_all_present(self):
        result = _build_pattern_block([
            {"similarity": 0.9,  "prompt": "feladat1", "code_snippet": "kod1"},
            {"similarity": 0.75, "prompt": "feladat2", "code_snippet": "kod2"},
        ])
        assert "feladat1" in result and "feladat2" in result
        assert "kod1"     in result and "kod2"     in result

    def test_ends_with_newline(self):
        result = _build_pattern_block([{"similarity": 0.8, "prompt": "p", "code_snippet": "c"}])
        assert result.endswith("\n")


# ══════════════════════════════════════════════════════════════
#  HELPER: _build_fix_block
# ══════════════════════════════════════════════════════════════

class TestBuildFixBlock:
    def test_empty_returns_empty(self):
        assert _build_fix_block([]) == ""

    def test_single_sample_contains_fields(self):
        result = _build_fix_block([{
            "score": 0.9, "prompt": "feladat",
            "bad_code": "bad", "issues": ["hiba1"], "fixed_code": "fixed",
        }])
        assert "bad"   in result
        assert "fixed" in result
        assert "hiba1" in result

    def test_json_string_issues_handled(self):
        import json
        result = _build_fix_block([{
            "score": 0.8, "prompt": "p", "bad_code": "b",
            "issues": json.dumps(["iss1", "iss2"]), "fixed_code": "f",
        }])
        assert "iss1" in result

    def test_invalid_json_issues_no_crash(self):
        result = _build_fix_block([{
            "score": 0.7, "prompt": "p", "bad_code": "b",
            "issues": "not_json_{broken", "fixed_code": "f",
        }])
        assert len(result) > 0

    def test_ends_with_newline(self):
        result = _build_fix_block([{
            "score": 0.8, "prompt": "p", "bad_code": "b",
            "issues": ["i"], "fixed_code": "f",
        }])
        assert result.endswith("\n")


# ══════════════════════════════════════════════════════════════
#  CODE GENERATOR — komplexitás becslés
# ══════════════════════════════════════════════════════════════

def _make_task() -> Task:
    return Task(text="Írj Python kódot", chat_id="1", pipeline=Pipeline.DEVELOPER)


def _make_generator(response: str) -> CodeGenerator:
    return CodeGenerator(
        call_claude_tracked=AsyncMock(return_value=response),
        pipeline_prompt="system",
    )


class TestCodeGeneratorComplexity:

    @pytest.mark.asyncio
    async def test_simple_response(self):
        gen = _make_generator("COMPLEXITY: SIMPLE")
        assert await gen.estimate_complexity(_make_task(), AsyncMock()) == TaskComplexity.SIMPLE

    @pytest.mark.asyncio
    async def test_complex_response(self):
        gen = _make_generator("COMPLEXITY: COMPLEX\nPLAN:\n1. a\n2. b")
        assert await gen.estimate_complexity(_make_task(), AsyncMock()) == TaskComplexity.COMPLEX

    @pytest.mark.asyncio
    async def test_ambiguous_defaults_simple(self):
        gen = _make_generator("Nem tudom.")
        assert await gen.estimate_complexity(_make_task(), AsyncMock()) == TaskComplexity.SIMPLE

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        gen = _make_generator("complexity: complex")
        assert await gen.estimate_complexity(_make_task(), AsyncMock()) == TaskComplexity.COMPLEX

    @pytest.mark.asyncio
    async def test_false_positive_protection(self):
        # "COMPLEXITY: COMPLEX" csak önálló sorban triggerel, nem ha szövegben van
        gen = _make_generator("Ez a feladat nem COMPLEXITY: COMPLEX szintű, inkább SIMPLE.")
        assert await gen.estimate_complexity(_make_task(), AsyncMock()) == TaskComplexity.SIMPLE

    @pytest.mark.asyncio
    async def test_status_callback_called(self):
        gen    = _make_generator("COMPLEXITY: SIMPLE")
        status = AsyncMock()
        await gen.estimate_complexity(_make_task(), status)
        status.assert_called_once()


class TestCodeGeneratorSimple:

    @pytest.mark.asyncio
    async def test_with_tests_returned(self):
        gen = CodeGenerator(
            call_claude_tracked=AsyncMock(side_effect=[
                "```python\n# === KÓD ===\nprint('hello')\n```",
                "```python\n# === KÓD ===\nprint('hello')\n\n# === TESZTEK ===\nif __name__ == '__test__':\n    assert True\n    print('TESZTEK OK')\n```",
            ]),
            pipeline_prompt="sys",
        )
        result = await gen.generate_simple(_make_task(), "", "", AsyncMock())
        assert "# === TESZTEK ===" in result
        assert "print('hello')"   in result

    @pytest.mark.asyncio
    async def test_fallback_when_no_tests(self):
        gen = CodeGenerator(
            call_claude_tracked=AsyncMock(side_effect=[
                "```python\nprint('hi')\n```",
                "Sajnos nem tudok tesztet írni.",
            ]),
            pipeline_prompt="sys",
        )
        result = await gen.generate_simple(_make_task(), "", "", AsyncMock())
        assert "# === TESZTEK ===" in result
        assert "fallback"          in result

    @pytest.mark.asyncio
    async def test_exactly_two_calls(self):
        mock = AsyncMock(side_effect=[
            "```python\nkod\n```",
            "```python\n# === KÓD ===\nkod\n\n# === TESZTEK ===\nif __name__ == '__test__':\n    assert True\n    print('TESZTEK OK')\n```",
        ])
        gen = CodeGenerator(call_claude_tracked=mock, pipeline_prompt="sys")
        await gen.generate_simple(_make_task(), "", "", AsyncMock())
        assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_history_context_in_prompt(self):
        mock = AsyncMock(side_effect=[
            "```python\nkod\n```",
            "```python\n# === KÓD ===\nkod\n\n# === TESZTEK ===\nif __name__ == '__test__':\n    assert True\n    print('TESZTEK OK')\n```",
        ])
        gen = CodeGenerator(call_claude_tracked=mock, pipeline_prompt="sys")
        ctx = "KONTEXTUS – előző kód:\n```python\nx = 1\n```\n\n"
        await gen.generate_simple(_make_task(), ctx, "", AsyncMock())
        first_prompt = mock.call_args_list[0].kwargs["user_msg"]
        assert "KONTEXTUS" in first_prompt

    @pytest.mark.asyncio
    async def test_few_shot_in_prompt(self):
        mock = AsyncMock(side_effect=[
            "```python\nkod\n```",
            "```python\n# === KÓD ===\nkod\n\n# === TESZTEK ===\nif __name__ == '__test__':\n    assert True\n    print('TESZTEK OK')\n```",
        ])
        gen = CodeGenerator(call_claude_tracked=mock, pipeline_prompt="sys")
        await gen.generate_simple(_make_task(), "", "TANULÁS – minták\n", AsyncMock())
        first_prompt = mock.call_args_list[0].kwargs["user_msg"]
        assert "TANULÁS" in first_prompt


# ══════════════════════════════════════════════════════════════
#  AUDIT FIX LOOP
# ══════════════════════════════════════════════════════════════

def _make_fix_loop(sandbox_success=True, audit_pass=True) -> tuple[AuditFixLoop, MagicMock]:
    save_fn = MagicMock()

    mock_sandbox_result          = MagicMock()
    mock_sandbox_result.success  = sandbox_success
    mock_sandbox_result.final_code = "fixed_code"
    mock_sandbox_result.stderr   = ""

    mock_sandbox = MagicMock()
    mock_sandbox.validate_with_retry = AsyncMock(return_value=mock_sandbox_result)

    mock_audit_result         = MagicMock()
    mock_audit_result.passed  = audit_pass
    mock_audit_result.verdict = AuditVerdict.PASS if audit_pass else AuditVerdict.FAIL
    mock_audit_result.issues  = [] if audit_pass else ["issue1"]
    mock_audit_result.score   = 90 if audit_pass else 40

    mock_auditor      = MagicMock()
    mock_auditor.audit = AsyncMock(return_value=mock_audit_result)

    loop = AuditFixLoop(
        call_claude=AsyncMock(return_value="```python\nfixed\n```"),
        sandbox=mock_sandbox,
        auditor=mock_auditor,
        save_fix_sample=save_fn,
        format_audit_for_fix=MagicMock(return_value="fix prompt"),
    )
    return loop, save_fn


def _passing_audit() -> AuditResult:
    return AuditResult(verdict=AuditVerdict.PASS, score=90)

def _failing_audit() -> AuditResult:
    return AuditResult(verdict=AuditVerdict.FAIL, score=35, issues=["Nincs error handling"])

def _make_sandbox_mock(success=True):
    r = MagicMock()
    r.success    = success
    r.final_code = "code"
    r.stderr     = ""
    return r


class TestAuditFixLoop:

    @pytest.mark.asyncio
    async def test_pass_no_fix(self):
        loop, _ = _make_fix_loop()
        code, audit, _ = await loop.run(
            task=_make_task(), validated_code="original",
            audit_result=_passing_audit(), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=AsyncMock(),
        )
        assert code  == "original"
        assert audit == _passing_audit()

    @pytest.mark.asyncio
    async def test_skip_no_fix(self):
        loop, _ = _make_fix_loop()
        code, _, _ = await loop.run(
            task=_make_task(), validated_code="code",
            audit_result=AuditResult.skipped("timeout"), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=AsyncMock(),
        )
        assert code == "code"

    @pytest.mark.asyncio
    async def test_fail_triggers_fix(self):
        loop, _ = _make_fix_loop(audit_pass=True)
        code, audit, _ = await loop.run(
            task=_make_task(), validated_code="bad_code",
            audit_result=_failing_audit(), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=AsyncMock(),
        )
        assert code          == "fixed_code"
        assert audit.passed  is True

    @pytest.mark.asyncio
    async def test_fix_sample_saved(self):
        loop, save_fn = _make_fix_loop(audit_pass=True)
        await loop.run(
            task=_make_task(), validated_code="bad",
            audit_result=_failing_audit(), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=AsyncMock(),
        )
        save_fn.assert_called_once()
        assert save_fn.call_args[1]["fix_succeeded"] is True

    @pytest.mark.asyncio
    async def test_status_cb_called_during_fix(self):
        loop, _ = _make_fix_loop(audit_pass=True)
        status  = AsyncMock()
        await loop.run(
            task=_make_task(), validated_code="bad",
            audit_result=_failing_audit(), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=status,
        )
        assert status.call_count >= 1

    @pytest.mark.asyncio
    async def test_sandbox_fail_during_fix_saves_failed_sample(self):
        """Ha sandbox a fix után is FAIL → save_fix_sample(fix_succeeded=False)."""
        loop, save_fn = _make_fix_loop(sandbox_success=False, audit_pass=False)
        await loop.run(
            task=_make_task(), validated_code="bad",
            audit_result=_failing_audit(), sandbox_result=_make_sandbox_mock(),
            few_shot_builder=lambda e: "",
            ai_fix_callback=AsyncMock(), status_cb=AsyncMock(),
        )
        save_fn.assert_called_once()
        assert save_fn.call_args[1]["fix_succeeded"] is False


# ══════════════════════════════════════════════════════════════
#  COST ACCUMULATOR
# ══════════════════════════════════════════════════════════════

class TestCostAccumulator:

    def _make(self, tokens: dict, cost: float) -> CostAccumulator:
        return CostAccumulator(
            pop_tokens_fn=MagicMock(return_value=tokens),
            tokens_to_usd_fn=MagicMock(return_value=cost),
            log_cost_fn=MagicMock(),
        )

    def test_returns_cost_and_tokens(self):
        tokens = {"input": 1000, "output": 500, "calls": 3}
        acc    = self._make(tokens, 0.0035)
        cost, result_tokens = acc.finalize(_make_task())
        assert cost          == pytest.approx(0.0035)
        assert result_tokens == tokens

    def test_log_cost_called_correctly(self):
        log_fn = MagicMock()
        acc    = CostAccumulator(
            pop_tokens_fn=MagicMock(return_value={"input": 200, "output": 100, "calls": 1}),
            tokens_to_usd_fn=MagicMock(return_value=0.001),
            log_cost_fn=log_fn,
        )
        acc.finalize(_make_task())
        log_fn.assert_called_once_with(
            task="Írj Python kódot",
            input_tokens=200, output_tokens=100,
            cost_usd=0.001, calls=1,
        )

    def test_pop_called_with_chat_id(self):
        pop = MagicMock(return_value={"input": 0, "output": 0, "calls": 0})
        acc = CostAccumulator(
            pop_tokens_fn=pop,
            tokens_to_usd_fn=MagicMock(return_value=0.0),
            log_cost_fn=MagicMock(),
        )
        acc.finalize(_make_task())
        pop.assert_called_once_with("1")

    def test_zero_cost_valid(self):
        acc     = self._make({"input": 0, "output": 0, "calls": 0}, 0.0)
        cost, _ = acc.finalize(_make_task())
        assert cost == 0.0

    def test_discard_pops_tokens_without_logging(self):
        pop    = MagicMock(return_value={"input": 500, "output": 200, "calls": 2})
        log_fn = MagicMock()
        acc    = CostAccumulator(
            pop_tokens_fn=pop,
            tokens_to_usd_fn=MagicMock(return_value=0.01),
            log_cost_fn=log_fn,
        )
        acc.discard(_make_task())
        pop.assert_called_once_with("1")
        log_fn.assert_not_called()


# ══════════════════════════════════════════════════════════════
#  OUTPUT WRITER
# ══════════════════════════════════════════════════════════════

class TestOutputWriter:

    def _make_writer(self, tmp_path) -> OutputWriter:
        return OutputWriter(
            output_dir=tmp_path,
            generate_readme_fn=AsyncMock(return_value="📄 `readme.md`"),
        )

    def _make_audit(self, passed=True) -> AuditResult:
        return AuditResult(
            verdict=AuditVerdict.PASS if passed else AuditVerdict.FAIL,
            score=90 if passed else 40,
        )

    def _make_sandbox(self, success=True):
        r = MagicMock()
        r.success = success
        return r

    def test_write_returns_four_tuple(self, tmp_path):
        writer = self._make_writer(tmp_path)
        result = writer.write(_make_task(), "print('hi')", self._make_sandbox(), self._make_audit())
        assert len(result) == 4

    def test_write_filename_contains_timestamp_and_task(self, tmp_path):
        writer = self._make_writer(tmp_path)
        _, filename, timestamp, safe_task = writer.write(
            _make_task(), "print('hi')", self._make_sandbox(), self._make_audit()
        )
        assert timestamp in filename
        assert safe_task in filename
        assert filename.endswith(".py")

    def test_write_timestamp_and_safe_task_consistent(self, tmp_path):
        writer = self._make_writer(tmp_path)
        _, filename, timestamp, safe_task = writer.write(
            _make_task(), "x = 1", self._make_sandbox(), self._make_audit()
        )
        assert filename == f"{timestamp}_{safe_task}.py"

    def test_write_creates_file(self, tmp_path):
        writer = self._make_writer(tmp_path)
        filepath, _, _, _ = writer.write(
            _make_task(), "x = 1", self._make_sandbox(), self._make_audit()
        )
        assert Path(filepath).exists()

    def test_write_file_contains_code(self, tmp_path):
        writer  = self._make_writer(tmp_path)
        code    = "def hello():\n    return 42"
        filepath, _, _, _ = writer.write(
            _make_task(), code, self._make_sandbox(), self._make_audit()
        )
        content = Path(filepath).read_text(encoding="utf-8")
        assert "def hello():" in content

    def test_write_header_sandbox_pass(self, tmp_path):
        writer   = self._make_writer(tmp_path)
        filepath, _, _, _ = writer.write(
            _make_task(), "x=1", self._make_sandbox(success=True), self._make_audit()
        )
        assert "Sandbox: PASS" in Path(filepath).read_text(encoding="utf-8")

    def test_write_header_sandbox_fail(self, tmp_path):
        writer   = self._make_writer(tmp_path)
        filepath, _, _, _ = writer.write(
            _make_task(), "x=1", self._make_sandbox(success=False), self._make_audit(passed=False)
        )
        assert "Sandbox: FAIL" in Path(filepath).read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_write_readme_returns_string(self, tmp_path):
        writer = self._make_writer(tmp_path)
        result = await writer.write_readme(
            task=_make_task(), main_code="x=1", filename="test.py",
            timestamp="20260506_120000", safe_task="test_task",
            audit_result=self._make_audit(), sandbox_result=self._make_sandbox(),
        )
        assert isinstance(result, str)
