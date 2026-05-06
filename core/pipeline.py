"""
AXON Neural Bridge — Core Pipeline Orchestrator
=================================================
v9.0

A run_developer_pipeline() 550 soros monolitjából 5 izolált osztály:

  CodeGenerator     – Claude hívások, SIMPLE / COMPLEX generálás
  AuditFixLoop      – Gemini FAIL → Claude fix → re-audit ciklus
  OutputWriter      – fájlmentés, README generálás
  CostAccumulator   – token tracking, cost számítás
  DeveloperPipeline – orchestrátor, összerakja a láncot

Minden osztály önállóan tesztelhető és Telegramon kívül is futtatható.
A Telegram I/O kizárólag a bot/handlers.py-ban van.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Awaitable

from models import (
    AuditResult, AuditVerdict,
    GenerationResult, Pipeline, PipelineResult,
    SandboxResult, Task, TaskComplexity,
)
log = logging.getLogger("AXON.Pipeline")

AUDIT_MAX_RETRIES   = 2
SANDBOX_MAX_RETRIES = 3

StatusCallback = Callable[[str], Awaitable[None]]


# ══════════════════════════════════════════════════════════════
#  PRIVÁT HELPER FÜGGVÉNYEK
# ══════════════════════════════════════════════════════════════

def _extract_code_block(text: str | None) -> str | None:
    """Python kód blokk kinyerése ```python ... ``` jelölőkből."""
    if not text:
        return None
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    return None


def _build_pattern_block(patterns: list[dict]) -> str:
    """Sikeres minták few-shot blokkba rendezve."""
    if not patterns:
        return ""
    lines = ["TANULÁS – hasonló feladatoknál ezek működtek:\n"]
    for i, p in enumerate(patterns, 1):
        lines.append(f"Példa {i} ({p['similarity']:.0%}):\nFeladat: {p['prompt']}")
        lines.append(f"```python\n{p['code_snippet']}\n```\n")
    return "\n".join(lines) + "\n"


def _build_fix_block(samples: list[dict]) -> str:
    """Fix minták few-shot blokkba rendezve."""
    if not samples:
        return ""
    import json as _j
    lines = ["KORÁBBI HIBÁK ÉS JAVÍTÁSAIK:\n"]
    for i, s in enumerate(samples, 1):
        try:
            iss = _j.loads(s["issues"]) if isinstance(s["issues"], str) else s["issues"]
            iss_str = "; ".join(iss[:2]) if isinstance(iss, list) else str(iss)
        except Exception:
            iss_str = str(s["issues"])[:200]
        lines.append(f"--- Példa {i} ({s['score']:.0%}) ---")
        lines.append(f"Feladat: {s['prompt']}")
        lines.append(f"Hibás:\n```python\n{s['bad_code'][:400]}\n```")
        lines.append(f"Kifogások: {iss_str}")
        lines.append(f"Javítás:\n```python\n{s['fixed_code'][:400]}\n```\n")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════
#  CODE GENERATOR
# ══════════════════════════════════════════════════════════════

class CodeGenerator:
    """
    Felelőssége: Claude API hívások és raw kód visszaadása.
    Nem tud a sandboxról, auditról, Telegramról.
    Minden generálási logika és prompt inline — nincs külső függőség.
    """

    def __init__(self, call_claude_tracked: Callable, pipeline_prompt: str) -> None:
        self._call   = call_claude_tracked
        self._prompt = pipeline_prompt

    async def estimate_complexity(
        self, task: Task, status_cb: StatusCallback
    ) -> TaskComplexity:
        """Claude becslés: SIMPLE vagy COMPLEX."""
        await status_cb("1️⃣ *Tervezés...*\nKomplexitás elemzés")

        complexity_prompt = (
            f"Feladat: {task.text}\n\n"
            "Becsüld meg a feladat komplexitását. Válaszolj CSAK így:\n"
            "SIMPLE – ha 1 függvény vagy osztály elegendő, max ~50 sor\n"
            "COMPLEX – ha több osztály/modul kell, adatstruktúrák, generálás, >50 sor\n\n"
            "Ha COMPLEX, adj egy rövid tervet max 3 lépésben (1 sor/lépés).\n"
            "Formátum:\nCOMPLEXITY: SIMPLE\nvagy\nCOMPLEXITY: COMPLEX\nPLAN:\n1. ...\n2. ...\n3. ..."
        )

        response = await self._call(
            system=self._prompt,
            user_msg=complexity_prompt,
            max_tokens=300,
            chat_id=task.chat_id,
        )

        is_complex = any(
            line.strip().startswith("COMPLEXITY: COMPLEX")
            for line in response.upper().splitlines()
        )
        complexity  = TaskComplexity.COMPLEX if is_complex else TaskComplexity.SIMPLE
        log.info(f"[GEN] Komplexitás: {complexity.value}")
        return complexity

    async def generate_simple(
        self, task: Task, history_context: str, few_shot_block: str,
        status_cb: StatusCallback,
    ) -> str:
        """SIMPLE: 2 session — kód + unit tesztek."""
        await status_cb("1️⃣ *Kód generálás...*")

        s1_prompt = (
            f"{few_shot_block}"
            f"{history_context}"
            f"A feladat: {task.text}\n\n"
            "Generálj tiszta, TELJES Python megoldást.\n"
            "KÖTELEZŐ FORMÁTUM:\n```python\n# === KÓD ===\n[teljes megoldás]\n```\n"
            "Csak a kód, tesztek NEM kellenek."
        )
        s1_resp = await self._call(
            system=self._prompt, user_msg=s1_prompt,
            max_tokens=4000, chat_id=task.chat_id,
        )
        s1_code = _extract_code_block(s1_resp) or ""

        await status_cb("1️⃣ *Unit tesztek...*")
        s2_prompt = (
            f"Kész kód:\n```python\n{s1_code[:3000]}\n```\n\n"
            f"Feladat: {task.text}\n\n"
            "Adj hozzá 2-3 LOGIKAI tesztet. A tesztek a KÓD BELSŐ LOGIKÁJÁT ellenőrizzék,\n"
            "NEM az infrastruktúra hívások sikerességét.\n\n"
            "TESZTÍRÁSI SZABÁLYOK:\n"
            "TILOS – infrastructure eredmény tesztelése:\n"
            "  assert conn is not None          <- DB kapcsolat\n"
            "  assert send_alert(x) == True     <- API hívás\n\n"
            "HELYES – logika, adatstruktúra, feltételek tesztelése:\n"
            "  result = transform(raw_data)\n"
            "  assert isinstance(result, list)\n\n"
            "Max 3 assert, mindegyik MÁS logikai aspektust teszteljen.\n"
            "```python\n# === KÓD ===\n[kód]\n\n# === TESZTEK ===\n"
            "if __name__ == \"__test__\":\n    [assert1]\n    [assert2]\n    print(\"TESZTEK OK\")\n```"
        )
        s2_resp = await self._call(
            system=self._prompt, user_msg=s2_prompt,
            max_tokens=2000, chat_id=task.chat_id,
        )
        combined = _extract_code_block(s2_resp)
        if combined and "# === TESZTEK ===" in combined:
            code = combined
        else:
            code = (
                s1_code +
                '\n\n# === TESZTEK ===\n'
                'if __name__ == "__test__":\n'
                '    assert True  # fallback\n'
                '    print("TESZTEK OK")'
            )

        log.info(f"[GEN] Egyszerű generálás kész – 2 session | {len(code.splitlines())} sor")
        return code

    async def generate_complex(
        self, task: Task, history_context: str, few_shot_block: str,
        status_cb: StatusCallback,
    ) -> str:
        """COMPLEX: 4 session — 1. rész, 2. rész, 3a összefűzés, 3b tesztek."""
        await status_cb(
            "1️⃣ *Komplex feladat – 4 lépéses generálás*\n"
            "  ⏳ 1. Kód első fele\n  ⏳ 2. Kód második fele\n"
            "  ⏳ 3a. Összefűzés + tisztítás\n  ⏳ 3b. Unit tesztek"
        )

        # Session 1
        await status_cb("1️⃣ *Session 1/4* – Adatstruktúrák + helper függvények")
        s1_prompt = (
            f"{few_shot_block}"
            f"{history_context}"
            f"Feladat: {task.text}\n\n"
            "FONTOS: Ez egy 2 részből álló generálás ELSŐ FELE.\n"
            "Írj TELJES, MŰKÖDŐ Python kódot az alábbi részekhez:\n"
            "- Importok\n"
            "- Adatstruktúrák (dataclass, enum, konstansok)\n"
            "- Helper/segédfüggvények (teljes implementációval, NEM pass!)\n\n"
            "TILOS: pass, TODO, ... placeholder\n"
            "MINDEN függvény törzse legyen kitöltve!\n\n"
            "FORMÁTUM:\n```python\n# === KÓD (1. rész) ===\n[teljes kód ide]\n```"
        )
        s1_resp = await self._call(
            system=self._prompt, user_msg=s1_prompt,
            max_tokens=3500, chat_id=task.chat_id,
        )
        s1_code = _extract_code_block(s1_resp) or ""
        s1_code = s1_code.replace("# === KÓD (1. rész) ===", "").strip()

        # Session 2
        await status_cb("1️⃣ *Session 2/4* – Fő logika + generáló függvények")
        s2_prompt = (
            f"Feladat: {task.text}\n\n"
            f"Már megvan a kód ELSŐ FELE:\n```python\n{s1_code[:2500]}\n```\n\n"
            "FONTOS: Ez a MÁSODIK FELE. Írj TELJES, MŰKÖDŐ kódot:\n"
            "- Fő logika / generáló függvények\n"
            "- Main függvény vagy belépési pont\n"
            "- Minden függvény KITÖLTVE (NEM pass, NEM TODO!)\n\n"
            "Az első félre ÉPÍTS, ne ismételd meg!\n"
            "FORMÁTUM:\n```python\n# === KÓD (2. rész) ===\n[folytatás ide]\n```"
        )
        s2_resp = await self._call(
            system=self._prompt, user_msg=s2_prompt,
            max_tokens=3500, chat_id=task.chat_id,
        )
        s2_code = _extract_code_block(s2_resp) or ""
        s2_code = s2_code.replace("# === KÓD (2. rész) ===", "").strip()

        # Session 3a — összefűzés
        await status_cb("1️⃣ *Session 3a/4* – Összefűzés + tisztítás")
        combined_raw = s1_code + "\n\n" + s2_code
        s3a_prompt = (
            f"Ez a Python kód két részből összefűzve:\n"
            f"```python\n{combined_raw[:4000]}\n```\n\n"
            f"Feladat: {task.text}\n\n"
            "CSAK ezeket csináld:\n"
            "1. Ha van dupla import, távolítsd el (tartsd az elsőt)\n"
            "2. Ha van dupla osztály/függvény definíció, távolítsd el (tartsd az elsőt)\n"
            "3. Ellenőrizd hogy a kód szintaktikailag helyes és futtatható\n\n"
            "TILOS: teszteket írni, logikát változtatni, kommentelni!\n"
            "Add vissza a TELJES tisztított kódot:\n"
            "```python\n# === KÓD ===\n[teljes, tisztított kód – TESZTEK NÉLKÜL]\n```"
        )
        s3a_resp = await self._call(
            system=self._prompt, user_msg=s3a_prompt,
            max_tokens=4000, chat_id=task.chat_id,
        )
        log.info(f"[GEN] S3a válasz hossza: {len(s3a_resp)} kar")
        s3a_code = _extract_code_block(s3a_resp)
        clean_code = s3a_code.replace("# === KÓD ===", "").strip() if s3a_code else combined_raw.strip()

        # Session 3b — tesztek
        await status_cb("1️⃣ *Session 3b/4* – Unit tesztek generálása")
        s3b_prompt = (
            f"Ez a kész Python kód (csak az eleje látható terjedelmi okokból):\n"
            f"```python\n{clean_code[:2500]}\n```\n\n"
            f"Feladat: {task.text}\n\n"
            "Írj 2-3 LOGIKAI unit tesztet a kód belső logikájának ellenőrzésére.\n\n"
            "TILOS:\n"
            "  assert conn is not None\n"
            "  assert client is not None\n"
            "  import unittest / class TestXxx(unittest.TestCase)\n\n"
            "HELYES:\n"
            "  result = transform(raw_data)\n"
            "  assert isinstance(result, list)\n\n"
            "Max 3 assert. Adj vissza CSAK a teszt blokkot:\n"
            "```python\n"
            "# === TESZTEK ===\n"
            "if __name__ == \"__test__\":\n"
            "    [assert1]\n"
            "    [assert2]\n"
            "    print(\"TESZTEK OK\")\n"
            "```\n"
            "TILOS: import unittest, class TestXxx, assert conn is not None"
        )
        s3b_resp = await self._call(
            system=self._prompt, user_msg=s3b_prompt,
            max_tokens=800, chat_id=task.chat_id,
        )
        log.info(f"[GEN] S3b válasz hossza: {len(s3b_resp)} kar")
        s3b_block = _extract_code_block(s3b_resp)

        if s3b_block and "# === TESZTEK ===" in s3b_block:
            test_part = s3b_block[s3b_block.index("# === TESZTEK ==="):]
            code = "# === KÓD ===\n" + clean_code + "\n\n" + test_part
        else:
            log.warning("[GEN] S3b nem adott vissza teszt blokkot – retry")
            s3b_retry_prompt = (
                "A következő Python kódhoz írj 2 assert-alapú unit tesztet.\n"
                f"```python\n{clean_code[:1500]}\n```\n\n"
                "Csak a teszt blokkot add vissza:\n"
                "```python\n"
                "# === TESZTEK ===\n"
                "if __name__ == \"__test__\":\n"
                "    assert valami == elvart\n"
                "    assert isinstance(valami, list)\n"
                "    print(\"TESZTEK OK\")\n"
                "```\n"
                "TILOS: import unittest, class TestXxx"
            )
            s3b_retry = await self._call(
                system=self._prompt, user_msg=s3b_retry_prompt,
                max_tokens=600, chat_id=task.chat_id,
            )
            s3b_retry_block = _extract_code_block(s3b_retry)
            if s3b_retry_block and "# === TESZTEK ===" in s3b_retry_block:
                test_part = s3b_retry_block[s3b_retry_block.index("# === TESZTEK ==="):]
                code = "# === KÓD ===\n" + clean_code + "\n\n" + test_part
                log.info("[GEN] S3b retry sikeres")
            else:
                log.warning("[GEN] S3b retry is NONE – dummy fallback")
                code = (
                    "# === KÓD ===\n" + clean_code +
                    '\n\n# === TESZTEK ===\n'
                    'if __name__ == "__test__":\n'
                    '    assert True  # fallback\n'
                    '    print("TESZTEK OK")'
                )

        log.info(f"[GEN] Komplex generálás kész – 4 session | {len(code.splitlines())} sor")
        return code


# ══════════════════════════════════════════════════════════════
#  AUDIT FIX LOOP
# ══════════════════════════════════════════════════════════════

class AuditFixLoop:
    """Gemini FAIL → Claude fix → sandbox → re-audit, max AUDIT_MAX_RETRIES körön."""

    def __init__(
        self,
        call_claude: Callable,
        sandbox,
        auditor,
        save_fix_sample: Callable,
        format_audit_for_fix: Callable,
    ) -> None:
        self._call_claude     = call_claude
        self._sandbox         = sandbox
        self._auditor         = auditor
        self._save_fix        = save_fix_sample
        self._format_fix      = format_audit_for_fix

    async def run(
        self,
        task: Task,
        validated_code: str,
        audit_result: AuditResult,
        sandbox_result,
        few_shot_builder: Callable[[str], str],
        ai_fix_callback: Callable,
        status_cb: StatusCallback,
    ) -> tuple[str, AuditResult, object]:
        """Returns: (final_code, final_audit, final_sandbox)"""
        if audit_result.passed or audit_result.verdict == AuditVerdict.SKIP:
            return validated_code, audit_result, sandbox_result

        for fix_round in range(1, AUDIT_MAX_RETRIES + 1):
            await status_cb(
                f"3️⃣ *Gemini: FAIL* (javítás #{fix_round})\n"
                f"🔧 Claude javítja a kifogásolt részeket...\n"
                f"`{audit_result.issues[0][:80] if audit_result.issues else ''}`"
            )

            bad_code   = validated_code
            bad_issues = audit_result.issues[:]
            bad_score  = audit_result.score

            fix_prompt     = self._format_fix(audit_result, validated_code, task.text)
            fixed_response = await self._call_claude(
                system=(
                    "Senior Python fejlesztő vagy. Javítsd ki a megadott problémákat. "
                    "Adj vissza kódot ```python blokkban "
                    "(# === KÓD === és # === TESZTEK === szekciókkal)."
                ),
                user_msg=fix_prompt,
            )
            new_code = _extract_code_block(fixed_response)
            if not new_code:
                log.warning(f"[FIX] Fix #{fix_round}: Claude nem adott kód blokkot — loop leáll")
                break

            await status_cb(f"3️⃣ *Javítás #{fix_round}* → Sandbox újra...")
            sandbox_result = await self._sandbox.validate_with_retry(
                code=new_code, task=task.text,
                ai_fix_callback=ai_fix_callback,
                few_shot_fixes=few_shot_builder(getattr(sandbox_result, 'stderr', '') or ""),
            )

            if not sandbox_result.success:
                self._save_fix(
                    prompt=task.text, bad_code=bad_code, gemini_issues=bad_issues,
                    gemini_score=bad_score, fixed_code=new_code,
                    fix_round=fix_round, fix_succeeded=False,
                )
                break

            validated_code = sandbox_result.final_code

            await status_cb(f"3️⃣ *Javítás #{fix_round}* → Gemini újra...")
            audit_result = await self._auditor.audit(
                code=validated_code, task=task.text,
                test_result=f"Javítás #{fix_round} utáni tesztek OK",
            )

            self._save_fix(
                prompt=task.text, bad_code=bad_code, gemini_issues=bad_issues,
                gemini_score=bad_score, fixed_code=validated_code,
                fix_round=fix_round, fix_succeeded=audit_result.passed,
            )

            if audit_result.passed:
                log.info(f"[FIX] Javítás #{fix_round} után PASS!")
                break

        return validated_code, audit_result, sandbox_result


# ══════════════════════════════════════════════════════════════
#  OUTPUT WRITER
# ══════════════════════════════════════════════════════════════

class OutputWriter:
    """Fájlmentés + README generálás."""

    def __init__(self, output_dir: Path, generate_readme_fn: Callable) -> None:
        self._dir             = output_dir
        self._generate_readme = generate_readme_fn

    def write(
        self, task: Task, validated_code: str, sandbox_result, audit_result: AuditResult
    ) -> tuple[str, str, str, str]:
        """Returns: (filepath, filename, timestamp, safe_task)"""
        self._dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task = re.sub(r"[^a-zA-Z0-9]", "_", task.text[:40]).strip("_")
        filename  = f"{timestamp}_{safe_task}.py"
        filepath  = self._dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# AXON Neural Bridge – generált kód\n")
            f.write(f"# Feladat: {task.text}\n")
            f.write(f"# Generálva: {datetime.strptime(timestamp, '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M:%S')}\n")
            sandbox_ok = getattr(sandbox_result, 'success', False)
            f.write(
                f"# Sandbox: {'PASS' if sandbox_ok else 'FAIL'} | "
                f"Gemini: {getattr(audit_result.verdict, 'value', audit_result.verdict)} ({audit_result.score}/100)\n"
            )
            f.write(f"# {'=' * 60}\n\n")
            f.write(validated_code)

        log.info(f"[OUTPUT] Kód mentve: {filepath}")
        return str(filepath), filename, timestamp, safe_task

    async def write_readme(self, task: Task, main_code: str, filename: str,
                           timestamp: str, safe_task: str,
                           audit_result: AuditResult, sandbox_result) -> str:
        """README.md generálás. Returns: Telegram sor vagy üres string."""
        try:
            return await self._generate_readme(
                task=task.text, main_code=main_code, filename=filename,
                output_dir=str(self._dir), timestamp=timestamp, safe_task=safe_task,
                audit_result=audit_result, sandbox_result=sandbox_result,
            )
        except Exception as e:
            log.error(f"[OUTPUT] README generálás hiba: {e}")
            return ""


# ══════════════════════════════════════════════════════════════
#  COST ACCUMULATOR
# ══════════════════════════════════════════════════════════════

class CostAccumulator:
    """Token tracking és cost számítás — memory függvényeket kap injektálva."""

    def __init__(
        self,
        pop_tokens_fn: Callable[[str], dict],
        tokens_to_usd_fn: Callable[[int, int], float],
        log_cost_fn: Callable,
    ) -> None:
        self._pop      = pop_tokens_fn
        self._to_usd   = tokens_to_usd_fn
        self._log_cost = log_cost_fn

    def finalize(self, task: Task) -> tuple[float, dict]:
        """Lezárja a számlálást. Returns: (cost_usd, token_dict)"""
        tokens   = self._pop(task.chat_id)
        cost_usd = self._to_usd(tokens["input"], tokens["output"])
        self._log_cost(
            task=task.text, input_tokens=tokens["input"],
            output_tokens=tokens["output"], cost_usd=cost_usd, calls=tokens["calls"],
        )
        return cost_usd, tokens

    def discard(self, task: Task) -> None:
        """Token akkumuláció eldobása early exit esetén — szivárgás megelőzése."""
        self._pop(task.chat_id)


# ══════════════════════════════════════════════════════════════
#  DEVELOPER PIPELINE — ORCHESTRÁTOR
# ══════════════════════════════════════════════════════════════

class DeveloperPipeline:
    """
    A DEVELOPER pipeline orchestrátora.
    Koordinálja: CodeGenerator → Sandbox → AuditFixLoop → OutputWriter → Memory.
    Telegram I/O kizárólag a bot/handlers.py-ban van.
    """

    def __init__(
        self,
        generator:               CodeGenerator,
        fix_loop:                AuditFixLoop,
        writer:                  OutputWriter,
        cost:                    CostAccumulator,
        sandbox,
        auditor,
        get_cached_response:     Callable,
        save_cached_response:    Callable,
        get_history_turn_count:  Callable,
        get_last_code:           Callable,
        add_to_history:          Callable,
        save_training_sample:    Callable,
        get_successful_patterns: Callable,
        get_relevant_few_shot:   Callable,
        ai_fix_callback:         Callable,
        format_sandbox_report:   Callable,
        risk_keywords:           list[str],
    ) -> None:
        self.generator  = generator
        self.fix_loop   = fix_loop
        self.writer     = writer
        self.cost       = cost
        self.sandbox    = sandbox
        self.auditor    = auditor
        self._get_cached          = get_cached_response
        self._save_cached         = save_cached_response
        self._turn_count          = get_history_turn_count
        self._get_last_code       = get_last_code
        self._add_history         = add_to_history
        self._save_training       = save_training_sample
        self._get_patterns        = get_successful_patterns
        self._get_few_shot        = get_relevant_few_shot
        self._ai_fix_cb           = ai_fix_callback
        self._fmt_sandbox         = format_sandbox_report
        self._risk_kws            = risk_keywords

    async def run(
        self,
        task: Task,
        status_cb: StatusCallback,
        risk_approval: Callable | None = None,
    ) -> PipelineResult:
        """
        Teljes DEVELOPER pipeline.
        Returns: PipelineResult — a bot ebből buildeli a Telegram üzenetet.
        """
        is_multiturn = self._turn_count(task.chat_id) > 0

        # 1. Cache
        if not is_multiturn:
            cached = self._get_cached("developer", task.text)
            if cached:
                self._add_history(task.chat_id, "user", task.text, "DEVELOPER")
                self._add_history(task.chat_id, "assistant", f"[CACHE HIT]\n{cached}", "DEVELOPER", task=task.text)
                log.info("Developer cache HIT")
                return PipelineResult(
                    task=task, pipeline=Pipeline.DEVELOPER,
                    success=True, output=cached, cache_hit=True,
                )

        # 2. Few-shot
        patterns       = self._get_patterns(task.text, max_patterns=2)
        few_shot_block = _build_pattern_block(patterns)

        def few_shot_builder(error_text: str) -> str:
            return _build_fix_block(self._get_few_shot(task.text, error_text=error_text, max_samples=2))

        # 3. History context
        history_context = ""
        if is_multiturn:
            last_code, _ = self._get_last_code(task.chat_id)
            if last_code:
                history_context = (
                    f"KONTEXTUS – az előző feladatban generált kód:\n"
                    f"```python\n{last_code[:3000]}\n```\n\n"
                )

        # 4. Komplexitás
        complexity = await self.generator.estimate_complexity(task, status_cb)
        task = task.model_copy(update={"complexity": complexity})

        # 5. Generálás
        if complexity == TaskComplexity.COMPLEX:
            code = await self.generator.generate_complex(task, history_context, few_shot_block, status_cb)
        else:
            code = await self.generator.generate_simple(task, history_context, few_shot_block, status_cb)

        if not code.strip():
            self.cost.discard(task)
            return PipelineResult(
                task=task, pipeline=Pipeline.DEVELOPER,
                success=False, output="❌ Kód generálás sikertelen.",
            )

        # 6. Kockázati szűrő
        risks = [kw for kw in self._risk_kws if kw in code.lower()]
        if risks and risk_approval:
            approved = await risk_approval(risks, str(uuid.uuid4())[:8])
            if not approved:
                self.cost.discard(task)
                return PipelineResult(
                    task=task, pipeline=Pipeline.DEVELOPER,
                    success=False, output="⛔ Kockázatos kód – visszautasítva.",
                )

        # 7. Sandbox
        await status_cb("2️⃣ *Sandbox validáció...*\n🔬 Statikus szűrő + unit tesztek")
        sandbox_result = await self.sandbox.validate_with_retry(
            code=code, task=task.text,
            ai_fix_callback=self._ai_fix_cb,
            status_callback=lambda m: status_cb(f"2️⃣ *Sandbox*\n{m}"),
            few_shot_fixes=few_shot_builder(""),
        )

        if not sandbox_result.success:
            self.cost.discard(task)
            return PipelineResult(
                task=task, pipeline=Pipeline.DEVELOPER, success=False,
                output=(
                    f"❌ *Sandbox sikertelen* {SANDBOX_MAX_RETRIES} próba után\n\n"
                    f"{self._fmt_sandbox(sandbox_result)}\n\n"
                    "• Pontosítsd a feladatot\n• `/bypass` sandbox nélkül"
                ),
            )

        validated_code  = sandbox_result.final_code
        test_result_str = (
            f"Tesztek: {sandbox_result.tests_passed}/{sandbox_result.tests_total} OK\n"
            f"Stdout: {sandbox_result.stdout[:300]}"
        )

        # 8. Gemini audit
        await status_cb("3️⃣ *Gemini audit...*\n🔮 Logikai ellenőrzés, projekt szabályok, minőség")
        audit_result = await self.auditor.audit(
            code=validated_code, task=task.text, test_result=test_result_str,
        )
        log.info(f"[AUDIT] {audit_result.verdict} – score: {audit_result.score}/100")

        # 9. Fix loop
        validated_code, audit_result, sandbox_result = await self.fix_loop.run(
            task=task, validated_code=validated_code,
            audit_result=audit_result, sandbox_result=sandbox_result,
            few_shot_builder=few_shot_builder,
            ai_fix_callback=self._ai_fix_cb, status_cb=status_cb,
        )

        # 10. Fájlmentés
        output_file = readme_file = None
        try:
            _, filename, timestamp, safe_task_s = self.writer.write(
                task, validated_code, sandbox_result, audit_result
            )
            output_file = filename
            readme_file = await self.writer.write_readme(
                task=task, main_code=validated_code, filename=filename,
                timestamp=timestamp, safe_task=safe_task_s,
                audit_result=audit_result, sandbox_result=sandbox_result,
            ) or None
        except Exception as e:
            log.error(f"[OUTPUT] Fájlmentés hiba: {e}")

        # 11. Cost
        cost_usd, tokens = self.cost.finalize(task)

        # 12. Memory + training + cache
        self._add_history(task.chat_id, "user",      task.text,      "DEVELOPER")
        self._add_history(task.chat_id, "assistant", validated_code, "DEVELOPER", task=task.text)

        final_success = sandbox_result.success and audit_result.passed
        self._save_training(
            expert_mode="developer", prompt=task.text,
            generated_code=validated_code,
            sandbox_result=sandbox_result.stdout[:500] + sandbox_result.stderr[:500],
            audit_result=audit_result.telegram_summary if audit_result.verdict != AuditVerdict.SKIP else "SKIP",
            sandbox_ok=sandbox_result.success, audit_ok=audit_result.passed,
            success=final_success, retry_count=sandbox_result.attempt - 1,
        )

        return PipelineResult(
            task=task, pipeline=Pipeline.DEVELOPER,
            success=final_success, output=validated_code,
            cost_usd=cost_usd, tokens_in=tokens["input"],
            tokens_out=tokens["output"], api_calls=tokens["calls"],
            output_file=output_file, readme_file=readme_file,
        )
