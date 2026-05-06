# AXON Neural Bridge — Code Audit Report
## `core/pipeline.py` — Anthropic-szintű teljes review

**Dátum:** 2026-05-06  
**Vizsgált fájl:** `core/pipeline.py` (v9.0, 699 sor)  
**Kapcsolódó fájlok:** `models.py`, `main.py`, `tests/test_pipeline.py`  
**Reviewer:** Claude Code (claude-sonnet-4-6)  
**Projekt:** AXON Neural Bridge v9.0

---

## Összefoglaló (Executive Summary)

A `core/pipeline.py` architekturálisan kiforrott kód. Az 5 izolált osztály (CodeGenerator, AuditFixLoop, OutputWriter, CostAccumulator, DeveloperPipeline) jól szétválasztja a felelősségeket, a dependency injection következetes, és az osztályok önállóan tesztelhetők. A kód olvasható, a Telegram I/O tisztán el van különítve az üzleti logikától.

Ugyanakkor a review **3 kritikus bugot**, **4 közepes súlyú problémát** és **5 kisebb fejlesztési lehetőséget** azonosított. A legkomolyabb probléma egy **contract mismatch a tesztek és az implementáció között**, amely azt jelenti, hogy a tesztek közül több nem azt teszteli, amit gondolnánk — a teszt suite hamis biztonságérzetet ad.

---

## Súlyossági besorolás

| Szint | Leírás | Darab |
|-------|--------|-------|
| 🔴 KRITIKUS | Bug, contract mismatch, adatvesztési kockázat | 3 |
| 🟠 KÖZEPES | Design smell, silent failure, deprecated API | 4 |
| 🟡 KISEBB | Karbantarthatóság, elnevezés, dead code | 5 |

---

## 🔴 KRITIKUS PROBLÉMÁK

---

### BUG-01: `_extract_code_block` — kontrakt mismatch a tesztekkel

**Fájl:** `core/pipeline.py:44–52`  
**Súlyosság:** 🔴 KRITIKUS

**Probléma:**

```python
def _extract_code_block(text: str) -> str:
    if not text:
        return ""            # ← "" visszatérés, nem None
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    return text.strip()     # ← fallback: visszaadja az eredeti szöveget, nem None
```

A tesztek (`tests/test_pipeline.py:33–39`) viszont `None`-t várnak:

```python
def test_no_block_returns_none(self):
    assert _extract_code_block("nincs kód blokk") is None   # FAIL — "nincs kód blokk"-ot kap

def test_empty_string_returns_none(self):
    assert _extract_code_block("") is None                   # FAIL — "" kap

def test_none_returns_none(self):
    assert _extract_code_block(None) is None                 # FAIL — "" kap
```

Ez **3 teszt garantált FAIL**, ha valaha futnak. A tesztek téves biztonságérzetet nyújtanak.

**Downstream hatás:**  
A `generate_simple()` (line 147) `or ""` fallback-kel hívja:
```python
s1_code = _extract_code_block(s1_resp) or ""
```
Ez jelenleg elfedi a bugot, mert ha Claude nem ad vissza kód blokkot, a `text.strip()` fallback értéket kapjuk, amit az `or ""` nem nulláz ki — tehát `s1_code` tele lesz raw szöveggel Claude markdown formázással, ami aztán tesztként fut le a sandboxban és hibát okoz.

**Javítás:**

```python
def _extract_code_block(text: str | None) -> str | None:
    if not text:
        return None
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    return None   # nincs code block → None, nem raw szöveg
```

Ezzel együtt frissíteni kell minden hívási helyet:
```python
s1_code = _extract_code_block(s1_resp) or ""
```
Ez az `or ""` pattern helyes marad az összes 6 hívási helyen.

---

### BUG-02: Timestamp mismatch a .py fájl és a README neve között

**Fájl:** `core/pipeline.py:661–671`  
**Súlyosság:** 🔴 KRITIKUS (adatintegritás)

**Probléma:**

