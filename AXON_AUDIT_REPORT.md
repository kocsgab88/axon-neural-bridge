# AXON Neural Bridge — `core/pipeline.py` Code Review

**Reviewer:** Anthropic-szintű audit
**Target:** `C:\AXON_OPS\AxonV2\core\pipeline.py` (v9.0, 699 sor)
**Modell-kontextus:** `C:\AXON_OPS\AxonV2\models.py` (Pydantic v2)
**Dátum:** 2026-05-06

---

## 1. Vezetői összefoglaló

A `pipeline.py` a v9.0 refactor eredménye: egy 550 soros monolit szétszedve 5 felelősségi körre (`CodeGenerator`, `AuditFixLoop`, `OutputWriter`, `CostAccumulator`, `DeveloperPipeline`). A separation of concerns **alapvetően helyes**, és a `models.py` Pydantic v2 réteg jó típusos szerződést biztosít a határon. Két szinten viszont a kód **nem éri el** a production-ready szintet:

1. **Belső interfész hiányosság** — a `DeveloperPipeline` 17 nyers `Callable`-t és típusozatlan `sandbox`/`auditor` objektumot kap, ami megöli a tesztelhetőséget és elrejti a kontraktus-eltéréseket.
2. **Költség- és hibakezelési résréteg** — a korai `return`-ök elveszítik a már elköltött tokeneket, a fix-loop csendben megszakad, a Claude-prompt egységesen Markdown-Hungarian — minden egyetlen, monolitikus `run()`-ban.

Az alábbi findingeket **súlyosság szerint címkéztem**:
- 🔴 **CRITICAL** — production-blocker, adatvesztés vagy biztonsági kockázat
- 🟠 **HIGH** — komoly minőségi/működési hiba, fix javasolt v9.1-re
- 🟡 **MEDIUM** — technikai adósság, refactor érdemű
- 🟢 **LOW** — kódstílus / nice-to-have

| Súlyosság | Darab |
|-----------|-------|
| 🔴 CRITICAL | 4 |
| 🟠 HIGH | 9 |
| 🟡 MEDIUM | 11 |
| 🟢 LOW | 7 |

---

## 2. Architektúra

### 🟠 H-1 — `DeveloperPipeline.__init__` god-constructor (17 paraméter)
`pipeline.py:515-551` — A konstruktor 5 osztály + 12 callback-et fogad. Ez:
- Minden tesztben 17 mockot követel.
- Elrejti, hogy a `_get_cached`/`_save_cached`/`_turn_count`/`_get_last_code`/`_add_history` valójában **egy `Memory` interfészhez** tartoznak.
- A `_save_training`, `_get_patterns`, `_get_few_shot`, `_save_fix` (utóbbi az `AuditFixLoop`-ban) ugyanezen objektum különböző metódusait jelentik szétszórva.

**Javaslat:** Vezess be két `Protocol`-t (`MemoryStore`, `LearningStore`) és csökkentsd a paramétert ~6-ra. A `format_sandbox_report` és `risk_keywords` természetes helye egy `PipelineConfig` dataclass.

### 🟠 H-2 — `sandbox` és `auditor` típusozatlan
`pipeline.py:342-346`, `:521-522`. A `__init__` mind az `AuditFixLoop`, mind a `DeveloperPipeline` esetén bare nevekkel kapja, **annotáció nélkül**. A `sandbox.validate_with_retry(...)`, `auditor.audit(...)`, `sandbox_result.success`, `.final_code`, `.tests_passed`, `.tests_total`, `.stdout`, `.stderr`, `.attempt` mind duck-typed — egyetlen elgépelés runtime hibát ad.

**Javaslat:** definiálj `Sandbox` és `Auditor` `Protocol`-t (PEP 544) a `models.py`-ban vagy egy új `core/contracts.py`-ban, és írd ki a paramétereket: `sandbox: Sandbox`. Ez megmentene egy egész osztály bug-ot statikusan.

