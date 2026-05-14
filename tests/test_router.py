"""
tests/test_router.py — AXON v9.0 router unit tesztek
Lefedés: keyword routing minden pipeline-ra, edge case-ek,
         Claude fallback logika, fallback default.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock

from bot.router import PipelineRouter
from models import Pipeline, RouteDecision, Task


def _router(claude_response: str = "PLANNER") -> PipelineRouter:
    return PipelineRouter(call_claude_fn=AsyncMock(return_value=claude_response))


def _task(text: str) -> Task:
    return Task(text=text, chat_id="1", pipeline=Pipeline.DEVELOPER)


# ══════════════════════════════════════════════════════════════
#  KEYWORD ROUTING
# ══════════════════════════════════════════════════════════════

class TestKeywordRouting:

    # ── DEVELOPER ────────────────────────────────────────────

    def test_developer_kod(self):
        r = _router().route_by_keyword("Írj kódot ami beolvassa a CSV-t")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER

    def test_developer_python(self):
        r = _router().route_by_keyword("Python script a fájlok feldolgozásához")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER

    def test_developer_scraper(self):
        r = _router().route_by_keyword("Fejlessz egy web scraper scriptet")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER

    def test_developer_function(self):
        r = _router().route_by_keyword("Írj egy függvényt ami rendezi a listát")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER

    def test_developer_implement(self):
        r = _router().route_by_keyword("Implement a retry mechanism in Python")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER

    # ── PLANNER ──────────────────────────────────────────────

    def test_planner_sprint(self):
        r = _router().route_by_keyword("Generálj sprint tervet az AXON-hoz")
        assert r is not None and r.pipeline == Pipeline.PLANNER

    def test_planner_roadmap(self):
        r = _router().route_by_keyword("Készíts roadmap-et a következő negyedévre")
        assert r is not None and r.pipeline == Pipeline.PLANNER

    def test_planner_dokumentacio(self):
        r = _router().route_by_keyword("Írj dokumentációt az API-hoz")
        assert r is not None and r.pipeline == Pipeline.PLANNER

    def test_planner_architektura(self):
        r = _router().route_by_keyword("Tervezd meg az architektúrát")
        assert r is not None and r.pipeline == Pipeline.PLANNER

    def test_planner_beats_developer_for_plan(self):
        """'fejlesztési terv egy scripthez' → PLANNER, nem DEVELOPER."""
        r = _router().route_by_keyword("Készíts fejlesztési tervet egy Python scripthez")
        assert r is not None and r.pipeline == Pipeline.PLANNER

    # ── CREATIVE ─────────────────────────────────────────────

    def test_creative_cover_letter(self):
        r = _router().route_by_keyword("Írj cover lettert az Upwork hirdetésre")
        assert r is not None and r.pipeline == Pipeline.CREATIVE

    def test_creative_email(self):
        r = _router().route_by_keyword("Fogalmazz egy email üzenetet az ügyfélnek")
        assert r is not None and r.pipeline == Pipeline.CREATIVE

    def test_creative_bemutatkozo(self):
        r = _router().route_by_keyword("Írj bemutatkozót a profilomhoz")
        assert r is not None and r.pipeline == Pipeline.CREATIVE

    def test_creative_beats_developer_for_cover_letter(self):
        """'cover letter Python munkához' → CREATIVE, nem DEVELOPER."""
        r = _router().route_by_keyword("Írj cover lettert Upwork Python automatizálás munkához")
        assert r is not None and r.pipeline == Pipeline.CREATIVE

    # ── ANALYST ──────────────────────────────────────────────

    def test_analyst_elemezd(self):
        r = _router().route_by_keyword("Elemezd a heti bevételeket")
        assert r is not None and r.pipeline == Pipeline.ANALYST

    def test_analyst_statisztika(self):
        r = _router().route_by_keyword("Statisztikát kérek a hibákról")
        assert r is not None and r.pipeline == Pipeline.ANALYST

    def test_analyst_roi(self):
        r = _router().route_by_keyword("Számold ki az ROI-t")
        assert r is not None and r.pipeline == Pipeline.ANALYST

    def test_analyst_tablazat(self):
        r = _router().route_by_keyword("Készíts táblázatot az eredményekről")
        assert r is not None and r.pipeline == Pipeline.ANALYST

    # ── Method ───────────────────────────────────────────────

    def test_method_is_keyword(self):
        r = _router().route_by_keyword("Írj kódot")
        assert r is not None and r.method == "keyword"

    # ── Keyword miss ─────────────────────────────────────────

    def test_miss_returns_none(self):
        assert _router().route_by_keyword("Mi az időjárás ma?") is None

    def test_miss_generic_question(self):
        assert _router().route_by_keyword("Szia, hogy vagy?") is None

    def test_miss_empty_string(self):
        assert _router().route_by_keyword("") is None

    def test_case_insensitive(self):
        r = _router().route_by_keyword("PYTHON SCRIPT FEJLESZTÉS")
        assert r is not None and r.pipeline == Pipeline.DEVELOPER


# ══════════════════════════════════════════════════════════════
#  CLAUDE FALLBACK
# ══════════════════════════════════════════════════════════════

class TestClaudeFallback:

    @pytest.mark.asyncio
    async def test_claude_developer_response(self):
        router = _router("DEVELOPER")
        task   = _task("Valami amit a keyword nem ismer fel")
        r      = await router.route_by_claude(task)
        assert r.pipeline == Pipeline.DEVELOPER
        assert r.method   == "claude"

    @pytest.mark.asyncio
    async def test_claude_planner_response(self):
        router = _router("PLANNER")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.PLANNER
        assert r.method   == "claude"

    @pytest.mark.asyncio
    async def test_claude_creative_response(self):
        router = _router("CREATIVE")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.CREATIVE

    @pytest.mark.asyncio
    async def test_claude_analyst_response(self):
        router = _router("ANALYST")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.ANALYST

    @pytest.mark.asyncio
    async def test_invalid_claude_response_fallback(self):
        """Ha Claude érvénytelen választ ad → PLANNER fallback."""
        router = _router("INVALID_GARBAGE")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.PLANNER
        assert r.method   == "fallback"

    @pytest.mark.asyncio
    async def test_claude_error_fallback(self):
        """Ha Claude dob exception-t → PLANNER fallback."""
        router = PipelineRouter(call_claude_fn=AsyncMock(side_effect=Exception("API error")))
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.PLANNER
        assert r.method   == "fallback"

    @pytest.mark.asyncio
    async def test_claude_response_case_insensitive(self):
        """Claude válasz kis-nagybetűtől független."""
        router = _router("developer")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.DEVELOPER

    @pytest.mark.asyncio
    async def test_claude_response_with_extra_whitespace(self):
        """Claude válasz lehet szóközökkel körülvéve."""
        router = _router("  ANALYST  ")
        r      = await router.route_by_claude(_task("x"))
        assert r.pipeline == Pipeline.ANALYST


# ══════════════════════════════════════════════════════════════
#  TELJES ROUTING (route())
# ══════════════════════════════════════════════════════════════

class TestFullRouting:

    @pytest.mark.asyncio
    async def test_keyword_match_no_claude_call(self):
        """Ha keyword match van → Claude NEM hívódik."""
        mock_claude = AsyncMock()
        router = PipelineRouter(call_claude_fn=mock_claude)
        await router.route(_task("Írj Python kódot"))
        mock_claude.assert_not_called()

    @pytest.mark.asyncio
    async def test_keyword_miss_calls_claude(self):
        """Ha keyword miss → Claude hívódik."""
        mock_claude = AsyncMock(return_value="ANALYST")
        router = PipelineRouter(call_claude_fn=mock_claude)
        r = await router.route(_task("Mi a legjobb étterem Budapesten?"))
        mock_claude.assert_called_once()
        assert r.pipeline == Pipeline.ANALYST

    @pytest.mark.asyncio
    async def test_full_route_developer(self):
        r = await _router().route(_task("Írj kódot"))
        assert r.pipeline == Pipeline.DEVELOPER

    @pytest.mark.asyncio
    async def test_full_route_planner(self):
        r = await _router().route(_task("Készíts sprint tervet"))
        assert r.pipeline == Pipeline.PLANNER

    @pytest.mark.asyncio
    async def test_route_decision_has_method(self):
        r = await _router().route(_task("Írj kódot"))
        assert r.method in ("keyword", "claude", "fallback")


# ══════════════════════════════════════════════════════════════
#  ROUTE DECISION MODELL
# ══════════════════════════════════════════════════════════════

class TestRouteDecision:

    def test_str_representation(self):
        r = RouteDecision(pipeline=Pipeline.DEVELOPER, method="keyword")
        assert "DEVELOPER" in str(r)
        assert "keyword"   in str(r)

    def test_default_method_keyword(self):
        r = RouteDecision(pipeline=Pipeline.ANALYST)
        assert r.method == "keyword"

    def test_all_pipelines_valid(self):
        for p in Pipeline:
            r = RouteDecision(pipeline=p, method="claude")
            assert r.pipeline == p
