# AXON Neural Bridge — Changelog

## v6.0 — 2026-03-26

### Új funkciók
- **Conversation memory** (in-memory dict, per chat_id session)
- **Session timeout:** 2 óra inaktivitás → auto clear + Telegram értesítő
- `/clear` parancs — manuális history törlés
- `/history` parancs — aktív kontextus megjelenítése (csak user turn-ök, röviden)

### Architektúrális döntések
- **DEVELOPER history:** `validated_code` kerül history-ba, nem a Telegram-formázott válasz — így multi-turn módosításkor Claude a valódi kódot látja
- **Cache + history integráció:** multi-turn session → cache bypass (kontextus-függő kód nem cache-elhető); cache hit → `[CACHE HIT]` flag az assistant turnben
- **Karakter-alapú history trim** (8000 kar limit) user+assistant párban töröl — nem fix üzenetszám, hanem token-tudatos megközelítés
- **CREATIVE pipeline history-mentes** — minden cover letter/szöveg friss slate marad
- **`get_last_code()` hook** előkészítve a v6.1 `/review` parancshoz
- History context prefix DEVELOPER promptban: ha előző kód van, beilleszti `"KONTEXTUS – az előző feladatban generált kód"` formában

### axon_memory.py v3.0 — új API
- `add_to_history()`, `get_history()`, `get_history_turn_count()`
- `get_last_code()` — utolsó DEVELOPER assistant turn kinyerése
- `clear_history()`, `was_timeout_cleared()` (egyszeri olvasás + auto-reset)
- `get_history_summary()` — `/history` parancshoz

---

## v5.6 — 2026-03-25

### Változások
- Scout import eltávolítva az `axon_telegram_v5.py`-ból
- Tiszta indítás — Cloudflare blokk miatt a Scout parkolt állapotba került

### Kontextus
- Cloudflare blokkolja a Playwright bejelentkezést → Scout inaktív
- Aktív megoldás: Upwork mobilapp push értesítő

---

## v5.5 — 2026-03-24

### Új funkciók
- **Enterprise DEVELOPER prompt** — 8 kötelező elv (error handling, logging, type hints, docstring, edge case-ek, DRY, konfigurálhatóság, teljes kód)
- **S3b retry logika** — ha a teszt session NONE-t ad vissza, újrapróbálkozik egyszer

### Architektúrális döntések
- A 8 elvből álló prompt azért kell, mert Upwork-ön a kód minőség közvetlenül látható az ügyfélnek — az alapértelmezett Claude output nem elég production-ready

---

## v5.4 — 2026-03-23

### Új funkciók
- **COMPLEX generálás fix:** Session 3 → 3a (összefűzés + tisztítás) + 3b (unit tesztek) szétválasztva
- Debug log sorok: S3a/S3b válasz hossz + combined kód preview
- `axon_context.py` CONTEXT_VERSION → 4

### Architektúrális döntések
- A 3a/3b szétválasztás azért szükséges, mert egy session-ben az összefűzés + teszt generálás együtt túl hosszú kimenethez vezet, Claude csonkítja — külön sessionben mindkettő teljes marad

---

## v5.3 — 2026-03-22

### Új funkciók
- **Multi-expert routing:** DEVELOPER / PLANNER / CREATIVE / ANALYST pipeline
- **PLANNER pipeline:** strukturált markdown kimenet, sandbox nélkül, cache ✅
- **CREATIVE pipeline:** Claude csak, NINCS cache (minden válasz egyedi) ❌
- **ANALYST pipeline:** Claude csak, cache ✅
- **`detect_pipeline()`:** keyword-alapú gyors detektálás, Claude fallback (max 10 token)
- `/cache_clear` parancs

### Architektúrális döntések
- CREATIVE soha nem kerül cache-be — cover letter, email, proposal egyedi tartalom, cached válasz profiltalan lenne
- Routing: keyword-match először (0 API hívás), Claude fallback csak ha egyik sem illeszkedik

---

## v5.2 — 2026-03-21

### Új funkciók
- **OWNER_CHAT_ID perzisztencia** — `axon.db` config táblában tárolva, újraindítás után is megmarad
- **`/upwork` parancs** — Upwork cover letter generálás (CREATIVE pipeline, nem cache-elhető)
- **Multi-session kód generálás:** SIMPLE → 2 session (kód + tesztek), COMPLEX → 3 session
- **Gemini audit küszöb:** 55/100 PASS (korábban magasabb volt, túl sok false positive)
- `safe_send` helper — Telegram Markdown parse error kezelés (4000 kar chunking)