### 🟡 M-1 — Promptok hard-coded a generátoron belül
`pipeline.py:107-114, 135-165, 198-228, 240-251, 262-283, 296-308`. A 6 különböző prompt változó-interpolációval inline, ami:
- Tesztelhetetlenné teszi a "ugyanaz a prompt-e két verzió között?" diff-et.
- Promp tuninghoz minden kis átfogalmazás Python-pull-request.
- Nincs verziótlan "prompt registry" (Anthropic best practice: külön YAML/markdown a promptoknak).

**Javaslat:** `core/prompts/developer/` alá külön `simple_step1.md`, `complex_session1.md` stb. fájlok; betöltés `importlib.resources`-szal. Diffelhetővé válik, A/B tesztelhetővé válik.

### 🟡 M-2 — Magic konstansok
`pipeline.py:34-35` `AUDIT_MAX_RETRIES = 2` és `SANDBOX_MAX_RETRIES = 3` modul-szintű konstans. Nem konfigurálható környezeti változón keresztül, nem injektálható tesztben.

**Javaslat:** vagy `PipelineConfig` mezők, vagy `os.getenv("AXON_AUDIT_MAX_RETRIES", "2")` lookup egy `config.py`-ban.

### 🟡 M-3 — `core/pipeline.py` lapos `from models import ...`
`pipeline.py:27`. A `core/` mappában lévő modul a **projekt-gyökér** `models.py`-jából importál. Ez `sys.path` injection-re épül; ha valaki `python -m core.pipeline` helyett másképp futtatja (pl. `pytest core/test_pipeline.py` rossz pwd-ből), `ModuleNotFoundError`-t kap. A `models.py` is gyökérszinten van, nem `axon/models.py`.

**Javaslat:** csomagosítsd egységesen (`axon/__init__.py`, `axon/core/pipeline.py`, `axon/models.py`), és használj abszolút importot `from axon.models import ...`.

### 🟢 L-1 — `DeveloperPipeline.run()` 145 soros method
`pipeline.py:553-698`. Olvasható (számozott szekciók), de nehezen unit-tesztelhető. Egy-egy lépés (cache, few-shot, history, generálás, sandbox, audit, fix-loop, fájlmentés, cost, training) önálló privát metódusként valószínűleg jobb lenne.

---

## 3. Hibakezelés

### 🔴 C-1 — Token-elszámolás eldobódik korai return-en
`pipeline.py:604-608, 615-618, 629-637`. Három korai return az `if` után — **egyik sem hívja a `self.cost.finalize(task)`-ot**. Ha a sandbox elbukik vagy a user nem hagyja jóvá a kockázatos kódot, a Claude-hívásokra **már elköltött** tokenek **soha nem mentődnek** az `api_costs` táblába és nem kerülnek be a `PipelineResult`-ba. Ez a **legfontosabb production bug**: a billing alulszámol.

**Javaslat:**
```python
try:
    ...  # teljes flow
finally:
    if not is_cache_hit:
        cost_usd, tokens = self.cost.finalize(task)
        # build result with cost-fields
```
Vagy: minden korai return előtt `self.cost.finalize(task)` és a result-ba beégetni a tokeneket.

### 🔴 C-2 — `AuditFixLoop` csendben megszakad rossz Claude válasznál
`pipeline.py:387-389`:
```python
new_code = _extract_code_block(fixed_response)
if not new_code:
    break
```
Nincs log, nincs `_save_fix`, nincs `status_cb` üzenet. Ha Claude egy körben üres / nem-kód választ ad (rate-limit, hiányos response), a loop megszakad, a `validated_code` és `audit_result` változatlan marad, és a hívó nem tudja, hogy a fix-kísérlet megtörtént-e.

**Javaslat:** legalább `log.warning("[FIX] Claude válasz nem tartalmaz kódblokkot — break")`, és hívd `self._save_fix(..., fix_succeeded=False)`-t a teljes audit-trail miatt.