A `DeveloperPipeline.run()` step 10-ben:
```python
timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")   # ← T1
safe_task_s = re.sub(r"[^a-zA-Z0-9]", "_", task.text[:40]).strip("_")
_, filename = self.writer.write(task, validated_code, ...)  # ← write() saját T2-t generál
readme_file = await self.writer.write_readme(
    ..., timestamp=timestamp, safe_task=safe_task_s, ...   # ← T1-et kap
)
```

Az `OutputWriter.write()` belsejében azonban saját timestamp-et generál:
```python
def write(self, task, validated_code, ...) -> tuple[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # ← saját T2
    filename  = f"{timestamp}_{safe_task}.py"              # ← T2 alapján
```

Eredmény: ha T1 ≠ T2 (pl. 1 másodperces eltérés is elég):
- `.py` fájl neve: `20260506_143201_feladat.py`
- README neve: `20260506_143200_feladat_README.md`

A fájlpár összetartozása elvész.

**Javítás:**

Az `OutputWriter.write()` térjen vissza a saját timestampjével is:
```python
def write(self, ...) -> tuple[str, str, str]:  # (filepath, filename, timestamp)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ...
    return str(filepath), filename, timestamp
```

Majd a pipeline-ban:
```python
_, filename, timestamp = self.writer.write(task, validated_code, ...)
safe_task_s = re.sub(r"[^a-zA-Z0-9]", "_", task.text[:40]).strip("_")
```

---

### BUG-03: `SANDBOX_MAX_RETRIES` konstans soha nem kontrollálja a sandbox retry-okat

**Fájl:** `core/pipeline.py:35, 633`  
**Súlyosság:** 🔴 KRITIKUS (félrevezető dokumentáció + lehetséges jövőbeli bug)

**Probléma:**

```python
SANDBOX_MAX_RETRIES = 3   # ← line 35, module-level konstans
```

A konstanst CSAK az error üzenetben használják:
```python
output=(
    f"❌ *Sandbox sikertelen* {SANDBOX_MAX_RETRIES} próba után\n\n"
    ...
)
```

De a tényleges sandbox retry-ok száma az `AxonSandbox.validate_with_retry()` belső logikájától függ (amelyet az `axon_sandbox_v2.py` határoz meg, és lehet más mint 3). Ha a sandbox implementáció megváltozik és 5 próbát végez, az error üzenet még mindig "3 próba" fog mutatni.

Ráadásul a `DeveloperPipeline.__init__` nem kap `sandbox_max_retries` paramétert, tehát nincs lehetőség ezt konfigurálni a dependency injection útján sem.

**Javítás:**

A konstanst vagy töröld (és olvasd ki a `sandbox_result.attempt` értékből), vagy add át a sandbox objektumnak konfigurációként:
```python
output=(
    f"❌ *Sandbox sikertelen* {sandbox_result.attempt} próba után\n\n"
    ...
)
```

---

## 🟠 KÖZEPES PROBLÉMÁK

---

### DESIGN-01: `AuditFixLoop.run` — nem típusos `sandbox_result` paraméter

**Fájl:** `core/pipeline.py:353–363`  
**Súlyosság:** 🟠 KÖZEPES

```python
async def run(
    self,
    task: Task,
    validated_code: str,
    audit_result: AuditResult,
    sandbox_result,          # ← típus nincs annotálva!
    ...
```

A sandbox_result-ot `getattr` hívásokkal éri el (line 395):
```python
getattr(sandbox_result, 'stderr', '') or ""
```

Miközben `SandboxResult` Pydantic modell létezik a `models.py`-ban és tartalmazza a `stderr` mezőt.

**Hatás:** Type checkereknél (mypy, pyright) nincs ellenőrzés, IDE autocomplete nem működik. A `getattr` elfedi ha a mező neve megváltozik.

**Javítás:**
```python
from models import SandboxResult

async def run(
    self,
    task: Task,
    validated_code: str,
    audit_result: AuditResult,
    sandbox_result: SandboxResult,
    ...
```

---

### DESIGN-02: Belső kód truncation — elveszett kontextus a tesztgenerálásban

**Fájl:** `core/pipeline.py:153, 242, 264`  
**Súlyosság:** 🟠 KÖZEPES

