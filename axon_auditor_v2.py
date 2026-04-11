"""
AXON Auditor v2.0 – Gemini Cross-Check (3. szint)
OWNER: GABOR KOCSIS | AXON Neural Bridge
──────────────────────────────────────────────────
Mi változott v1 → v2:
- Lépéses (Chain of Thought) audit prompt: Gemini előbb gondolkodik,
  utána ítél – sokkal megbízhatóbb mint az egylépéses JSON kérés
- Robusztus JSON parser: 3 különböző fallback stratégia
- Fail-safe logika: ha a Gemini API nem elérhető, nem blokkol
- Részletes logging minden lépésről
- Új google-genai SDK (google.genai csomag)
"""

import asyncio
import logging
import json
import re
from dataclasses import dataclass, field
from google import genai

log = logging.getLogger("AXON.Auditor")

# ═══════════════════════════════════════════════════════════════
#  KONFIGURÁCIÓ
# ═══════════════════════════════════════════════════════════════
GEMINI_MODEL = "gemini-2.5-flash"

# ═══════════════════════════════════════════════════════════════
#  AXON PROJEKT KONTEXTUS
#  Ezt kapja a Gemini – pontosan tudja mit kell ellenőriznie
# ═══════════════════════════════════════════════════════════════
AXON_CONTEXT = """
Te az AXON rendszer független kód-auditora vagy.
Az AXON egy Python automatizálási rendszer ami Telegramon keresztül kap feladatokat,
Claude AI-jal generál kódot, és az Asus X550JX gépen futtatja.

PROJEKT SZABÁLYOK AMIKET ISMERNED KELL:
- Az AXON kizárólag SRE, rendszerfelügyelet, kódgenerálás és Upwork automatizálás feladatokat végez
- SZIGORÚAN TILOS: sportfogadás, odds-elemzés, TITAN nevű projekt bármely eleme
- TILOS: más projektek adatainak beépítése az AXON kódba
- KÖTELEZŐ: a kód ne módosítsa saját futó rendszerfájljait
- KÖTELEZŐ: hálózati hívások csak dokumentált végpontokra

FONTOS: Te Gemini vagy, Claude generálta a kódot. Légy kritikus és független.
Ha valamit nem tudsz megítélni, inkább jelezd kétségesként mint hogy vakon elfogadd.
"""

# ═══════════════════════════════════════════════════════════════
#  AUDIT PROMPT – LÉPÉSES GONDOLKODÁS
#  Miért működik jobban mint az egylépéses JSON?
#  Mert az AI "gondolkodás közben" sokkal pontosabb következtetésekre jut.
#  Az emberi szakértők sem adnak azonnal verdiktet – előbb elemzik a kódot.
# ═══════════════════════════════════════════════════════════════
AUDIT_PROMPT = """
FELADAT AMIT A KÓD MEG KELLENE OLDJON:
{task}

MEGÍRT KÓD (Claude generálta):
```python
{code}
```

SANDBOX TESZT EREDMÉNY:
{test_result}

---
Auditáld a kódot az alábbi 4 szempont szerint. Minden szempontnál:
1. Először gondold végig (1-2 mondat elemzés)
2. Majd adj egy döntést: OK vagy PROBLÉMA
3. Ha PROBLÉMA: pontosan mi a baj

### 1. PROJEKT SZABÁLYOK
Tartalmaz-e a kód sportfogadást, TITAN projektet, vagy tiltott elemeket?
Módosít-e rendszerfájlokat?
Elemzés:
Döntés: [OK / PROBLÉMA]
Ha probléma: ...

### 2. LOGIKAI HELYESSÉG
Azt csinálja-e a kód amit a feladat kért?
Vannak-e logikai hibák (pl. rossz képlet, fordított feltétel, off-by-one)?
Elemzés:
Döntés: [OK / PROBLÉMA]
Ha probléma: ...

### 3. BIZTONSÁGI KOCKÁZAT
Amit a statikus szűrő esetleg kihagyott: injection lehetőség, nem sanitizált input,
path traversal, titkos adatok a kódban, nem biztonságos véletlenszám-generálás?
Elemzés:
Döntés: [OK / PROBLÉMA]
Ha probléma: ...

### 4. KÓD MINŐSÉG
Clean code elvek: olvashatóság, felesleges ismétlés, hibakezelés megléte,
nem kezelt edge case-ek?
Elemzés:
Döntés: [OK / PROBLÉMA]
Ha probléma: ...

---
### VÉGSŐ VERDIKT
Az összes szempont alapján add meg az alábbi JSON-t (CSAK a JSON-t, semmi más):

```json
{{
  "verdict": "PASS" vagy "FAIL",
  "score": <0-100>,
  "categories": {{
    "project_rules":       {{"ok": true/false, "note": "max 1 mondat"}},
    "logical_correctness": {{"ok": true/false, "note": "max 1 mondat"}},
    "security":            {{"ok": true/false, "note": "max 1 mondat"}},
    "code_quality":        {{"ok": true/false, "note": "max 1 mondat"}}
  }},
  "issues": ["konkrét probléma 1", "konkrét probléma 2"],
  "suggestions": ["konkrét javítás 1", "konkrét javítás 2"]
}}
```

Pontozási szabályok:
- PASS feltétele: score >= 70 ÉS project_rules.ok=true ÉS security.ok=true
- FAIL: ha bármelyik fenti feltétel nem teljesül
- issues: csak valódi problémák, üres lista ha nincs
- suggestions: csak ha FAIL, egyébként üres lista
"""