### 🔴 C-3 — `estimate_complexity` nem fault-tolerant
`pipeline.py:101-126, 595`. Ha a Claude komplexitás-becslő hívás dob (timeout, 429, network), a teljes `run()` hibára fut **fájlmentés és cost-finalize előtt** — pedig egy konzervatív fallback (`COMPLEX`) tökéletesen működne.

**Javaslat:**
```python
try:
    complexity = await self.generator.estimate_complexity(task, status_cb)
except Exception as e:
    log.warning(f"[GEN] Komplexitás becslés hiba ({e}), fallback: COMPLEX")
    complexity = TaskComplexity.COMPLEX
```

### 🔴 C-4 — Cache HIT nem validál, nem auditál
`pipeline.py:567-575`. A cache-elt választ `output`-ra állítja, `success=True` jelöléssel. Ha a cache-be **korábban** egy gyenge audit-pontszámú vagy futás közben behavior-driftelt kód került, az minden további hívásnál visszajön. **Nincs cache-invalidáció, nincs TTL ellenőrzés ezen a layerren** (a `CacheEntry` modell `created_at`-ja megvan, de nem nézzük itt).

**Javaslat:** vagy revalidálj sandbox-on egy gyors smoke-teszttel, vagy állíts be max-age-et: `if (now - cached.created_at) > timedelta(days=N): skip cache`.

### 🟠 H-3 — `try/except Exception` szélespentumú swallow
- `pipeline.py:73-77` `_build_fix_block` JSON-parse: helyén való hogy elnyeli, de `log.debug` legalább elvárható.
- `pipeline.py:471-473` `write_readme`: `Exception` → `""`. A felhasználó **nem tudja**, hogy a README megpróbált generálódni és elbukott.
- `pipeline.py:672-673` fájlmentés: `Exception` → log.error és továbbmegy `output_file=None`-nal. A `PipelineResult.success=True` lehet, miközben a kód NEM mentődött lemezre. **A user üzenetet kap "kész"-ről, de fájl nincs.**

**Javaslat:** szűkítsd a kivételtípust (`OSError`, `PermissionError`), és a `PipelineResult`-ba tegyél egy `warnings: list[str]` mezőt, hogy a Telegram handler kiírhassa.

### 🟠 H-4 — Több `datetime.now()` race
`pipeline.py:441, 449, 663`. A `OutputWriter.write()` saját `timestamp`-et generál (L441), `DeveloperPipeline.run()` pedig saját külön `timestamp`-et (L663). Mivel mindkettő `datetime.now()`-on alapszik, **ugyanazon futás .py és README fájlja másodperc-eltéréssel eltérő nevet kaphat**, ha a hívás épp átlépi a másodperchatárt. Ez subtle bug a fájl-páríghozzárendelésnél.

**Javaslat:** generáld egyszer, add át paraméterként mind az `OutputWriter.write()`-nek, mind a `write_readme()`-nek. Vagy: `self.writer.write()` adja vissza `(filepath, filename, timestamp, safe_task)` négyest.

### 🟠 H-5 — Generálási hiba nem mégis-pipálódik tovább
`pipeline.py:604-608`. Ha `code.strip()` üres, return false-szal. De az **estimate_complexity** és az **első session(ek)** Claude-tokenjeit már elköltöttük (lásd C-1), és a `_call_claude` lehet, hogy egy retry-jal mégis adott volna kódot.

**Javaslat:** az üres-kód eseten egy retry, mielőtt feladjuk.

### 🟡 M-4 — `sandbox_result` "object" return-típus
`pipeline.py:362` `tuple[str, AuditResult, object]`. A `SandboxResult` bőven létezik a modellben — itt szándékos, hogy ne legyen circular import? Nem, mindkettő ugyanazt a `models.py`-t importálja.

**Javaslat:** `tuple[str, AuditResult, SandboxResult]`.

