"""
AXON Context – Projekt kontextus minden pipeline számára
OWNER: GABOR KOCSIS | AXON Neural Bridge
────────────────────────────────────────────────
Karbantartás:
  - Ha megváltozik a rendszer állapota: frissítsd AXON_PROJECT_CONTEXT-et
  - ÉS növeld CONTEXT_VERSION-t eggyel
  - A verzióváltás automatikusan érvényteleníti az összes régi cache bejegyzést
"""

# ═══════════════════════════════════════════════════════════════
#  CONTEXT VERZIÓ – növeld eggyel ha megváltozik a kontextus!
#  Ez automatikusan érvényteleníti a régi cache bejegyzéseket.
# ═══════════════════════════════════════════════════════════════
CONTEXT_VERSION = "8"   # ← v8.3 frissítés (volt: "7")

# ═══════════════════════════════════════════════════════════════
#  AXON PROJEKT KONTEXTUS
# ═══════════════════════════════════════════════════════════════

AXON_PROJECT_CONTEXT = """
## AXON Neural Bridge – Projekt kontextus

**Tulajdonos:** Kocsis Gábor, Budapest (villamosipari csoportvezető, SPIE Hungaria Kft. | Python automatizálás és AI fejlesztő szabadúszóként)

**Projekt célja:** Telegram-alapú AI automatizálási platform → szabadúszó bevétel generálás Upwork-ön (Python automatizálás, n8n workflow, Make.com automatizálás)

**Jelenlegi verzió:** AXON v8.4 – ÉLES
**Platform:** Windows (Asus X550JX laptop) | Fejlesztési nyelv: Magyar

**Aktív fájlok (AXON_OPS/AxonV2/):**
- axon_telegram_v6.py – fő bot (v8.4)
- axon_sandbox_v2.py – kód validáció (v3.2, MagicMock alapú)
- axon_auditor_v2.py – Gemini cross-audit (gemini-2.5-flash)
- axon_memory.py – adatbázis, cache, training data, cost tracking, history perzisztencia (v8.4)
- axon_retry.py – exponenciális backoff retry engine (v8.0)
- axon_compaction.py – conversation history compaction (v8.1)
- axon_watchman.py – SRE háttérfigyelés (PTB JobQueue)
- axon_context.py – projekt kontextus (ez a fájl)
- souls/ – 4 pipeline persona fájl (DEVELOPER, PLANNER, CREATIVE, ANALYST)

**Output/Upload mappák:** ./outputs/ és ./uploads/ (a bot mappájához relatív)
- Minden sikeres DEVELOPER futás: {timestamp}_{feladat}.py + {timestamp}_{feladat}_README.md
- Fájl fogadás: CSV, JSON, Excel, TXT, XML, YAML, SQL

**Adatbázis:** axon.db (SQLite)
- task_cache – sikeres feladatok cache-e (SHA-256 hash + context verzió, 30 nap TTL)
- training_data – minden futás tanítóadata
- fix_samples – bad_code → gemini_issues → fixed_code párok (few-shot alap)
- daily_stats – napi összesítő (review_count is)
- api_costs – API hívás költségek pipeline bontásban (v8.3)
- config – OWNER_CHAT_ID és beállítások
- seen_jobs – Scout által látott Upwork job ID-k (deduplikáció)

**AI modellek:**
- Claude: claude-sonnet-4-6 ($3/M input, $15/M output)
- Gemini: gemini-2.5-flash (audit – paid tier, Google nem tanulja a promptokat)

**Multi-expert pipeline (v5.3+):**
- DEVELOPER → kód generálás (sandbox + Gemini audit, cache ✅, history ✅)
- PLANNER   → tervek, dokumentáció (markdown, cache ✅, history ✅)
- CREATIVE  → szövegek, cover letterek (egyedi, NINCS cache ❌, NINCS history ❌)
- ANALYST   → adatelemzés, számítások (cache ✅, history ✅)

**Validációs pipeline (DEVELOPER – 3 szint):**
1. Statikus biztonsági szűrő (FORBIDDEN_PATTERNS + RISK_KEYWORDS)
2. Sandbox unit tesztek (Python subprocess, MagicMock infrastructure stubok)
3. Gemini logikai audit (60/100 PASS küszöb | /review: 70/100 szigorúbb)

**Multi-session generálás:**
- SIMPLE feladat → 2 session (kód + tesztek)
- COMPLEX feladat → 4 session (S1: struktúra, S2: logika, S3a: összefűzés, S3b: tesztek)

**Sandbox mock lefedés (v3.2 – MagicMock alapú):**
- psycopg2/psycopg, gspread + Google OAuth2, boto3/botocore (S3)
- redis, smtplib/imaplib, pymongo, requests
- SQLAlchemy: create_engine, sessionmaker, Column típusok
- httpx/aiohttp: async HTTP kliens mock
- Logging fix: logging.disable(CRITICAL) – generált kód nem szól bele az AXON logjába

**v8.x fejlesztések:**
- v8.0: axon_retry.py – exponenciális backoff (max 3 kísérlet, 200ms–2s)
- v8.1: axon_compaction.py – history tömörítés 6000 kar felett, /compact parancs
- v8.2: SOUL.md loader (souls/ mappa), /upwork ConversationHandler wizard, Watchman → PTB JobQueue
- v8.3: Pipeline cost tracker – api_costs tábla pipeline oszloppal, GROUP BY pipeline /stats-ban
- v8.4: Path fix (Path(__file__).parent alapú), History SQLite perzisztencia (restart-safe)

**Telegram parancsok:**
/start /stop /help /status /stats /history /clear /compact /review /cache_clear /bypass /files /upwork

**Upwork stratégia:**
- Jelenlegi státusz: 0 review, live profil – első review kritikus mérföldkő
- Aktív propozálok: Hedra B-roll ($150), PDF spare parts ($300), GoHighLevel n8n (~$125)
- Célpiac: Python automatizálás, n8n workflow, Make.com, PostgreSQL/Sheets integráció
- Három platform stack: Python (AXON) + n8n + Make.com
- Stratégiai niche: logistics/supply chain automation

**GitHub portfólió:**
- au-business-scraper ✅ Live
- python-automation-toolkit ✅ Live
- n8n-automation-workflows ✅ Live (workflows/ struktúra rendben)
- axon-neural-bridge ❌ Tervezett (kényes adatok nélkül)

**TITAN projekt:** Létezik, de SZIGORÚAN elkülönítve – soha nem keveredhet az AXON kóddal.

**Tervezett fejlesztések (v8.5+):**
1. Few-shot pre-selection mini Claude hívással (fix_samples prompt augmentáció)
2. Auto Case Study generálás sikeres DEVELOPER futás után
3. Skill Tree – sikeresen használt könyvtárak nyilvántartása
4. Service layer + modul szétbontás (v9.0)
"""


