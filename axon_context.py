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
CONTEXT_VERSION = "7"   # ← ezt növeld ha frissíted a kontextust

# ═══════════════════════════════════════════════════════════════
#  AXON PROJEKT KONTEXTUS
# ═══════════════════════════════════════════════════════════════

AXON_PROJECT_CONTEXT = """
## AXON Neural Bridge – Projekt kontextus

**Tulajdonos:** Kocsis Gábor, Budapest (villamos elosztó tábla szerelő csoportvezető, Python automatizálás és AI fejlesztő szabadúszóként)

**Projekt célja:** Telegram-alapú AI automatizálási platform → szabadúszó bevétel generálás Upwork-ön (Python automatizálás, SRE feladatok)

**Jelenlegi dátum:** 2026. április 9.
**Jelenlegi verzió:** AXON v8.4 – ÉLES

**Aktív fájlok:**
- axon_telegram_v6.py – fő bot (v8.4)
- axon_sandbox_v2.py – kód validáció (MagicMock alapú)
- axon_auditor_v2.py – Gemini audit
- axon_memory.py – adatbázis, cache, training data, history perzisztencia
- axon_watchman.py – SRE háttérfigyelés
- axon_retry.py – exponenciális backoff retry
- axon_compaction.py – history tömörítés
- axon_context.py – projekt kontextus (ez a fájl)

**Output mappa:** `outputs/` (a script mappájában, automatikusan létrejön)
- Minden sikeres DEVELOPER futás ide menti a teljes kódot .py fájlba
- Fájlnév formátum: YYYYMMDD_HHMMSS_feladat_rövid.py

**Adatbázis:** axon.db (SQLite)
- task_cache – sikeres feladatok cache-e (SHA-256 hash + context verzió)
- training_data – minden futás tanítóadata
- fix_samples – bad_code → fixed_code párok (fine-tuning alap)
- daily_stats – napi összesítő
- config – OWNER_CHAT_ID és beállítások
- seen_jobs – Scout által látott Upwork job ID-k (deduplikáció)

**AI modellek:**
- Claude: claude-sonnet-4-6 ($3/M input, $15/M output)
- Gemini: gemini-2.5-flash (audit, ~$0.01/nap)

**API egyenleg (2026.03.20.): Claude ~$22.76 | Gemini ~$0.08/hó

**Multi-expert pipeline (v5.3):**
- DEVELOPER → kód generálás (sandbox + Gemini audit, cache)
- PLANNER   → tervek, dokumentáció (markdown, cache)
- CREATIVE  → szövegek, levelek (egyedi, NINCS cache)
- ANALYST   → adatelemzés, számítások (cache)

**Validációs pipeline (DEVELOPER – 3 szint):**
1. Statikus biztonsági szűrő (RISK_KEYWORDS)
2. Sandbox unit tesztek (Python subprocess)
3. Gemini logikai audit (55/100 PASS küszöb)

**Multi-session generálás:**
- SIMPLE feladat → 2 session (kód + tesztek)
- COMPLEX feladat → 4 session (S1: struktúra, S2: logika, S3a: összefűzés, S3b: tesztek)

**Sandbox mock lefedés (v3.1 – MagicMock alapú):**
- psycopg2/psycopg: MagicMock conn+cursor, fetchall, fetchmany, fetchone, closed,
  set_session, set_isolation_level, autocommit, extensions, sql alias, exception alias-ok
- gspread + Google OAuth2: worksheet, get_all_records, append_row, service_account
- boto3/botocore: S3 client, upload_file, download_file, list_objects_v2
- redis: get, set, delete, exists, hget, hset, from_url
- smtplib/imaplib: SMTP, SMTP_SSL, starttls, login, sendmail
- pymongo: MongoClient, find, find_one, insert_one, update_one
- requests: get, post, put, delete, patch, Response mock
- SQLAlchemy: create_engine, sessionmaker, Session, Column típusok (v3.1+)
- httpx/aiohttp: async HTTP kliens mock (v3.1+)
- Logging fix: logging.disable(CRITICAL) – generált kód nem szól bele az AXON logjába
- Windows fix: stdout/stderr PIPE dekódolás, py_compile fallback

**Upwork stratégia (frissített):**
- Célpiac: Python automatizálás, PostgreSQL/Sheets integráció, adatfeldolgozás, CSV/ETL
- Megközelítés: TÚLKÉPZÉS – AXON $200-300 szintű feladatokra képes → $80-100 munkák garantált
- Első munkák: fix áras, deliverable egy Python fájl vagy CSV amit ellenőrizni lehet
- Sorrend: Sports Card CSV ($100) és Python Rules Engine ($150) ajánlat kész
- Profil neve: Gábor Kocsis | Python Automation Engineer | AI Workflow & API Integration

**Ismert technikai adósság (etikus hacker barát – szeptember-október):**
- API kulcsok hardcodeolva → .env-re kellene átállítani
- axon.db titkosítatlan
- Rate limiting nincs

**Tervezett fejlesztések (prioritás sorrendben):**
1. Spending cap beállítása (Claude Console + Google AI Studio)
2. Upwork Scout cookie mentés első indításkor (--save-cookies)
3. Fine-tuning local modellekkel a fix_samples alapján
4. Dell OptiPlex 7071 upgrade (i9-9900, 32GB RAM) – ha bevétel jön

**TITAN projekt:** Létezik, de SZIGORÚAN elkülönítve – soha nem keveredhet az AXON kóddal.

**Fejlesztési nyelv:** Magyar (kommentek, logok, Telegram üzenetek)
**Platform:** Windows (Asus X550JX laptop)
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
            "Specialitás: Python automatizálás, AI integráció, Telegram botok, adatfeldolgozás.\n"
            "Stílus: professzionális de személyes, konkrét, nem általánoskodó.\n"
            "Minden szöveg egyedi – soha nem sablon."
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
        return base
