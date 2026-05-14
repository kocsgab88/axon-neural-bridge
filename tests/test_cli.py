"""
tests/test_cli.py — cli.py unit tesztek.

Lefedés: argparse, task input resolution, status/risk callbacks,
output rendering, exit code mapping, end-to-end run_cli mockolva.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import asyncio
import io
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cli
from models import (
    AuditResult, AuditVerdict,
    Pipeline, PipelineResult, SandboxResult, Task,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def base_task():
    return Task(text="dummy", chat_id="cli", pipeline=Pipeline.DEVELOPER)


@pytest.fixture
def passing_result(base_task):
    return PipelineResult(
        task=base_task, pipeline=Pipeline.DEVELOPER, success=True,
        output="print('hi')",
        sandbox=SandboxResult(success=True, message="ok", tests_passed=3, tests_total=3),
        audit=AuditResult(verdict=AuditVerdict.PASS, score=92),
        cost_usd=0.0123, tokens_in=1000, tokens_out=500, api_calls=2,
    )


@pytest.fixture
def failing_result(base_task):
    return PipelineResult(
        task=base_task, pipeline=Pipeline.DEVELOPER, success=False,
        output="❌ Kód generálás sikertelen.",
    )


@pytest.fixture
def risk_rejected_result(base_task):
    return PipelineResult(
        task=base_task, pipeline=Pipeline.DEVELOPER, success=False,
        output="⛔ Kockázatos kód – visszautasítva.",
    )


# ══════════════════════════════════════════════════════════════
#  build_parser
# ══════════════════════════════════════════════════════════════

class TestBuildParser:
    def test_positional_task(self):
        args = cli.build_parser().parse_args(["hello world"])
        assert args.task == "hello world"
        assert args.chat_id == cli.DEFAULT_CHAT_ID
        assert args.as_json is False
        assert args.quiet is False
        assert args.yes is False
        assert args.no_interactive is False

    def test_json_flag(self):
        args = cli.build_parser().parse_args(["--json", "task"])
        assert args.as_json is True

    def test_chat_id_override(self):
        args = cli.build_parser().parse_args(["--chat-id", "session-42", "task"])
        assert args.chat_id == "session-42"

    def test_yes_and_no_interactive_mutex(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["--yes", "--no-interactive", "task"])

    def test_task_file(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("from file", encoding="utf-8")
        args = cli.build_parser().parse_args(["--task-file", str(f)])
        assert args.task_file == f

    def test_no_task_optional(self):
        args = cli.build_parser().parse_args([])
        assert args.task is None


# ══════════════════════════════════════════════════════════════
#  resolve_task_text
# ══════════════════════════════════════════════════════════════

class TestResolveTaskText:
    def _ns(self, **kw):
        defaults = dict(task=None, task_file=None)
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_positional_wins(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("ignored"))
        ns = self._ns(task="  hello  ")
        assert cli.resolve_task_text(ns) == "hello"

    def test_task_file(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("  feladat\n", encoding="utf-8")
        ns = self._ns(task_file=f)
        assert cli.resolve_task_text(ns) == "feladat"

    def test_stdin_pipe(self, monkeypatch):
        fake_stdin = io.StringIO("piped task\n")
        fake_stdin.isatty = lambda: False  # type: ignore[method-assign]
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        ns = self._ns()
        assert cli.resolve_task_text(ns) == "piped task"

    def test_stdin_tty_raises(self, monkeypatch):
        fake_stdin = io.StringIO("")
        fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        ns = self._ns()
        with pytest.raises(ValueError, match="Nincs feladat"):
            cli.resolve_task_text(ns)


# ══════════════════════════════════════════════════════════════
#  Callbacks
# ══════════════════════════════════════════════════════════════

class TestStatusCb:
    @pytest.mark.asyncio
    async def test_quiet_silences(self, capsys):
        cb = cli.make_status_cb(quiet=True)
        await cb("status msg")
        out = capsys.readouterr()
        assert out.err == ""

    @pytest.mark.asyncio
    async def test_normal_writes_stderr(self, capsys):
        cb = cli.make_status_cb(quiet=False)
        await cb("status msg")
        out = capsys.readouterr()
        assert "status msg" in out.err


class TestRiskApproval:
    def test_no_interactive_returns_none(self):
        assert cli.make_risk_approval(
            auto_yes=False, no_interactive=True, quiet=False,
        ) is None

    @pytest.mark.asyncio
    async def test_auto_yes(self, capsys):
        cb = cli.make_risk_approval(auto_yes=True, no_interactive=False, quiet=False)
        assert cb is not None
        result = await cb(["os.system"], "abc123")
        assert result is True
        err = capsys.readouterr().err
        assert "auto-approved" in err

    @pytest.mark.asyncio
    async def test_interactive_yes(self, monkeypatch):
        cb = cli.make_risk_approval(auto_yes=False, no_interactive=False, quiet=True)
        assert cb is not None
        monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
        assert await cb(["exec("], "id1") is True

    @pytest.mark.asyncio
    async def test_interactive_no(self, monkeypatch):
        cb = cli.make_risk_approval(auto_yes=False, no_interactive=False, quiet=True)
        monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))
        assert await cb(["exec("], "id1") is False

    @pytest.mark.asyncio
    async def test_interactive_default_no(self, monkeypatch):
        """Üres input → False (biztonságos default)."""
        cb = cli.make_risk_approval(auto_yes=False, no_interactive=False, quiet=True)
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
        assert await cb(["exec("], "id1") is False

    @pytest.mark.asyncio
    async def test_interactive_hungarian_igen(self, monkeypatch):
        cb = cli.make_risk_approval(auto_yes=False, no_interactive=False, quiet=True)
        monkeypatch.setattr(sys, "stdin", io.StringIO("igen\n"))
        assert await cb(["exec("], "id1") is True


# ══════════════════════════════════════════════════════════════
#  render_result
# ══════════════════════════════════════════════════════════════

class TestRenderResult:
    def test_json_mode(self, passing_result, capsys):
        cli.render_result(passing_result, as_json=True, no_output_file=False, quiet=False)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["success"] is True
        assert parsed["output"] == "print('hi')"
        assert parsed["sandbox"]["success"] is True
        assert parsed["audit"]["verdict"] == "PASS"

    def test_plain_mode_outputs_code(self, passing_result, capsys):
        cli.render_result(passing_result, as_json=False, no_output_file=False, quiet=False)
        captured = capsys.readouterr()
        assert "print('hi')" in captured.out
        assert "sandbox: PASS 3/3" in captured.err
        assert "audit: PASS 92/100" in captured.err
        assert "$0.0123" in captured.err

    def test_quiet_suppresses_summary(self, passing_result, capsys):
        cli.render_result(passing_result, as_json=False, no_output_file=False, quiet=True)
        captured = capsys.readouterr()
        assert "print('hi')" in captured.out
        assert captured.err == ""

    def test_failing_result_no_sandbox_summary(self, failing_result, capsys):
        cli.render_result(failing_result, as_json=False, no_output_file=False, quiet=False)
        captured = capsys.readouterr()
        assert "Kód generálás sikertelen" in captured.out
        # Nincs sandbox/audit, de costs+duration igen
        assert "sandbox" not in captured.err
        assert "$0.0000" in captured.err


# ══════════════════════════════════════════════════════════════
#  compute_exit_code
# ══════════════════════════════════════════════════════════════

class TestExitCode:
    def test_success_passing(self, passing_result):
        assert cli.compute_exit_code(passing_result) == 0

    def test_failing(self, failing_result):
        assert cli.compute_exit_code(failing_result) == 1

    def test_risk_rejected(self, risk_rejected_result):
        assert cli.compute_exit_code(risk_rejected_result) == 3

    def test_success_but_sandbox_failed(self, base_task):
        r = PipelineResult(
            task=base_task, pipeline=Pipeline.DEVELOPER, success=True,
            output="x",
            sandbox=SandboxResult(success=False, message="bad", tests_passed=1, tests_total=3),
        )
        assert cli.compute_exit_code(r) == 1


# ══════════════════════════════════════════════════════════════
#  run_cli — integration with mocked AppContext
# ══════════════════════════════════════════════════════════════

class TestRunCli:
    def _args(self, **kw):
        defaults = dict(
            task="dummy task", task_file=None, chat_id="cli",
            as_json=False, quiet=True, no_output_file=False,
            yes=False, no_interactive=True, verbose=False,
        )
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    @pytest.mark.asyncio
    async def test_passing_run_returns_zero(self, passing_result):
        fake_ctx = MagicMock()
        fake_ctx.initialize = AsyncMock()
        fake_ctx.shutdown = AsyncMock()
        fake_pipeline = MagicMock()
        fake_pipeline.run = AsyncMock(return_value=passing_result)
        fake_ctx.build_developer_pipeline.return_value = fake_pipeline

        with patch("main.AppContext", return_value=fake_ctx), \
             patch("main.Config") as fake_config_cls:
            fake_config_cls.from_env.return_value = MagicMock()
            rc = await cli.run_cli(self._args())

        assert rc == 0
        fake_ctx.initialize.assert_awaited_once()
        fake_ctx.shutdown.assert_awaited_once()
        fake_pipeline.run.assert_awaited_once()
        # Task helyesen lett összerakva
        called_task = fake_pipeline.run.call_args.args[0]
        assert called_task.text == "dummy task"
        assert called_task.chat_id == "cli"
        assert called_task.pipeline == Pipeline.DEVELOPER

    @pytest.mark.asyncio
    async def test_config_error_returns_two(self):
        with patch("main.Config") as fake_config_cls:
            fake_config_cls.from_env.side_effect = ValueError("missing key")
            rc = await cli.run_cli(self._args())
        assert rc == 2

    @pytest.mark.asyncio
    async def test_failing_result_returns_one(self, failing_result):
        fake_ctx = MagicMock()
        fake_ctx.initialize = AsyncMock()
        fake_ctx.shutdown = AsyncMock()
        fake_pipeline = MagicMock()
        fake_pipeline.run = AsyncMock(return_value=failing_result)
        fake_ctx.build_developer_pipeline.return_value = fake_pipeline

        with patch("main.AppContext", return_value=fake_ctx), \
             patch("main.Config") as fake_config_cls:
            fake_config_cls.from_env.return_value = MagicMock()
            rc = await cli.run_cli(self._args())
        assert rc == 1

    @pytest.mark.asyncio
    async def test_no_output_file_unlinks_artifacts(self, tmp_path, base_task):
        py_file = tmp_path / "out.py"
        py_file.write_text("x = 1", encoding="utf-8")
        readme = tmp_path / "out_README.md"
        readme.write_text("# readme", encoding="utf-8")

        result = PipelineResult(
            task=base_task, pipeline=Pipeline.DEVELOPER, success=True,
            output="x = 1",
            output_file=str(py_file), readme_file=str(readme),
        )
        fake_ctx = MagicMock()
        fake_ctx.initialize = AsyncMock()
        fake_ctx.shutdown = AsyncMock()
        fake_pipeline = MagicMock()
        fake_pipeline.run = AsyncMock(return_value=result)
        fake_ctx.build_developer_pipeline.return_value = fake_pipeline

        with patch("main.AppContext", return_value=fake_ctx), \
             patch("main.Config") as fake_config_cls:
            fake_config_cls.from_env.return_value = MagicMock()
            rc = await cli.run_cli(self._args(no_output_file=True))

        assert rc == 0
        assert not py_file.exists()
        assert not readme.exists()
