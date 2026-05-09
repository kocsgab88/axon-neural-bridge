#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AXON Neural Bridge — Core Data Models
======================================

Copyright (c) 2026 Kocsis Gábor. All rights reserved.
Licensed under AXON Source Available License v1.0.

This file is part of AXON Neural Bridge.
See LICENSE.md for licensing terms.
Commercial use requires separate license: kocsgab88@gmail.com

---

v9.0 | Pydantic v2

Ez a fájl az AXON teljes adatmodelljét definiálja.
Minden pipeline, memory és bot modul ebből importál —
soha nem raw dict-eket ad át egymásnak.

Modellek:
  Pipeline:
    Task               – bejövő feladat
    GenerationResult   – Claude által generált kód
    SandboxResult      – sandbox + unit test eredmény
    AuditResult        – Gemini cross-check eredmény
    PipelineResult     – teljes pipeline végeredmény

  Memory:
    HistoryTurn        – egy conversation turn
    CostEntry          – egy feladat API cost rekordja
    TrainingSample     – training data rekord
    FixSample          – bad→fixed kód pár fine-tuning adathoz
    CacheEntry         – task cache rekord

  System:
    SystemStatus       – watchman / /status parancs
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator, model_validator


# ══════════════════════════════════════════════════════════════════
#  ENUMS
# ══════════════════════════════════════════════════════════════════

class Pipeline(str, Enum):
    """Az AXON négy pipeline-ja."""
    DEVELOPER = "DEVELOPER"
    PLANNER   = "PLANNER"
    CREATIVE  = "CREATIVE"
    ANALYST   = "ANALYST"


class TaskComplexity(str, Enum):
    """DEVELOPER pipeline komplexitás becslés."""
    SIMPLE  = "SIMPLE"   # 2 session: kód + tesztek
    COMPLEX = "COMPLEX"  # 3 session: terv + kód + tesztek