### 🟡 M-5 — `_build_fix_block` rejtett függőség `s["bad_code"]`/`s["fixed_code"]` formátumtól
`pipeline.py:74-83` — `s` egy dict, ami feltehetőleg `FixSample`-ből származik (`models.py:303`). De a `models.FixSample` `gemini_issues: list[str]`, míg itt `s["issues"]` szerepel — **eltérő kulcsnév**. A rendszer valószínűleg a DB row-t adja vissza dict-ként más kulcsnevekkel. Pydantic szempontból ez egy **alias-réteg-szivárgás**.

**Javaslat:** `FixSample` Pydantic objektumot adj át, vagy definiálj egy `FixSampleDict = TypedDict(...)` legalább.

---

## 4. Type safety

### 🟠 H-6 — `Callable` aláírás nélkül
`pipeline.py:97, 341, 434, 484-491, 515-534`. A `Callable` típus paraméterek-és-return-érték nélkül elszúrt elgépelést **nem** kap el statikusan. Példa: `call_claude_tracked` 4 kwargs-szal hívódik meg (`system=`, `user_msg=`, `max_tokens=`, `chat_id=`); aki tévesen `pos_arg`-okkal írná újra, csak runtime-ban derülne ki.

**Javaslat:** definiáld a tipikus callable signature-öket `Protocol`-lal:
```python
class ClaudeCaller(Protocol):
    async def __call__(
        self, *, system: str, user_msg: str,
        max_tokens: int = 4000, chat_id: str | None = None,
    ) -> str: ...
```

### 🟡 M-6 — `dict` típusú few-shot adatok
`pipeline.py:55, 60-62, 66, 74-82`. `patterns: list[dict]` és `samples: list[dict]` — kulcsnévre épülő hozzáférések (`p['similarity']`, `p['prompt']`, `p['code_snippet']`, `s['issues']`, `s['score']`, `s['bad_code']`, `s['fixed_code']`). Egyetlen elgépelés `KeyError` runtime-ban.

**Javaslat:** TypedDict vagy dedikált Pydantic model (`SuccessPattern`, `FixExample`).

### 🟡 M-7 — `risk_approval: Callable | None`
`pipeline.py:557, 612-614`. A return type-ja nem dokumentált — `await risk_approval(risks, str(uuid.uuid4())[:8])` `bool`-t vár (`if not approved`).

**Javaslat:**
```python
RiskApproval = Callable[[list[str], str], Awaitable[bool]]
```

### 🟢 L-2 — `import json as _j` függvényen belül
`pipeline.py:70`. Felesleges, mivel a fájl elejére is felmehet (nincs nehéz import). A `_j` aliasnak nincs technikai indoka.

---

## 5. Tesztelhetőség

### 🟠 H-7 — Kemény `datetime.now()` és `uuid.uuid4()` hívások
`pipeline.py:441, 443, 449, 613, 663`. Ezek **közvetlenül** dt/uuid nyelvi hívások — tesztben monkeypatch-elni kell a `datetime.now`-ot vagy időutazni. Determinista snapshot-teszt nehéz.

**Javaslat:** injektálj `now: Callable[[], datetime]` és `gen_id: Callable[[], str]` callable-öket a `DeveloperPipeline` és `OutputWriter` ctor-ba (vagy `clock`/`id_provider` Protocol). Default érték `datetime.now`/`uuid.uuid4`.

### 🟡 M-8 — Túl sok status_cb call → tesztben "logikai" zaj
`pipeline.py` ~25 különböző `await status_cb(...)` hívás. Egy unit teszt vagy mindet csendre teszi, vagy verifikál mindegyiket — utóbbi rideg (a UI-szöveg módosulása töri a tesztet).

**Javaslat:** absztrakt `StatusReporter` Protocol, ami struktúrált eseményeket emit-tál (`reporter.step("complexity")`, `reporter.session_progress(1, 4)`); a Telegram formatter külön réteg.