### Architektúrális döntések
- Multi-session azért kell, mert egyetlen Claude hívásban a hosszú kód csonkul — 2 sessionnel a kód és a tesztek külön, teljes kimenettel generálódnak
- Gemini 55/100 küszöb: empirikusan meghatározva, alatta valódi hibák, felette stíluspreferenciák

---

## v5.1 — 2026-03-20

### Új funkciók
- **Task cache** (`axon.db` alapú) — ismételt feladatnál 0 API hívás
- SHA-256 hash: `expert_mode + "|" + prompt.strip().lower()`
- Cache TTL: 30 nap
- Cache statisztika `/stats`-ban (hit arány, megtakarított hívások)
- `axon_task_cache.py` → beolvasztva `axon_memory.py v2.0`-ba

### Architektúrális döntések
- Cache csak SIKERES futás után mentődik (sandbox PASS + Gemini PASS)
- Kizártak: `cover letter`, `upwork`, `fordítás` — egyedi tartalom
- CONTEXT_VERSION hash-be épített → kontextus változáskor automatikus cache invalidáció

---

## v5.0 — 2026-03-19

### Új funkciók
- **`axon_memory.py`** — training data gyűjtés (`training_data` + `daily_stats` tábla)
- **`axon_watchman.py`** — SRE háttérfigyelés (CPU, RAM, disk, hálózat)
- **`/stats` parancs** — tanulási statisztikák (sikerességi arány, retry count, sandbox/audit hibák)
- **`fix_samples` tábla** — `bad_code → gemini_issues → fixed_code` párok (fine-tuning alap)

### Architektúrális döntések
- `fix_samples` a jövőbeli fine-tuning "arany bányája" — a hibás kódok ugyanolyan értékesek mint a sikeresek
- Watchman külön asyncio task, nem blokkolja a bot működését

---

## v4.0 — 2026-03-18

### Új funkciók
- **Gemini Cross-Check (3. validációs szint)** — logikai audit, projekt szabályok, minőség
- `axon_auditor_v2.py` — Google Gemini API integráció (`gemini-2.5-flash`)
- Audit FAIL esetén Claude javítási kör (max 2 retry)
- `format_audit_for_fix_prompt()` — strukturált javítási prompt Gemini issues alapján

### Architektúrális döntések
- Gemini **paid tier** kötelező — free tier engedélyezi Google-nek a prompt adatok felhasználását tanításhoz; ügyfél kódja nem kerülhet oda
- Gemini audit a sandboxon PASS kód minőségét ellenőrzi — szétválasztott felelősségek

---

## v3.0 — 2026-03-18

### Új funkciók
- **Unit tesztek (2. validációs szint)** — generált kód logikai ellenőrzése
- `axon_sandbox_v2.py` — unit teszt runner, MagicMock alapú dependency mock
- **Kill switch** — `/stop` parancs, `/start` újraindítás
- Mock lefedés: psycopg2, gspread, boto3, redis, smtplib, pymongo, requests

### Architektúrális döntések
- Unit tesztek max 3 assert, semmi infrastructure assert (`conn is not None` tiltott) — ezek mindig passolnak és nem mérnek semmit
- MagicMock stratégia: a generált kód nem tud valódi DB/API kapcsolatot nyitni sandboxban — mock nélkül minden infrastructure hívás ImportError vagy ConnectionError lenne

---

## v2.0 — 2026-03-17

### Új funkciók
- **Sandbox (1. validációs szint)** — kód futtatás Python subprocess-ben
- Statikus biztonsági szűrő (RISK_KEYWORDS: `os.system`, `subprocess`, `__import__`, stb.)
- Kockázatos kód esetén inline approval gomb (Telegram InlineKeyboardButton)
- `/bypass` parancs — validáció nélküli futtatás saját felelősségre

### Architektúrális döntések
- Subprocess izolálás: a generált kód nem futhat az AXON process-ében — külön Python process, korlátozott env
- RISK_KEYWORDS szándékosan szűk scope — korábban `remove`, `drop`, `format` is benne volt, sok false positive-ot okozott

---

## v1.0 — 2026-03-17

### Alapok
- Telegram bot (`python-telegram-bot`)
- Anthropic Claude API integráció (`claude-sonnet-4-6`)
- OWNER_CHAT_ID regisztráció első üzenetnél
- Szöveges feladat → Claude válasz → Telegram

### Kontextus
- Kiindulópont: egyszerű AI proxy bot
- Cél: Upwork-ön értékesíthető Python automatizálási feladatok megoldása

---

*AXON Neural Bridge | Tulajdonos: Kocsis Gábor, Budapest*
*Fejlesztés kezdete: 2026-03-17 | Jelenlegi verzió: v6.0*
