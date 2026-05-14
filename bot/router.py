#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AXON Neural Bridge — Pipeline Router
======================================

Copyright (c) 2026 Kocsis Gábor. All rights reserved.
Licensed under AXON Source Available License v1.0.

This file is part of AXON Neural Bridge.
See LICENSE.md for licensing terms.
Commercial use requires separate license: kocsgab88@gmail.com

---

v9.0

Felelőssége: Task szövegéből RouteDecision készítése.
Semmi más — nem tud a Telegramról, nem hív pipeline-t.

Routing stratégia (prioritás sorrendben):
  1. Keyword match  — 0 API hívás, determinisztikus
  2. Claude routing — ha keyword nem egyértelmű, max 10 token
  3. Fallback       — PLANNER (biztonságos default)

A PLANNER kulcsszavak ELSŐ prioritást kapnak:
  "fejlesztési terv egy scripthez" → PLANNER, nem DEVELOPER
  (a DEVELOPER kulcsszavak (script, python) félrevezetnek)

Tesztelhetőség:
  A PipelineRouter.route() sync metódus — unit tesztelhető mock nélkül.
  A Claude fallback async — külön tesztelhető.
"""

from __future__ import annotations

import logging
from typing import Callable, Awaitable

from models import Pipeline, RouteDecision, Task

log = logging.getLogger("AXON.Router")


# ══════════════════════════════════════════════════════════════
#  KEYWORD SZABÁLYOK
#  Sorrendben ellenőrizzük — az első match nyer
# ══════════════════════════════════════════════════════════════

_KEYWORD_RULES: list[tuple[Pipeline, frozenset[str]]] = [

    # PLANNER ELŐSZÖR — "fejlesztési terv egy scripthez" ne menjen DEVELOPER-be
    (Pipeline.PLANNER, frozenset({
        "terv", "tervez", "tervezz", "fejlesztési terv", "sprint", "roadmap",
        "ütemterv", "dokumentáció", "dokumentum", "összefoglaló", "leírás",
        "specifikáció", "spec", "feladatlista", "checklist", "struktúra",
        "felépítés", "architektúra", "készíts tervet", "írj tervet",
    })),

    # CREATIVE MÁSODSZOR — "cover letter Python munkához" ne menjen DEVELOPER-be
    # a "python" szó jelenléte nem elég: ha cover letter / levél / szöveg is van → CREATIVE nyeri
    (Pipeline.CREATIVE, frozenset({
        "cover letter", "cover lettert", "email", "levél", "levelet", "szöveget",
        "hirdetés szöveg", "posztot", "prezentációt", "bemutatkozó",
        "ajánlat szöveg", "írj egy levél", "fogalmazz",
    })),

    (Pipeline.DEVELOPER, frozenset({
        "kód", "kódot", "python", "script", "program", "fejlessz", "code",
        "függvény", "function", "class", "modul", "implement", "írj kódot",
        "automatizálj", "bot", "api hívás", "parser", "scraper",
    })),

    (Pipeline.ANALYST, frozenset({
        "elemezd", "elemzés", "adat", "statisztika", "statisztikát", "mennyi", "számolj",
        "összehasonlít", "összehasonlítás", "kalkulál", "megtérülés",
        "bevétel", "kiadás", "roi", "táblázat", "trend",
    })),
]

# Claude fallback prompt — max 10 token válasz
_ROUTING_SYSTEM = (
    "Pipeline routing döntéshozó vagy. "
    "CSAK egyetlen szót válaszolsz: DEVELOPER, PLANNER, CREATIVE, vagy ANALYST."
)

_ROUTING_USER_TEMPLATE = (
    "Feladat: {task}\n\n"
    "Melyik pipeline dolgozza fel? Válaszolj CSAK egyetlen szóval:\n"
    "DEVELOPER – ha Python kódot kell írni vagy implementálni\n"
    "PLANNER   – ha tervet, dokumentációt, sprint tervet, összefoglalót kell készíteni\n"
    "CREATIVE  – ha szöveget, levelet, hirdetést, prezentációt kell írni\n"
    "ANALYST   – ha adatot kell elemezni, számolni, összehasonlítani\n\n"
    "Válasz (CSAK EGY SZÓ):"
)

_VALID_PIPELINES = frozenset(p.value for p in Pipeline)


# ══════════════════════════════════════════════════════════════
#  PIPELINE ROUTER
# ══════════════════════════════════════════════════════════════

class PipelineRouter:
    """
    Routing döntéshozó.
    Teljesen állapotmentes — minden hívás független.

    A sync route() metódus tesztelhető Claude nélkül.
    Az async route_with_fallback() az éles bot által használt teljes routing.
    """

    def __init__(self, call_claude_fn: Callable[..., Awaitable[str]]) -> None:
        """
        Args:
            call_claude_fn: async (system, user_msg, max_tokens) → str
                            Az AppContext adja át — a router nem tud a Claude clientről.
        """
        self._call_claude = call_claude_fn

    # ── Sync keyword routing ──────────────────────────────────

    def route_by_keyword(self, text: str) -> RouteDecision | None:
        """
        Keyword alapú routing — 0 API hívás.
        Returns None ha nincs egyértelmű match (Claude fallback következik).
        """
        lowered = text.lower()
        for pipeline, keywords in _KEYWORD_RULES:
            if any(kw in lowered for kw in keywords):
                log.debug(f"[ROUTER] Keyword match: {pipeline.value}")
                return RouteDecision(pipeline=pipeline, method="keyword")
        return None

    # ── Async Claude fallback ─────────────────────────────────

    async def route_by_claude(self, task: Task) -> RouteDecision:
        """
        Claude-ra bízza a döntést ha keyword nem egyértelmű.
        Max 10 token → gyors és olcsó.
        Fallback: PLANNER ha Claude sem ad érvényes választ.
        """
        log.info(f"[ROUTER] Keyword miss → Claude routing | req={task.request_id}")
        try:
            result = await self._call_claude(
                system=_ROUTING_SYSTEM,
                user_msg=_ROUTING_USER_TEMPLATE.format(task=task.text),
                max_tokens=10,
            )
            candidate = result.strip().upper().split()[0]
            if candidate in _VALID_PIPELINES:
                log.info(f"[ROUTER] Claude döntés: {candidate} | req={task.request_id}")
                return RouteDecision(pipeline=Pipeline(candidate), method="claude")
        except Exception as e:
            log.warning(f"[ROUTER] Claude routing hiba: {e} | req={task.request_id}")

        log.info(f"[ROUTER] Fallback: PLANNER | req={task.request_id}")
        return RouteDecision(pipeline=Pipeline.PLANNER, method="fallback")

    # ── Teljes routing (éles bot) ─────────────────────────────

    async def route(self, task: Task) -> RouteDecision:
        """
        Teljes routing pipeline:
          1. Keyword match (sync, 0 API hívás)
          2. Claude fallback (async, max 10 token)
          3. PLANNER fallback

        Ez az a metódus amit a TaskHandler hív.
        """
        decision = self.route_by_keyword(task.text)
        if decision:
            return decision
        return await self.route_by_claude(task)