```python
# generate_simple, S2 prompt:
f"Kész kód:\n```python\n{s1_code[:3000]}\n```\n\n"   # ← 3000 char truncation

# generate_complex, S3a prompt:
f"```python\n{combined_raw[:4000]}\n```\n\n"           # ← 4000 char truncation

# generate_complex, S3b prompt:
f"```python\n{clean_code[:2500]}\n```\n\n"             # ← 2500 char truncation
```

Ha egy generált kód 200+ soros (enterprise Python szinten normális), a truncation elvágja a végét. A tesztgeneráló session nem látja a fő logikát, és triviális teszteket ír ahelyett, hogy a valódi függvényeket tesztelné. Ez silent failure — nem hibát dob, hanem gyenge teszteket generál.

**Javítás:**

Dinamikus token budget alapján truncate helyett inkább a kód elejét és végét add meg:
```python
# Az első N + utolsó M sor megőrzi az importokat és a main logikát
lines = s1_code.splitlines()
if len(lines) > 120:
    visible = lines[:80] + ["# ... (kihagyva) ..."] + lines[-20:]
    s1_code_preview = "\n".join(visible)
else:
    s1_code_preview = s1_code
```

---

### DESIGN-03: `DeveloperPipeline.run` — cache mentés a handlersben duplikál

**Fájl:** `bot/handlers.py:397`, `core/pipeline.py:567-575`  
**Súlyosság:** 🟠 KÖZEPES

A `DeveloperPipeline` saját cache logikával rendelkezik (pipeline.py:567): cache HIT esetén visszaad, de a cache WRITE-ot a `bot/handlers.py:397` végzi:
```python
# handlers.py:397
if result.fully_passed and not is_multiturn and pipeline == Pipeline.DEVELOPER:
    self._save_cached("developer", task_text, reply)  # ← formázott Telegram üzenet kerül cache-be
```

Probléma: a cache a formázott Telegram reply-t tárolja (markdown, emojik, sor preview), nem a kódot. Cache HIT esetén a pipeline.py:575-ben `output=cached` visszatér, ami a `PipelineFormatter.format_developer_result` cache_hit ágában jelenik meg. Ez belső konzisztenciát feltételez, de ha a formatter logikája változik, a cache tartalom "stale" lesz.

**Ajánlás:** A `validated_code`-t cacheld, ne a formázott választ. Így a formatter mindig az aktuális kód alapján generál üzenetet.

---

### DESIGN-04: `system_running()` deprecated asyncio API

**Fájl:** `main.py:339`  
**Súlyosság:** 🟠 KÖZEPES

```python
def system_running(self, update) -> bool:
    if not self.state.running:
        asyncio.get_event_loop().create_task(   # ← deprecated Python 3.10+
            update.message.reply_text(...)
        )
    return self.state.running
```

`asyncio.get_event_loop()` Python 3.10+ óta DeprecationWarning-ot ad ha nincs futó event loop a jelenlegi szálban. PTB kontextusban rendszerint van futó loop, de a helyes API:

```python
asyncio.get_running_loop().create_task(...)
# vagy:
asyncio.ensure_future(...)
```

---

## 🟡 KISEBB PROBLÉMÁK

---

### MINOR-01: Dead code — `axon_main()` függvény

**Fájl:** `main.py:630–632`  
**Súlyosság:** 🟡 KISEBB

```python
async def axon_main() -> None:
    """Legacy — nem használt, a main() + _run_bot() váltotta fel."""
    pass
```

Ez az üres függvény zavart okozhat: ha valaki keresi a belépési pontot, előbb ezt találja meg. El kell távolítani.

---

### MINOR-02: `_build_fix_block` lazy import

**Fájl:** `core/pipeline.py:70`  
**Súlyosság:** 🟡 KISEBB

```python
def _build_fix_block(samples: list[dict]) -> str:
    if not samples:
        return ""
    import json as _j    # ← függvény belsejébe importálva
```

A `json` standard library, nincs indok a lazy importra. A modul tetejére hozva gyorsabb és konvencionálisabb.

**Javítás:**
```python
import json   # ← felső importok közé
```

---

### MINOR-03: `generate_complex` status üzenet session számozás inkonzisztencia