### 🟡 M-9 — `_extract_code_block` és `_build_*` modul-szintű függvények
`pipeline.py:44, 55, 66`. Tesztelhetők (`from pipeline import _extract_code_block`), de privát névkonvenció ellentmondó. A `re.findall(... re.DOTALL)` és `max(matches, key=len)` viselkedés edge case-ekre érdekes (több-blokk, üres blokk, sor-eleji nem-`python` fence).

**Javaslat:** publikus `extract_code_block(text: str) -> str` egy `core/text_utils.py`-ban, dedikált tesztsorral.

---

## 6. Biztonság

### 🟠 H-8 — Risk keyword filter triviálisan kerülhető
`pipeline.py:611` `risks = [kw for kw in self._risk_kws if kw in code.lower()]`.
- Substring-match: `"exec"` ⇒ illeszkedik a `"execute"`, `"executor"`, `"execve"` szavakra is → false-positive felugrók.
- Másfelől trivially bypass-olható: `getattr(__builtins__, "ex" + "ec")(...)`, `__import__("os").system(...)`, base64 dekódolás, `eval(b)`, `compile()`, `os.popen()`, importok aliasolva.

A **valódi** védelmet az **AST-elemzés** vagy a **Sandbox/seccomp** adja. Itt jelenleg a **fő védelem** a sandbox réteg (kívül van), de ez a keyword-filter a usernek azt sugallja, hogy "kockázatos kódra rákérdezünk", miközben az `os.system` egy formázott alakja átengedi.

**Javaslat:**
- AST-alapú scanner (`ast.parse` → `os.system`/`subprocess.*`/`eval`/`exec`/`compile`/`__import__`/`pickle.loads`/`socket` node-keresés).
- Vagy: dokumentáld explicit, hogy ez **csak heuristic UX-warning**, nem biztonsági control. A `# 6. Kockázati szűrő` komment félrevezető.

### 🟡 M-10 — Cache-poisoning vektor
`pipeline.py:567-575`. Az audit-cache-be került első "sikeres" minta minden további azonos-prompt esetén kérdés nélkül felolvasásra kerül. Ha bármikor a sandbox/audit kompromittálódik vagy egy lazább szabálykészlettel fut le egy futás, **a rossz minta beragad**. Nincs verzió-bélyeg az audit-szabályokon, ami invalidálná a cache-t (pl. a `system_prompt` hash-e).

**Javaslat:** a cache-kulcsba kerüljön bele a `system_prompt` SHA-256-ja és az `AUDIT_MAX_RETRIES` értéke; szabályváltozáskor a cache automatikusan érvénytelenedik.

### 🟢 L-3 — Fájlnév-szanitizáció jó, de ütközéskezelés nincs
`pipeline.py:442` `safe_task = re.sub(r"[^a-zA-Z0-9]", "_", task.text[:40]).strip("_")`. Ez **biztonságosan** védi path-traversaltől. De timestamp + 40-char prefix ⇒ ha egy másodpercen belül 2 ugyanolyan prefixű feladat fut, **a második felülírja az elsőt**.

**Javaslat:** add hozzá a `task.request_id` rövid alakját (`task.request_id.hex[:6]`).

### 🟢 L-4 — Logok kódot tartalmazhatnak
`pipeline.py:182, 256, 288, 328, 421` stb. A `len(code)` és hasonló metrika OK, de néhol pl. a fix-loop `audit_result.issues[0][:80]` Telegram-üzenetben megjelenik (L371). Ha az issues-szöveg user-supplied promptot tartalmaz, **és** Telegram MarkdownV2-ben renderelődik, a felhasználó injektálhat vezérlőkaraktert.

**Javaslat:** `audit_result.issues[0]` Telegram-felé átfutás előtt menjen át egy MarkdownV2 escape-en (a bot rétegben, ne itt — de **dokumentáld**, hogy ez NEM escaped output).

---

## 7. Production readiness

