"""
AXON Neural Bridge — CLI Wrapper
=================================
v9.0

A DEVELOPER pipeline parancssoros entry pointja. A Telegram bot mellett
fut, ugyanazt az AppContext + DeveloperPipeline kódot használja
(coexistence — bot változatlan).

Használat:
  python cli.py "Írj egy CSV merger scriptet"
  python cli.py --json "..."
  python cli.py --quiet "..."
  python cli.py --no-output-file "..."
  python cli.py --chat-id mysession "..."
  python cli.py --yes "..."                # risk auto-approve
  python cli.py --task-file feladat.txt
  cat feladat.txt | python cli.py

Exit kódok:
  0  success + sandbox/audit PASS
  1  pipeline futott, de success=False (vagy nem fully_passed)
  2  config / IO hiba
  3  kockázatos kód visszautasítva
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from dotenv import load_dotenv

from models import Pipeline, Task

log = logging.getLogger("AXON.CLI")

DEFAULT_CHAT_ID = "cli"


# ── Argparse ─────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="axon-cli",
        description="AXON Neural Bridge — DEVELOPER pipeline CLI",
    )
    p.add_argument(
        "task", nargs="?", default=None,
        help="A feladat szövege. Ha hiányzik, --task-file vagy stdin.",
    )
    p.add_argument(
        "--task-file", type=Path, default=None,
        help="Feladat fájlból olvasva (UTF-8).",
    )
    p.add_argument(
        "--chat-id", default=DEFAULT_CHAT_ID,
        help=f"History namespace (default: {DEFAULT_CHAT_ID!r}).",
    )
    p.add_argument(
        "--json", action="store_true", dest="as_json",
        help="PipelineResult JSON-ben stdoutra (pipeable).",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Status üzenetek elnyomása stderr-en.",
    )
    p.add_argument(
        "--no-output-file", action="store_true",
        help="Ne írjon outputs/ alá .py + README-t (csak stdout).",
    )
    risk = p.add_mutually_exclusive_group()
    risk.add_argument(
        "--yes", action="store_true",
        help="Kockázati keyword esetén auto-approve.",
    )
    risk.add_argument(
        "--no-interactive", action="store_true",
        help="Ne kérdezzen rá; kockázatos kódot automatikusan elutasít.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="DEBUG szintű logging stderr-re.",
    )
    return p


# ── Task input resolution ────────────────────────────────────────

def resolve_task_text(args: argparse.Namespace) -> str:
    """Pozícionális arg → --task-file → stdin (ha pipe)."""
    if args.task:
        return args.task.strip()
    if args.task_file:
        return args.task_file.read_text(encoding="utf-8").strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError(
        "Nincs feladat megadva. Használj pozícionális argumentumot, "
        "--task-file kapcsolót, vagy pipe-old be stdin-en."
    )


# ── Callbacks ────────────────────────────────────────────────────

def make_status_cb(quiet: bool) -> Callable[[str], Awaitable[None]]:
    """Pipeline → stderr (vagy noop ha --quiet)."""
    async def status_cb(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr, flush=True)
    return status_cb


def make_risk_approval(
    auto_yes: bool, no_interactive: bool, quiet: bool
) -> Callable[[list[str], str], Awaitable[bool]] | None:
    """Risk-keyword approval callback. None → pipeline auto-rejects risky code."""
    if no_interactive:
        return None  # pipeline tagadja a kockázatos kódot

    async def risk_approval(risks: list[str], request_id: str) -> bool:
        if auto_yes:
            if not quiet:
                print(
                    f"⚠️  [{request_id}] Risky keywords auto-approved: {risks}",
                    file=sys.stderr,
                )
            return True

        loop = asyncio.get_running_loop()
        prompt = (
            f"\n⚠️  Kockázatos keyword(ök) észlelve: {risks}\n"
            f"   Request ID: {request_id}\n"
            f"   Engedélyezed? [y/N]: "
        )
        # Sync stdin read executor-ban, hogy ne blokkolja az event loop-ot
        answer = await loop.run_in_executor(
            None, lambda: _prompt_yn(prompt)
        )
        return answer

    return risk_approval


def _prompt_yn(prompt: str) -> bool:
    print(prompt, file=sys.stderr, end="", flush=True)
    try:
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return False
    return line.strip().lower() in ("y", "yes", "i", "igen")


# ── Output rendering ─────────────────────────────────────────────

def render_result(result, as_json: bool, no_output_file: bool, quiet: bool) -> None:
    """PipelineResult → stdout (kód vagy JSON) + stderr summary."""
    if as_json:
        # Pydantic v2: model_dump_json
        print(result.model_dump_json(indent=2))
        return

    # Plain mode: kód/szöveg stdoutra, summary stderrre
    print(result.output)

    if not quiet:
        summary_parts = []
        if result.sandbox is not None:
            sb = result.sandbox
            summary_parts.append(
                f"sandbox: {'PASS' if sb.success else 'FAIL'} "
                f"{sb.tests_passed}/{sb.tests_total}"
            )
        if result.audit is not None:
            au = result.audit
            summary_parts.append(f"audit: {au.verdict.value} {au.score}/100")
        if result.cache_hit:
            summary_parts.append("cache: HIT")
        summary_parts.append(f"${result.cost_usd:.4f}")
        summary_parts.append(f"{result.duration_seconds:.1f}s")
        if result.output_file:
            summary_parts.append(f"file: {result.output_file}")
        print("# " + " | ".join(summary_parts), file=sys.stderr)


def compute_exit_code(result) -> int:
    if not result.success:
        # A pipeline a 'visszautasítva' szöveggel jelzi a risk-rejectet
        if "visszautasítva" in (result.output or "").lower():
            return 3
        return 1
    if not result.fully_passed:
        return 1
    return 0


# ── Lifecycle ────────────────────────────────────────────────────

async def run_cli(args: argparse.Namespace) -> int:
    # Lazy import — csak a CLI futás közben kell, és így gyorsabb a --help
    from main import AppContext, Config

    base_dir = Path(__file__).parent
    load_dotenv(dotenv_path=base_dir / ".env")

    try:
        config = Config.from_env(base_dir)
    except ValueError as e:
        log.critical(f"Konfiguráció hiba: {e}")
        return 2

    try:
        task_text = resolve_task_text(args)
    except ValueError as e:
        log.critical(str(e))
        return 2

    ctx = AppContext(config)

    try:
        await ctx.initialize()

        # History visszatöltés a CLI chat_id-hez (multi-turn folytonosság)
        try:
            from axon_memory import restore_history
            restore_history(args.chat_id)
        except Exception as e:
            log.debug(f"History restore skip: {e}")

        pipeline = ctx.build_developer_pipeline()

        task = Task(
            text=task_text,
            chat_id=args.chat_id,
            pipeline=Pipeline.DEVELOPER,
        )

        status_cb = make_status_cb(args.quiet)
        risk_cb = make_risk_approval(
            auto_yes=args.yes,
            no_interactive=args.no_interactive,
            quiet=args.quiet,
        )

        result = await pipeline.run(task, status_cb, risk_approval=risk_cb)

        # --no-output-file: ha tényleg írt fájlt az OutputWriter, töröljük
        if args.no_output_file:
            for path_attr in ("output_file", "readme_file"):
                fp = getattr(result, path_attr, None)
                if fp:
                    try:
                        Path(fp).unlink(missing_ok=True)
                    except Exception as e:
                        log.warning(f"Cleanup hiba ({fp}): {e}")

        render_result(result, args.as_json, args.no_output_file, args.quiet)

        # CLI chat_id history mentése a következő futáshoz
        try:
            from axon_memory import persist_history, get_history_turn_count
            if get_history_turn_count(args.chat_id) > 0:
                persist_history(args.chat_id)
        except Exception as e:
            log.debug(f"History persist skip: {e}")

        return compute_exit_code(result)

    finally:
        try:
            await ctx.shutdown()
        except Exception as e:
            log.debug(f"Shutdown hiba (nem kritikus): {e}")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        return asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        print("\n⛔ Megszakítva.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