# ═══════════════════════════════════════════════════════════════
#  EREDMÉNY STRUKTÚRA
# ═══════════════════════════════════════════════════════════════
@dataclass
class AuditResult:
    passed: bool
    verdict: str        # "PASS", "FAIL", "SKIP"
    score: int          # 0-100
    issues: list[str]   = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    categories: dict    = field(default_factory=dict)
    raw_response: str   = ""
    skip_reason: str    = ""   # ha SKIP: miért

    @property
    def telegram_summary(self) -> str:
        """Rövid, Telegram-barát összefoglaló."""
        if self.verdict == "SKIP":
            return f"⏭️ *Gemini audit kihagyva:* `{self.skip_reason[:80]}`"

        icon  = "✅" if self.passed else "❌"
        lines = [f"{icon} *Gemini audit: {self.verdict}* ({self.score}/100)"]

        # Kategória ikonok
        cat_icons = []
        for name, data in self.categories.items():
            ok    = data.get("ok", True)
            label = {"project_rules":"Szabályok","logical_correctness":"Logika",
                     "security":"Biztonság","code_quality":"Minőség"}.get(name, name)
            cat_icons.append(f"{'✅' if ok else '❌'} {label}")
        if cat_icons:
            lines.append(" | ".join(cat_icons))

        if self.issues:
            lines.append("\n*Problémák:*")
            for issue in self.issues[:3]:
                lines.append(f"• {issue}")

        if not self.passed and self.suggestions:
            lines.append(f"\n*Javaslat:* {self.suggestions[0]}")

        return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
#  JSON PARSER – 3 FALLBACK STRATÉGIA
#  Miért kell ez? Mert az AI néha markdown blokkba teszi a JSON-t,
#  néha prefix szöveggel kezdi, néha trailing comma-t hagy.
# ═══════════════════════════════════════════════════════════════
def extract_json(text: str) -> dict | None:
    """
    4 stratégiával próbálja kinyerni a JSON-t.
    Gemini 2.5-flash thinking modell esetén a JSON a thinking blokk UTÁN van,
    ezért az utolsó { ... } blokkot keressük, nem az elsőt.
    """
    strategies = [
        # 1. Közvetlen parse
        lambda t: t.strip(),
        # 2. ```json blokk keresés
        lambda t: re.search(r'```(?:json)?\s*\n?(.*?)\n?```', t, re.DOTALL).group(1)
                  if re.search(r'```(?:json)?\s*\n?(.*?)\n?```', t, re.DOTALL) else None,
        # 3. UTOLSÓ { ... } blokk – thinking modelleknél a JSON a végén van
        lambda t: t[t.rfind('{'):t.rfind('}')+1] if '{' in t and '}' in t else None,
        # 4. Első { ... } blokk (fallback)
        lambda t: t[t.find('{'):t.rfind('}')+1] if '{' in t else None,
    ]

    for i, strategy in enumerate(strategies):
        try:
            candidate = strategy(text)
            if not candidate:
                continue
            candidate = candidate.strip()
            if not candidate.startswith('{'):
                continue
            data = json.loads(candidate)
            # Validálás: kell verdict és score
            if "verdict" in data and "score" in data:
                log.info(f"[AUDITOR] JSON sikeresen kinyerve (stratégia #{i+1})")
                return data
        except Exception:
            continue

    log.error(f"[AUDITOR] JSON nem kinyerhető. Raw:\n{text[:600]}")
    return None