class AuditVerdict(str, Enum):
    """Gemini audit lehetséges verdiktjei."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"   # API nem elérhető


class Role(str, Enum):
    """Conversation history szerepek."""
    USER      = "user"
    ASSISTANT = "assistant"


class RouteDecision(BaseModel):
    """
    Pipeline routing döntés — típusosan, nem magic string.
    method: hogyan döntött a router ('keyword' | 'claude' | 'fallback')
    """
    pipeline: Pipeline
    method:   str = "keyword"

    def __str__(self) -> str:
        return f"{self.pipeline.value} (via {self.method})"


# ══════════════════════════════════════════════════════════════════
#  PIPELINE MODELLEK
# ══════════════════════════════════════════════════════════════════

class Task(BaseModel):
    """Bejövő feladat — a pipeline belépési pontja."""
    text:       str
    chat_id:    str
    pipeline:   Pipeline
    complexity: TaskComplexity | None = None
    request_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Task text nem lehet üres")
        return v.strip()

    @field_validator("chat_id")
    @classmethod
    def chat_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chat_id nem lehet üres")
        return v.strip()


class GenerationResult(BaseModel):
    """Claude által generált raw kód — sandbox előtt."""
    code:       str
    session:    int = 1          # melyik Claude session generálta
    prompt:     str = ""         # a prompt amit kapott (debug célra)
    tokens_in:  int = 0
    tokens_out: int = 0

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Generált kód nem lehet üres")
        return v


class SandboxResult(BaseModel):
    """Sandbox + unit test futtatás eredménye."""
    success:       bool
    message:       str
    stdout:        str = ""
    stderr:        str = ""
    attempt:       int = Field(default=1, ge=1, le=10)
    final_code:    str = ""
    tests_passed:  int = Field(default=0, ge=0)
    tests_total:   int = Field(default=0, ge=0)
    risk_keywords: list[str] = Field(default_factory=list)
    mock_mode:     bool = False
    mock_libs:     list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def tests_consistency(self) -> SandboxResult:
        if self.tests_passed > self.tests_total:
            raise ValueError(
                f"tests_passed ({self.tests_passed}) > tests_total ({self.tests_total})"
            )
        return self

    @property
    def test_ratio(self) -> str:
        return f"{self.tests_passed}/{self.tests_total}"

    @property
    def retry_count(self) -> int:
        return self.attempt - 1


class AuditResult(BaseModel):
    """Gemini cross-check audit eredménye."""
    verdict:      AuditVerdict
    score:        int = Field(default=0, ge=0, le=100)
    issues:       list[str] = Field(default_factory=list)
    suggestions:  list[str] = Field(default_factory=list)
    categories:   dict[str, Any] = Field(default_factory=dict)
    raw_response: str = ""
    skip_reason:  str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == AuditVerdict.PASS

    @property
    def telegram_summary(self) -> str:
        """Rövid Telegram-barát összefoglaló."""
        if self.verdict == AuditVerdict.SKIP:
            return f"⏭️ *Gemini audit kihagyva:* `{self.skip_reason[:80]}`"

        icon = "✅" if self.passed else "❌"
        lines = [f"{icon} *Gemini audit: {self.verdict.value}* ({self.score}/100)"]

        cat_icons = []
        for name, data in self.categories.items():
            if isinstance(data, dict):
                score = data.get("score", 0)
                cat_icon = "✅" if score >= 7 else "⚠️" if score >= 5 else "❌"
                cat_icons.append(f"{cat_icon} {name}: {score}/10")
        if cat_icons:
            lines.append(" | ".join(cat_icons))

        if not self.passed and self.issues:
            lines.append(f"⚠️ {self.issues[0][:100]}")

        return "\n".join(lines)

    @classmethod
    def skipped(cls, reason: str) -> AuditResult:
        """Factory: SKIP eredmény gyors létrehozása."""
        return cls(
            verdict=AuditVerdict.SKIP,
            score=0,
            skip_reason=reason,
        )

    @classmethod
    def failed(cls, score: int, issues: list[str]) -> AuditResult:
        """Factory: FAIL eredmény gyors létrehozása."""
        return cls(
            verdict=AuditVerdict.FAIL,
            score=score,
            issues=issues,
        )


class PipelineResult(BaseModel):
    """
    Egy teljes pipeline futás végeredménye.
    Ez az az objektum amit a bot handler megkap és Telegramon küld el.
    """
    task:           Task
    pipeline:       Pipeline
    success:        bool
    output:         str                    # a végső szöveg / kód
    sandbox:        SandboxResult | None = None
    audit:          AuditResult   | None = None
    cost_usd:       float = Field(default=0.0, ge=0.0)
    tokens_in:      int   = Field(default=0, ge=0)
    tokens_out:     int   = Field(default=0, ge=0)
    api_calls:      int   = Field(default=0, ge=0)
    cache_hit:      bool  = False
    output_file:    str | None = None      # ha .py fájl mentve
    readme_file:    str | None = None      # ha README.md generálva
    completed_at:   datetime = Field(default_factory=datetime.now)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.task.created_at).total_seconds()

    @property
    def fully_passed(self) -> bool:
        """Sandbox + Audit mind PASS."""
        sandbox_ok = self.sandbox.success if self.sandbox else True
        audit_ok   = self.audit.passed    if self.audit   else True
        return self.success and sandbox_ok and audit_ok


# ══════════════════════════════════════════════════════════════════
#  MEMORY MODELLEK
# ══════════════════════════════════════════════════════════════════

class HistoryTurn(BaseModel):
    """Egy conversation history bejegyzés."""
    role:       Role
    content:    str
    pipeline:   Pipeline
    ts:         float = Field(default_factory=lambda: datetime.now().timestamp())
    task:       str | None = None    # assistant turn esetén az eredeti feladat

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("History turn content nem lehet üres")
        return v

    @property
    def char_count(self) -> int:
        return len(self.content)

    def to_claude_message(self) -> dict[str, str]:
        """Claude API messages formátumba konvertál."""
        return {"role": self.role.value, "content": self.content}


class CostEntry(BaseModel):
    """Egy feladat API cost rekordja az api_costs táblához."""
    task:       str
    date:       str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    input_tok:  int = Field(ge=0)
    output_tok: int = Field(ge=0)
    cost_usd:   float = Field(ge=0.0)
    calls:      int = Field(default=1, ge=1)
    pipeline:   Pipeline = Pipeline.DEVELOPER

    @property
    def total_tokens(self) -> int:
        return self.input_tok + self.output_tok


class TrainingSample(BaseModel):
    """Training data rekord — minden pipeline futás után mentődik."""
    expert_mode:    Pipeline
    prompt:         str
    generated_code: str = ""
    sandbox_result: str = ""
    audit_result:   str = ""
    sandbox_ok:     bool = True
    audit_ok:       bool = True
    success:        bool = True
    retry_count:    int  = Field(default=0, ge=0)
    created_at:     str  = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


class FixSample(BaseModel):
    """
    Bad → Fixed kód pár a fix_samples táblához.
    Fine-tuning alap + few-shot tanulás forrása.
    """
    bad_code:        str
    gemini_issues:   list[str]
    fixed_code:      str
    task:            str = ""
    fix_succeeded:   bool = True
    bad_score:       int  = Field(default=0, ge=0, le=100)
    fixed_score:     int  = Field(default=0, ge=0, le=100)
    abstract_lesson: str  = ""    # v8.5: domain-független tanulság
    created_at:      str  = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    @field_validator("gemini_issues", mode="before")
    @classmethod
    def parse_issues(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [v]
        return v


class CacheEntry(BaseModel):
    """Task cache rekord."""
    hash:       str
    response:   str
    expert_mode: Pipeline
    prompt:     str
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    hits:       int = Field(default=0, ge=0)


# ══════════════════════════════════════════════════════════════════
#  SYSTEM MODELLEK
# ══════════════════════════════════════════════════════════════════

class SystemStatus(BaseModel):
    """Watchman / /status parancs adatai."""
    version:      str = "v9.0"
    running:      bool = True
    cpu_percent:  float = Field(default=0.0, ge=0.0, le=100.0)
    ram_percent:  float = Field(default=0.0, ge=0.0, le=100.0)
    ram_used_mb:  int   = Field(default=0, ge=0)
    ram_total_mb: int   = Field(default=0, ge=0)
    disk_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    disk_free_gb: float = Field(default=0.0, ge=0.0)
    checked_at:   datetime = Field(default_factory=datetime.now)

    @property
    def cpu_icon(self) -> str:
        return "🔥" if self.cpu_percent >= 80 else "📊"

    @property
    def ram_icon(self) -> str:
        return "🔥" if self.ram_percent >= 80 else "🧠"

    @property
    def disk_icon(self) -> str:
        return "🔥" if self.disk_percent >= 90 else "💾"