### 🟠 H-9 — Nincs telemetria/tracing
A pipeline 12 lépéses, async, hosszú futású. Pure `log.info("...")` van, **nincs span/trace ID**, nincs metrika (`step_duration_ms`, `tokens_per_step`, `cache_hit_rate`). Egy production-incidentnél a "miért tartott 90 másodpercig?" kérdésre **csak a logok mintázatából** lehet visszafejteni.

**Javaslat:** OpenTelemetry vagy minimum strukturált log (`extra={"step": "audit", "duration_ms": ...}`); a `task.request_id` minden log-line-ban jelenjen meg.

### 🟡 M-11 — Idempotencia hiánya
A `task.request_id` Pydantic-szinten létezik (`models.py:91`), de a pipeline **nem használja** dedup-ra. Ha a Telegram handler ismétlődő `update_id`-t kap (Telegram polling retry), az egész pipeline újrafut.

**Javaslat:** a `_get_cached`/`_save_cached` egészüljön ki egy `request_id`-alapú in-flight lookup-pal, vagy a handler használjon update-id-tárat.

### 🟡 M-12 — Hungarian + Markdown szövegek beégetve
`pipeline.py` ~25 status_cb és output-szöveg (pl. `"❌ *Sandbox sikertelen* {SANDBOX_MAX_RETRIES} próba után\n\n..."`). i18n-zhetetlen, és Telegram-specifikus formázást feltételez (`*bold*` MarkdownV2-ben **escape-elendő**, pl. `*` előtti pont). Ez most nem a `pipeline` réteg dolga lenne.

**Javaslat:** mozgasd ki a végfelhasználói szövegeket a `bot/messages.py` modulba; a pipeline csak strukturált `PipelineResult`-ot adjon vissza, a Telegram réteg formáz.

### 🟢 L-5 — `if __name__ == "__test__":` egyedi konvenció
`pipeline.py:164, 178, 277, 302, 322`. Nem standard Python — Sandbox custom konvenciója. Ha **dokumentálva van** a sandbox modulban, OK. Ha nem, akkor minden új fejlesztő számára meglepetés.

**Javaslat:** legyen egy `# === TESZTEK ===` és `__test__` konvenció külön `core/conventions.md`-ben dokumentálva.

### 🟢 L-6 — String-konstansok ismétlődnek
`pipeline.py:171, 176, 247, 250, 268, 274, 282, 303, 306, 316, 322`. A `"# === KÓD ==="` és `"# === TESZTEK ==="` szöveg ~10 helyen.

**Javaslat:**
```python
CODE_MARKER = "# === KÓD ==="
TEST_MARKER = "# === TESZTEK ==="
```

### 🟢 L-7 — `validated_code` és `code` változónevek átfedése
`pipeline.py:599-606, 622-639`. Először `code` (raw), aztán `validated_code = sandbox_result.final_code` (sandboxolt). A fix-loop visszafelé módosítja a `validated_code`-ot. A flow **olvasható**, de a `validated_code` névhasználat nem konzisztens — a `code`-tól csak a sandbox után lesz, de a `# 5. Generálás` után **nincs** `validated_code` még.

---

## 8. Konkrét bug-listák (fix-priorizált)