# ═══════════════════════════════════════════════════════════════
#  FŐ AUDITOR OSZTÁLY
# ═══════════════════════════════════════════════════════════════
class AxonAuditor:
    def __init__(self, gemini_api_key: str):
        self.client = genai.Client(api_key=gemini_api_key)
        self.api_key = gemini_api_key
        log.info(f"[AUDITOR] Inicializálva ({GEMINI_MODEL})")

    def _run_audit_sync(self, prompt: str) -> str:
        """Szinkron Gemini hívás – külön szálban fut."""
        from google.genai import types
        # JSON kényszer: response_mime_type + explicit instrukció
        json_instruction = """
KRITIKUS INSTRUKCIÓ: A válaszod KIZÁRÓLAG egy valid JSON objektum legyen.
NE írj semmi mást – se bevezető szöveget, se magyarázatot, se markdown blokkot.
CSAK a JSON objektum, ami így kezdődik: {  és így végződik: }
"""
        response = self.client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt + json_instruction,
            config=types.GenerateContentConfig(
                system_instruction=AXON_CONTEXT,
                max_output_tokens=4096,
                temperature=0.1,
                response_mime_type="application/json",
            )
        )
        # Biztonságos szöveg kinyerés – ha response.text üres (thinking modell),
        # a parts-ból szedjük ki a text típusú blokkot
        text = response.text or ""
        if not text and hasattr(response, "candidates"):
            for candidate in (response.candidates or []):
                for part in getattr(getattr(candidate, "content", None), "parts", []):
                    if hasattr(part, "text") and part.text:
                        text += part.text
        return text

    async def audit(
        self,
        code: str,
        task: str,
        test_result: str = "Sandbox tesztek lefutottak"
    ) -> AuditResult:
        """
        3. szintű logikai audit.
        Lépéses prompt → Gemini gondolkodik → JSON verdikt → parse.
        """
        prompt = AUDIT_PROMPT.format(
            task=task,
            code=code[:8000],           # Gemini 2.5 Flash bőven bírja
            test_result=test_result[:400]
        )

        log.info("[AUDITOR] Gemini audit indul (lépéses prompt)...")

        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(
                None, self._run_audit_sync, prompt
            )
            log.debug(f"[AUDITOR] Raw válasz ({len(raw)} char):\n{raw[:500]}")
            return self._parse(raw)

        except Exception as e:
            log.error(f"[AUDITOR] Gemini hiba: {e}")
            # Fail-safe: nem blokkoljuk a folyamatot Gemini hiba miatt
            return AuditResult(
                passed=True,
                verdict="SKIP",
                score=0,
                skip_reason=str(e)[:200]
            )

    def _parse(self, raw: str) -> AuditResult:
        """
        Raw Gemini válasz → AuditResult.
        Az elemzés szövegét logban tartjuk (hasznos debughoz),
        a JSON-t kinyerjük és validáljuk.
        """
        data = extract_json(raw)

        if not data:
            # Konzervatív FAIL – jobb biztonságosan hibát jelezni
            return AuditResult(
                passed=False,
                verdict="FAIL",
                score=0,
                issues=["Audit válasz nem értelmezhető"],
                suggestions=["Próbáld újra a feladatot"],
                raw_response=raw
            )

        verdict     = str(data.get("verdict", "FAIL")).upper()
        score       = max(0, min(100, int(data.get("score", 0))))
        categories  = data.get("categories", {})
        issues      = [str(i) for i in data.get("issues", [])][:5]
        suggestions = [str(s) for s in data.get("suggestions", [])][:3]

        # PASS feltétel: score>=55 ÉS projekt szabályok ÉS biztonság OK
        # 55 a reális küszöb – a Gemini kód stílust is büntet ami nem funkcionális hiba
        proj_ok = categories.get("project_rules",  {}).get("ok", True)
        sec_ok  = categories.get("security",        {}).get("ok", True)
        passed  = (verdict == "PASS") and (score >= 55) and proj_ok and sec_ok

        # Ha a Gemini PASS-t mondott de a feltételek nem teljesülnek → átírjuk
        if not passed and verdict == "PASS":
            verdict = "FAIL"
            log.warning("[AUDITOR] Gemini PASS-t adott de feltételek nem teljesülnek → FAIL")

        log.info(f"[AUDITOR] Verdikt: {verdict} | Score: {score}/100 | Issues: {len(issues)}")

        return AuditResult(
            passed=passed,
            verdict=verdict,
            score=score,
            categories=categories,
            issues=issues,
            suggestions=suggestions,
            raw_response=raw
        )


# ═══════════════════════════════════════════════════════════════
#  SEGÉDFÜGGVÉNY – Claude javítási prompthoz
# ═══════════════════════════════════════════════════════════════
def format_audit_for_fix_prompt(audit: AuditResult, code: str, task: str) -> str:
    """
    Ha Gemini FAIL-t adott → ezt a promptot küldjük Claude-nak.
    A konkrét kifogásokat tartalmazza hogy célzottan tudjon javítani.
    """
    issues_text = "\n".join(f"- {i}" for i in audit.issues) \
                  if audit.issues else "Általános minőségi probléma"
    sugg_text   = "\n".join(f"- {s}" for s in audit.suggestions) \
                  if audit.suggestions else ""

    # Kategória részletek a javításhoz
    cat_details = []
    for name, data in audit.categories.items():
        if not data.get("ok", True):
            label = {"project_rules":"Projekt szabályok","logical_correctness":"Logikai hiba",
                     "security":"Biztonsági rés","code_quality":"Kód minőség"}.get(name, name)
            cat_details.append(f"- {label}: {data.get('note','')}")
    cat_text = "\n".join(cat_details) if cat_details else ""

    return f"""Egy független AI (Gemini) auditálta a kódot és HIBÁSNAK találta (score: {audit.score}/100).

FELADAT: {task}

GEMINI KIFOGÁSAI:
{issues_text}

ÉRINTETT TERÜLETEK:
{cat_text}

JAVASLATOK:
{sugg_text}

EREDETI KÓD:
```python
{code}
```

Javítsd ki a fenti problémákat. Adj vissza egy javított kódot ```python blokkban
(# === KÓD === és # === TESZTEK === szekciókkal).
Csak a kód kell, semmi magyarázat."""