**Fájl:** `core/pipeline.py:197, 219, 238, 261`  
**Súlyosság:** 🟡 KISEBB

```python
await status_cb("1️⃣ *Session 1/3* – ...")  # "1/3"
await status_cb("1️⃣ *Session 2/3* – ...")  # "2/3"
await status_cb("1️⃣ *Session 3a/3* – ...")  # "3a/3" ← de van 3b is!
await status_cb("1️⃣ *Session 3b/3* – ...")  # "3b/3"
```

A fejléc helyesen mondja "4 lépéses generálás", de az egyes sessionök "/3"-at mutatnak. Ez félrevezeti a felhasználót.

**Javítás:**
```python
await status_cb("1️⃣ *Session 1/4* – ...")
await status_cb("1️⃣ *Session 2/4* – ...")
await status_cb("1️⃣ *Session 3a/4* – ...")
await status_cb("1️⃣ *Session 3b/4* – ...")
```

---

### MINOR-04: Teszt fájlok hardcoded Linux path

**Fájl:** `tests/test_pipeline.py:6`, `tests/test_models.py:6`  
**Súlyosság:** 🟡 KISEBB

```python
sys.path.insert(0, "/home/claude/axon_v9")   # ← Linux path, Windows-on nem működik
```

Windows futtatókörnyezetben a pytest a `tests/` könyvtárból indul, ezért az `axon_v9` könyvtár nem található meg. A tesztek valószínűleg `ImportError`-ral buknak el Windows-on.

**Javítás:**
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

### MINOR-05: `_task_tokens` class variable, nem instance variable

**Fájl:** `main.py:245`  
**Súlyosság:** 🟡 KISEBB

```python
class AppContext:
    _task_tokens: dict = {}   # ← class szintű, megosztott minden instance között
```

Ha az `AppContext` valaha több példányban jön létre (teszteléskor, vagy jövőbeli multi-tenant esetén), az összes példány ugyanazt a dict-et használja — token szivárgás lehetséges.

**Javítás:**
```python
def __init__(self, config: Config) -> None:
    self._task_tokens: dict[str, dict] = {}   # ← instance szintű
```

---

## Pozitív megállapítások

Ezek az erősségek figyelemre méltók és meg kell tartani őket:

**1. Kiváló separation of concerns**  
A `CodeGenerator`, `AuditFixLoop`, `OutputWriter`, `CostAccumulator` osztályok pontosan egy dolgot csinálnak. A Telegram I/O kizárólag `bot/handlers.py`-ban van — ez az eredeti 550 soros monolithoz képest drámai javulás.

**2. Következetes dependency injection**  
A `DeveloperPipeline.__init__` hosszú paraméterlista ugyan, de minden függőség explicit. Nincs globális state, nincs `import axon_memory` a pipeline belsejéből — ez tesztelhetővé teszi az osztályt.

**3. StatusCallback protokoll**  
`StatusCallback = Callable[[str], Awaitable[None]]` — ez egy tiszta, Telegram-agnosztikus protokoll. A pipeline nem tud a Telegram Update objektumról, csak string üzeneteket küld. Ez a réteghatár helyes.

**4. Pydantic v2 modellek teljes lefedéssel**  
A `models.py` minden adatcsere-objektumot definiál (Task, SandboxResult, AuditResult, PipelineResult, stb.). Nincs raw dict átadás a modulok között — ez nagyon értékes, különösen a `model_validator` és `field_validator` használata.

**5. AuditFixLoop retry logikája**  
A `AUDIT_MAX_RETRIES = 2` korlát, a `save_fix_sample` hívás mind sikeres, mind sikertelen esetben, és a korai `break` ha sandbox FAIL — ez gondosan tervezett, nem naiv retry loop.

**6. `_extract_code_block` regex**  
Az `r"```(?:python)?\s*\n?(.*?)```"` és a `max(matches, key=len)` stratégia helyes gondolkodást tükröz: Claude néha több kód blokkot ad vissza, és a leghosszabb szinte mindig a végső megoldás.

**7. Risk keyword szűrő placement**  
A kockázatos kód ellenőrzés a generálás UTÁN és a sandbox ELŐTT van — ez a helyes sorrendek, mert a generált kódra reagál, nem a user promptra.