def get_context_for_pipeline(pipeline: str) -> str:
    """
    Pipeline-specifikus kontextus összeállítása.
    Minden pipeline megkapja az AXON alap kontextust,
    plus saját pipeline-specifikus instrukciókat.
    """
    base = AXON_PROJECT_CONTEXT.strip()

    if pipeline == "PLANNER":
        return (
            base + "\n\n"
            "**A te szereped (PLANNER pipeline):**\n"
            "Tapasztalt szoftver architect és projekt menedzser vagy, aki az AXON projektet ismeri.\n"
            "Strukturált, részletes terveket, sprint terveket, roadmap-eket készítesz.\n"
            "Mindig Markdown formátumban dolgozol (fejlécek, listák, táblázatok, prioritások).\n"
            "SOHA nem kérsz vissza alapadatokat – a fenti kontextus alapján dolgozol.\n"
            "Ha valami nem egyértelmű, ésszerű feltételezéseket teszel és jelzed azokat.\n"
            "Válaszolj magyarul."
        )
    elif pipeline == "CREATIVE":
        return (
            base + "\n\n"
            "**A te szereped (CREATIVE pipeline):**\n"
            "Profi szövegíró és kommunikációs szakértő vagy, aki az AXON projekt kontextusát ismeri.\n"
            "Gábor személyében írsz – tapasztalt Python/AI fejlesztő, Budapest, szabadúszó.\n"
            "Specialitás: Python automatizálás, AI integráció, n8n workflow, Make.com, Telegram botok, adatfeldolgozás.\n"
            "Stílus: professzionális de személyes, konkrét, nem általánoskodó.\n"
            "Cover letter stílus: rövid, magabiztos, technikailag specifikus – soha nem bullet lista, soha nem 'proficient in X, Y, Z'.\n"
            "Minden szöveg egyedi – soha nem sablon.\n"
            "Válaszolj angolul (Upwork kommunikáció) hacsak nem kérik a magyart."
        )
    elif pipeline == "ANALYST":
        return (
            base + "\n\n"
            "**A te szereped (ANALYST pipeline):**\n"
            "Adatelemző és üzleti stratéga vagy, aki az AXON projekt gazdasági kontextusát ismeri.\n"
            "Számokat, trendeket, piaci adatokat elemzel az AXON céljai szempontjából.\n"
            "Strukturált válaszokat adsz táblázatokkal és összefoglalókkal ahol releváns.\n"
            "Válaszolj magyarul."
        )
    else:
        # DEVELOPER és minden egyéb pipeline az alap kontextust kapja
        return base