| # | Súly | Hely | Bug |
|---|------|------|-----|
| 1 | 🔴 | `:604, :615, :629` | Korai return → `cost.finalize()` kimarad → token-billing alulszámol |
| 2 | 🔴 | `:387-389` | `AuditFixLoop` csendben break-el, `_save_fix` nem hívódik |
| 3 | 🔴 | `:595` | `estimate_complexity` exception → teljes pipeline összeomlik fallback nélkül |
| 4 | 🔴 | `:567-575` | Cache HIT nem validál újra, no TTL — drift-veszély |
| 5 | 🟠 | `:441, :663` | Két különálló `datetime.now()` → .py és README timestamp-mismatch lehet |
| 6 | 🟠 | `:611` | Substring risk-filter triviálisan bypass-olható |
| 7 | 🟠 | `:672-673` | Fájlmentési hiba elnyelve, `success=True` mehet ki üres fájllal |
| 8 | 🟠 | `:471-473` | README hiba elnyelve, user nem értesül |
| 9 | 🟡 | `:74` | `s["issues"]` vs `models.FixSample.gemini_issues` — kulcsnév-eltérés |
| 10 | 🟡 | `:258` | `clean_code = ... if s3a_code else combined_raw.strip()` — `_extract_code_block` sosem ad vissza üreset érdemi inputon → dead else-ág |
| 11 | 🟡 | `:613` | `uuid.uuid4()[:8]` → ütközés nem zárható ki kis volumenben sem; ráadásul nem injektált |

---

## 9. Pozitívumok (érdemes megőrizni)

- ✅ **Tiszta SRP felosztás** 5 osztályra; a `DeveloperPipeline` valóban orchestrátor.
- ✅ **`from __future__ import annotations`** jelen van — modern típushasználat.
- ✅ **Pydantic v2 modellek** szigorú validátorral (`tests_consistency`, `text_not_empty`).
- ✅ **`AuditResult.skipped()` és `.failed()` factory metódusok** — DRY és tesztbarát.
- ✅ **Számozott `# 1. ... # 12.` lépés-kommentek** a `run()`-ban — nagyon olvasható.
- ✅ **Few-shot pattern + fix sample integráció** — tanuló-rendszer alapja megvan.
- ✅ **`status_cb` callback injekció** — a Telegram I/O kívül marad.
- ✅ **`StatusCallback` típusalias** definiálva.
- ✅ **Memóriafüggvények kiinjektálva** — elvileg könnyen mockolhatóak (a probléma csak a darabszám).

---

## 10. Javasolt v9.1 roadmap

**Sprint 1 (kritikus, 1-2 nap):**
1. Cost-finalize garanciálása `try/finally` blokkban (C-1).
2. `AuditFixLoop` break-pontok logolása + `_save_fix` minden esetben (C-2).
3. `estimate_complexity` graceful fallback (C-3).
4. Cache-kulcs SHA-256 + TTL (C-4 / M-10).

**Sprint 2 (interfészek, 2-3 nap):**
5. `Sandbox`, `Auditor`, `MemoryStore`, `LearningStore` Protocol-ok (H-1, H-2).
6. `ClaudeCaller` Protocol + tipizált `Callable`-ek (H-6).
7. `clock`/`id_provider` injektálás (H-7).
8. Risk filter AST-alapra cserélés (H-8).

**Sprint 3 (operability, 2-3 nap):**
9. OpenTelemetry / strukturált log + `request_id` propagáció (H-9).
10. Promptok kiemelése `core/prompts/`-ba (M-1).
11. Telegram-formattálás kimozgatása `bot/messages.py`-ba (M-12).

---

## 11. Záró értékelés

A `pipeline.py` v9.0 egy **erős mérnöki alap** egy MVP→production átmenetben. A `models.py` Pydantic-réteg **az audit kedvelt része** — a határon ott van a típus-szigor. A `pipeline.py` viszont a **belső kontraktusoknál** ad le pontot: 17 `Callable` és duck-typed `sandbox/auditor` a tesztelést és statikus elemzést **lényegében ellehetetleníti**.

A négy CRITICAL bug közül három (C-1, C-2, C-3) **adatvesztést és billing-alulszámolást** okoz, az egyik (C-4) **kódminőség-driftet** jelenthet. Ezek `try/finally` és néhány log-sor árán **fél nap alatt** javíthatók — utána a v9.0 architektúra **production-ready**, és a v9.1 a típusos interfész-réteget hozhatja.

**Összesített pontszám:** **6.8 / 10** (architektúra 8, hibakezelés 5, type safety 6, tesztelhetőség 5, biztonság 7, production readiness 7).