---

## Javítási prioritások (teendőlista)

| # | Feladat | Fájl | Sürgősség |
|---|---------|------|-----------|
| 1 | `_extract_code_block` visszatérési típus javítása + tesztek frissítése | `core/pipeline.py`, `tests/test_pipeline.py` | 🔴 Azonnal |
| 2 | Teszt fájlok Linux path fix | `tests/test_*.py` | 🔴 Azonnal |
| 3 | Timestamp mismatch fix `OutputWriter.write()` return értékben | `core/pipeline.py` | 🔴 Következő PR |
| 4 | `SANDBOX_MAX_RETRIES` kiváltása `sandbox_result.attempt`-tel | `core/pipeline.py` | 🟠 |
| 5 | `AuditFixLoop.run` sandbox_result típus annotáció | `core/pipeline.py` | 🟠 |
| 6 | `asyncio.get_event_loop()` → `get_running_loop()` | `main.py` | 🟠 |
| 7 | `_task_tokens` instance variable | `main.py` | 🟠 |
| 8 | `axon_main()` dead code eltávolítás | `main.py` | 🟡 |
| 9 | `import json` modul szintre hozva | `core/pipeline.py` | 🟡 |
| 10 | Session számozás "1/4"-re javítás | `core/pipeline.py` | 🟡 |

---

## Részletes javítási diff — BUG-01

Ez a legfontosabb javítás, teljes diff:

```diff
# core/pipeline.py

-def _extract_code_block(text: str) -> str:
-    """Python kód blokk kinyerése ```python ... ``` jelölőkből."""
-    if not text:
-        return ""
-    pattern = r"```(?:python)?\s*\n?(.*?)```"
-    matches = re.findall(pattern, text, re.DOTALL)
-    if matches:
-        return max(matches, key=len).strip()
-    return text.strip()
+def _extract_code_block(text: str | None) -> str | None:
+    """Python kód blokk kinyerése ```python ... ``` jelölőkből."""
+    if not text:
+        return None
+    pattern = r"```(?:python)?\s*\n?(.*?)```"
+    matches = re.findall(pattern, text, re.DOTALL)
+    if matches:
+        return max(matches, key=len).strip()
+    return None
```

```diff
# tests/test_pipeline.py

-    def test_no_block_returns_none(self):
-        assert _extract_code_block("nincs kód blokk") is None
+    def test_no_block_returns_none(self):
+        assert _extract_code_block("nincs kód blokk") is None   # ✓ most helyes

-    def test_empty_string_returns_none(self):
-        assert _extract_code_block("") is None
+    def test_empty_string_returns_none(self):
+        assert _extract_code_block("") is None    # ✓ most helyes

-    def test_none_returns_none(self):
-        assert _extract_code_block(None) is None
+    def test_none_returns_none(self):
+        assert _extract_code_block(None) is None  # ✓ most helyes
```

---

## Kiegészítő megfigyelések — `models.py`

A `models.py` teljes lefedettségű, de egy észrevétel:

**`AuditResult.telegram_summary`** (models.py:171):  
Telegram-specifikus formázó logika (`*bold*`, emoji-k) az adatmodellben van. Ez sérti a separation of concerns elvét — a formázás a `PipelineFormatter` dolga lenne. Nem kritikus, de következő major refactornál érdemes kiemelni.

---

## Konklúzió

A `core/pipeline.py` **production-ready architektúrával** rendelkezik. A fő kockázat nem a futásidejű viselkedésben, hanem a **teszt suite megbízhatóságában** rejlik: a BUG-01 teszt contract mismatch miatt a CI/CD látszólag zöld lehet, míg a valódi viselkedés eltér a specifikációtól. Ez az "invisible bug" kategória — nem okoz látható hibát a normál működésben, de félrevezeti a fejlesztőt a jövőbeli módosításoknál.

A 3 kritikus javítás elvégzése után a kódbázis Anthropic production standard követelményeit teljesíti.

---

*Report generated by Claude Code (claude-sonnet-4-6) | 2026-05-06*
