"""
AXON Memory v3.0 – Tanulómodul, Statisztikák + Task Cache + Conversation History
OWNER: GABOR KOCSIS | AXON Neural Bridge
────────────────────────────────────────────────
v1.0 → Training data + daily stats
v2.0 → Task cache (ne hívjon Claude-ot ha már megoldotta!)
        → Spórol: API hívás = $0 ha cache hit
v2.1 → seen_jobs tábla (axon_scout.py deduplikációhoz)
v3.0 → Conversation history (in-memory dict, karakter-alapú trim)
        → session timeout (2 óra inaktivitás → auto clear)
        → get_last_code() helper a v6.1 /review parancshoz
        → history turn struktúra: {role, content, pipeline, ts, task}
          (task mező: assistant turn-nél az eredeti feladat szövege)

Cache logika:
  hash = sha256(expert_mode + "|" + prompt.strip().lower())
  Csak SIKERES feladatok kerülnek cache-be.
  Kizárt: upwork, cover letter, fordítás (egyedi tartalom!)
  TTL: 30 nap (utána újrahívja Claude-ot)

Conversation history logika:
  - In-memory dict: chat_id → list[{role, content, pipeline, ts, task}]
  - Karakter limit: MAX_HISTORY_CHARS (8000) – régebbi párok törlődnek
  - Session timeout: SESSION_TIMEOUT_SEC (7200 = 2 óra)
  - DEVELOPER pipeline: assistant turn = validated_code (nem Telegram formázás!)
  - CREATIVE pipeline: history kikapcsolva (minden válasz egyedi)
  - Cache + history: ha history > 1 turn → cache bypass
  - Cache hit esetén: [CACHE HIT] flag kerül az assistant turnbe
  - task mező: /review parancshoz kell (mi volt a feladat amikor a kód készült)
"""

import sqlite3
import hashlib
import logging
import re
from datetime import datetime, timedelta
from time import time

log = logging.getLogger("AXON.Memory")

DB_PATH = "axon.db"

# ═══════════════════════════════════════════════════════════════
#  CACHE KIZÁRÁSI LISTA – ezeket MINDIG újrageneráljuk
# ═══════════════════════════════════════════════════════════════
NEVER_CACHE_KEYWORDS = [
    "cover letter", "upwork", "pályázat", "ajánlólevél",
    "fordítsd", "translate", "fordítás",
]

CACHE_TTL_DAYS = 30

# ═══════════════════════════════════════════════════════════════
#  CONVERSATION HISTORY KONFIGURÁCIÓ
# ═══════════════════════════════════════════════════════════════
MAX_HISTORY_CHARS   = 8000   # ennyi karakternél trim-eli a régebbi párokat
SESSION_TIMEOUT_SEC = 7200   # 2 óra inaktivitás → auto session clear
MAX_HISTORY_TURNS   = 20     # abszolút felső határ (10 kérdés-válasz pár)

# Pipeline-onként: history aktív-e?
HISTORY_ENABLED_PIPELINES = {"DEVELOPER", "PLANNER", "ANALYST"}
# CREATIVE szándékosan kimarad – minden válasz friss slate


# ═══════════════════════════════════════════════════════════════
#  IN-MEMORY CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════
#
#  Struktúra:
#  _history[chat_id] = {
#      "turns": [
#          {
#              "role":     "user" | "assistant",
#              "content":  str,
#              "pipeline": str,
#              "ts":       float,       # unix timestamp
#              "task":     str | None   # eredeti feladat szövege (assistant turn-nél!)
#          },
#          ...
#      ],
#      "last_active":    float,  # unix timestamp
#      "timeout_flag":   bool    # True ha timeout miatt törlődött (egyszeri olvasás)
#  }
#
_history: dict[str, dict] = {}


def _get_session(chat_id: str) -> dict:
    """Visszaadja vagy létrehozza a session dict-et. Timeout ellenőrzéssel."""
    now = time()

    if chat_id not in _history:
        _history[chat_id] = {
            "turns": [],
            "last_active": now,
            "timeout_flag": False
        }
        return _history[chat_id]

    session = _history[chat_id]
    elapsed = now - session["last_active"]

    if elapsed > SESSION_TIMEOUT_SEC and len(session["turns"]) > 0:
        log.info(f"[HISTORY] Session timeout ({elapsed/3600:.1f}h) → auto clear | chat: {chat_id}")
        _history[chat_id] = {
            "turns": [],
            "last_active": now,
            "timeout_flag": True
        }
        return _history[chat_id]

    session["last_active"] = now
    return session


def _trim_history(turns: list) -> list:
    """
    Karakter-alapú trim: ha a teljes history meghaladja MAX_HISTORY_CHARS-t,
    törli a legrégebbi user+assistant párokat amíg alatta nem marad.
    Párban töröl hogy a kontextus koherens maradjon.
    """
    total_chars = sum(len(t["content"]) for t in turns)

    while total_chars > MAX_HISTORY_CHARS and len(turns) >= 2:
        # Első pár eltávolítása (user + assistant)
        removed_user      = turns.pop(0)
        removed_assistant = turns.pop(0) if turns else None

        total_chars -= len(removed_user["content"])
        if removed_assistant:
            total_chars -= len(removed_assistant["content"])

        log.debug(f"[HISTORY] Trim: régebbi pár eltávolítva, maradék chars: {total_chars}")

    # Abszolút határ
    if len(turns) > MAX_HISTORY_TURNS:
        turns = turns[-MAX_HISTORY_TURNS:]

    return turns


# ═══════════════════════════════════════════════════════════════
#  HISTORY PUBLIKUS API
# ═══════════════════════════════════════════════════════════════

def add_to_history(
    chat_id:  str,
    role:     str,
    content:  str,
    pipeline: str,
    task:     str | None = None
) -> None:
    """
    Hozzáad egy turn-t a conversation history-hoz.

    Args:
        chat_id:  Telegram chat azonosító
        role:     "user" vagy "assistant"
        content:  Az üzenet tartalma
                  DEVELOPER assistant turn esetén: validated_code (nem Telegram formázás!)
        pipeline: "DEVELOPER" | "PLANNER" | "ANALYST" | "CREATIVE"
        task:     Eredeti feladat szövege – assistant turn-nél kötelező kitölteni!
                  Ez kell a v6.1 /review parancshoz (Gemini audithoz kontextus).
                  user turn esetén None marad.

    Megjegyzés:
        - CREATIVE pipeline-t nem menti (minden válasz friss slate)
        - Karakter-alapú trim automatikusan fut
    """
    if pipeline not in HISTORY_ENABLED_PIPELINES:
        return

    session = _get_session(chat_id)

    turn = {
        "role":     role,
        "content":  content,
        "pipeline": pipeline,
        "ts":       time(),
        "task":     task  # None user turn-nél, feladat szövege assistant turn-nél
    }

    session["turns"].append(turn)
    session["turns"] = _trim_history(session["turns"])

    log.debug(f"[HISTORY] +1 turn ({role}/{pipeline}) | összesen: {len(session['turns'])} | chat: {chat_id}")


def get_history(chat_id: str) -> list[dict]:
    """
    Visszaadja az aktív history turn-ök listáját Claude API formátumban.

    Returns:
        [{"role": "user"|"assistant", "content": str}, ...]
        Csak a role és content mezők – Claude API kompatibilis.
    """
    if chat_id not in _history:
        return []

    session = _history[chat_id]
    return [
        {"role": t["role"], "content": t["content"]}
        for t in session["turns"]
    ]


def get_history_turn_count(chat_id: str) -> int:
    """Hány turn van az aktív history-ban (0 ha nincs session)."""
    if chat_id not in _history:
        return 0
    return len(_history[chat_id]["turns"])


def get_last_code(chat_id: str) -> tuple[str | None, str | None]:
    """
    Visszaadja az utolsó DEVELOPER assistant turn kódját és az eredeti feladatot.
    A v6.1 /review parancs erre támaszkodik.

    Returns:
        (code, task) tuple
        - code: az utolsó validált kód szövege, vagy None ha nincs
        - task: az eredeti feladat szövege, vagy None ha nincs
    """
    if chat_id not in _history:
        return None, None

    turns = _history[chat_id]["turns"]

    for turn in reversed(turns):
        if turn["role"] == "assistant" and turn["pipeline"] == "DEVELOPER":
            # [CACHE HIT] válaszokat kihagyjuk – azok nem valódi kódok
            content = turn["content"]
            if content.startswith("[CACHE HIT]"):
                continue
            task = turn.get("task")
            return content, task

    return None, None


def clear_history(chat_id: str) -> int:
    """
    Törli a chat history-t.

    Returns:
        Törölt turn-ök száma (0 ha nem volt aktív session)
    """
    if chat_id not in _history:
        return 0

    count = len(_history[chat_id]["turns"])
    _history[chat_id] = {
        "turns": [],
        "last_active": time(),
        "timeout_flag": False
    }
    log.info(f"[HISTORY] History törölve – {count} turn | chat: {chat_id}")
    return count


def was_timeout_cleared(chat_id: str) -> bool:
    """
    Egyszeri olvasás: True ha timeout miatt törlődött a history azóta
    hogy utoljára ellenőriztük. Auto-reset olvasás után.

    Telegram értesítőhöz használatos: handle_task() elején hívjuk.
    """
    if chat_id not in _history:
        return False

    flag = _history[chat_id].get("timeout_flag", False)
    if flag:
        _history[chat_id]["timeout_flag"] = False  # auto-reset
    return flag


def get_history_summary(chat_id: str) -> str:
    """
    /history parancshoz: az aktív session user turn-jeinek rövid listája.
    Csak a felhasználói üzeneteket mutatja (assistant kódot nem).
    """
    if chat_id not in _history or not _history[chat_id]["turns"]:
        return "📭 *Nincs aktív conversation history.*\nFriss session fut."

    turns = _history[chat_id]["turns"]
    user_turns = [t for t in turns if t["role"] == "user"]

    if not user_turns:
        return "📭 *Nincs aktív conversation history.*\nFriss session fut."

    session = _history[chat_id]
    total_chars = sum(len(t["content"]) for t in turns)
    elapsed_min = int((time() - session["last_active"]) / 60)

    lines = [
        f"🧠 *Aktív conversation history* ({len(user_turns)} kérdés)\n"
    ]

    for i, t in enumerate(user_turns, 1):
        preview = t["content"][:80].replace("\n", " ").strip()
        if len(t["content"]) > 80:
            preview += "…"
        pipeline_icon = {"DEVELOPER": "🔧", "PLANNER": "📋", "ANALYST": "📊"}.get(t["pipeline"], "💬")
        lines.append(f"{i}. {pipeline_icon} `{preview}`")

    lines.append(
        f"\n📏 *Méret:* {total_chars} / {MAX_HISTORY_CHARS} kar\n"
        f"⏱ *Utolsó aktivitás:* {elapsed_min} perce\n"
        f"_(Session timeout: 2 óra inaktivitás után)_"
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  ADATBÁZIS INICIALIZÁLÁS
# ═══════════════════════════════════════════════════════════════
def init_db():
    """
    Létrehozza az összes szükséges táblát ha még nem léteznek.
    Biztonságosan futtatható többször is.
    """
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()

    # Régi tábla (megtartjuk kompatibilitás miatt)
    cursor.execute("CREATE TABLE IF NOT EXISTS done (hash TEXT PRIMARY KEY)")

    # Tanítóadat tábla – minden futásról nyers adat
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_data (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
            expert_mode     TEXT,
            prompt          TEXT,
            generated_code  TEXT,
            sandbox_result  TEXT,
            audit_result    TEXT,
            sandbox_ok      INTEGER,
            audit_ok        INTEGER,
            success         INTEGER,
            retry_count     INTEGER DEFAULT 0
        )
    """)

    # Gyors statisztika tábla – napok szerint összesítve
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date            TEXT PRIMARY KEY,
            total_tasks     INTEGER DEFAULT 0,
            dev_tasks       INTEGER DEFAULT 0,
            success_count   INTEGER DEFAULT 0,
            fail_count      INTEGER DEFAULT 0,
            sandbox_fails   INTEGER DEFAULT 0,
            audit_fails     INTEGER DEFAULT 0,
            total_retries   INTEGER DEFAULT 0,
            review_count    INTEGER DEFAULT 0
        )
    """)
    # Meglévő adatbázishoz review_count hozzáadása (biztonságos migration)
    try:
        cursor.execute("ALTER TABLE daily_stats ADD COLUMN review_count INTEGER DEFAULT 0")
    except Exception:
        pass  # már létezik – nem baj

    # Task cache tábla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_cache (
            hash        TEXT PRIMARY KEY,
            expert_mode TEXT,
            prompt      TEXT,
            response    TEXT,
            hit_count   INTEGER DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_hit    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Cache statisztika tábla (naponta összesített megtakarítás)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_stats (
            date        TEXT PRIMARY KEY,
            hits        INTEGER DEFAULT 0,
            misses      INTEGER DEFAULT 0,
            saved_calls INTEGER DEFAULT 0
        )
    """)

    # Fix tanítóadat tábla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fix_samples (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
            prompt          TEXT,
            bad_code        TEXT,
            gemini_issues   TEXT,
            gemini_score    INTEGER,
            fixed_code      TEXT,
            fix_round       INTEGER,
            fix_succeeded   INTEGER
        )
    """)

    # Scout seen_jobs tábla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_id      TEXT PRIMARY KEY,
            title       TEXT,
            url         TEXT,
            budget      TEXT,
            first_seen  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Config tábla (OWNER_CHAT_ID perzisztencia)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key     TEXT PRIMARY KEY,
            value   TEXT
        )
    """)

    # API cost tábla (v6.2)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_costs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            date        TEXT,
            task        TEXT,
            input_tok   INTEGER DEFAULT 0,
            output_tok  INTEGER DEFAULT 0,
            cost_usd    REAL DEFAULT 0.0,
            calls       INTEGER DEFAULT 1
        )
    """)

    db.commit()
    db.close()
    log.info("[MEMORY] Adatbázis inicializálva (v3.0: training + stats + cache + fix_samples + seen_jobs + config)")


# ═══════════════════════════════════════════════════════════════
#  SCOUT – SEEN JOBS FÜGGVÉNYEK (v2.1)
# ═══════════════════════════════════════════════════════════════
def is_new_job(job_id: str) -> bool:
    """True ha a job még nem volt látva."""
    try:
        db = sqlite3.connect(DB_PATH)
        row = db.execute(
            "SELECT job_id FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        db.close()
        return row is None
    except Exception as e:
        log.error(f"[SCOUT] is_new_job hiba: {e}")
        return True


def mark_job_seen(job_id: str, title: str, url: str, budget: str):
    """Elmenti a job ID-t hogy ne küldje el újra."""
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute(
            "INSERT OR IGNORE INTO seen_jobs (job_id, title, url, budget) VALUES (?, ?, ?, ?)",
            (job_id, title, url, budget)
        )
        db.commit()
        db.close()
    except Exception as e:
        log.error(f"[SCOUT] mark_job_seen hiba: {e}")


def get_seen_jobs_count() -> int:
    """Hány jobot látott eddig a scout."""
    try:
        db = sqlite3.connect(DB_PATH)
        count = db.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
        db.close()
        return count
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════
#  TASK CACHE – CORE FÜGGVÉNYEK
# ═══════════════════════════════════════════════════════════════

def _make_hash(expert_mode: str, prompt: str) -> str:
    """SHA256 hash az expert_mode + prompt kombinációból."""
    raw = f"{expert_mode}|{prompt.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_cacheable(expert_mode: str, prompt: str) -> bool:
    """
    Eldönti hogy cache-elhető-e a feladat.
    Kizárja az egyedi/dinamikus tartalmakat.
    """
    prompt_lower = prompt.lower()
    for kw in NEVER_CACHE_KEYWORDS:
        if kw in prompt_lower:
            log.debug(f"[CACHE] Kizárt kulcsszó: '{kw}' → nem cache-elhető")
            return False
    return True


def get_cached_response(expert_mode: str, prompt: str) -> str | None:
    """
    Visszaadja a cache-elt választ ha van és nem járt le.
    None-t ad vissza ha nincs találat → Claude hívás szükséges.
    """
    if not is_cacheable(expert_mode, prompt):
        return None

    h = _make_hash(expert_mode, prompt)

    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT response, created_at, hit_count
            FROM task_cache
            WHERE hash = ?
              AND created_at >= datetime('now', ? || ' days')
        """, (h, f"-{CACHE_TTL_DAYS}"))

        row = cursor.fetchone()

        if row:
            response, created_at, hit_count = row

            cursor.execute("""
                UPDATE task_cache
                SET hit_count = hit_count + 1,
                    last_hit  = CURRENT_TIMESTAMP
                WHERE hash = ?
            """, (h,))

            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                INSERT INTO cache_stats (date, hits, saved_calls)
                VALUES (?, 1, 1)
                ON CONFLICT(date) DO UPDATE SET
                    hits        = hits + 1,
                    saved_calls = saved_calls + 1
            """, (today,))

            db.commit()
            db.close()

            log.info(f"[CACHE] HIT – {expert_mode} | hit #{hit_count + 1} | létrehozva: {created_at[:10]}")
            return response

        else:
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                INSERT INTO cache_stats (date, misses)
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET
                    misses = misses + 1
            """, (today,))
            db.commit()
            db.close()

            log.debug(f"[CACHE] MISS – {expert_mode}")
            return None

    except Exception as e:
        log.error(f"[CACHE] Lekérdezési hiba: {e}")
        return None


def save_cached_response(expert_mode: str, prompt: str, response: str) -> bool:
    """
    Elmenti a választ a cache-be.
    CSAK sikeres futás után hívd! (sandbox + audit PASS)
    """
    if not is_cacheable(expert_mode, prompt):
        log.debug(f"[CACHE] Nem cache-elhető – kizárt kulcsszó")
        return False

    h = _make_hash(expert_mode, prompt)

    try:
        db = sqlite3.connect(DB_PATH)
        db.execute("""
            INSERT OR REPLACE INTO task_cache (hash, expert_mode, prompt, response)
            VALUES (?, ?, ?, ?)
        """, (h, expert_mode, prompt[:2000], response[:10000]))
        db.commit()
        db.close()

        log.info(f"[CACHE] Mentve – {expert_mode} | {len(response)} kar")
        return True

    except Exception as e:
        log.error(f"[CACHE] Mentési hiba: {e}")
        return False


def get_cache_stats(days: int = 7) -> dict:
    """Cache statisztikák az elmúlt N napból."""
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT
                SUM(hits)        as total_hits,
                SUM(misses)      as total_misses,
                SUM(saved_calls) as total_saved
            FROM cache_stats
            WHERE date >= date('now', ? || ' days')
        """, (f"-{days}",))

        row = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM task_cache")
        cached_tasks = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(hit_count), 0) FROM task_cache")
        all_time_hits = cursor.fetchone()[0]

        db.close()

        hits   = row[0] or 0
        misses = row[1] or 0
        saved  = row[2] or 0
        total  = hits + misses

        return {
            "days":          days,
            "hits":          hits,
            "misses":        misses,
            "saved_calls":   saved,
            "hit_ratio":     round(hits / max(total, 1) * 100, 1),
            "cached_tasks":  cached_tasks,
            "all_time_hits": all_time_hits
        }

    except Exception as e:
        log.error(f"[CACHE] Statisztika lekérdezési hiba: {e}")
        return {}


def purge_expired_cache() -> int:
    """Lejárt cache bejegyzések törlése. Opcionálisan hívható cleanup-hoz."""
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("""
            DELETE FROM task_cache
            WHERE created_at < datetime('now', ? || ' days')
        """, (f"-{CACHE_TTL_DAYS}",))
        deleted = cursor.rowcount
        db.commit()
        db.close()
        if deleted > 0:
            log.info(f"[CACHE] {deleted} lejárt bejegyzés törölve")
        return deleted
    except Exception as e:
        log.error(f"[CACHE] Purge hiba: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════
#  MENTŐ FÜGGVÉNY (v1.0 – változatlan)
# ═══════════════════════════════════════════════════════════════
def save_training_sample(
    expert_mode: str,
    prompt: str,
    generated_code: str = "",
    sandbox_result: str = "",
    audit_result: str = "",
    sandbox_ok: bool = True,
    audit_ok: bool = True,
    success: bool = True,
    retry_count: int = 0
):
    """
    Egy feladat teljes életciklusát menti el.

    SZABÁLY: Tilos az adatokat szépíteni!
    Ha a kód hibás volt, a nyers hibaüzenetet kell ide írni,
    nem egy szép összefoglalót. A rendszer a hibákból tanul.
    """
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            INSERT INTO training_data
            (expert_mode, prompt, generated_code, sandbox_result,
             audit_result, sandbox_ok, audit_ok, success, retry_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            expert_mode,
            prompt[:2000],
            generated_code[:5000],
            sandbox_result[:1000],
            audit_result[:1000],
            1 if sandbox_ok else 0,
            1 if audit_ok else 0,
            1 if success else 0,
            retry_count
        ))

        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT INTO daily_stats (date, total_tasks, dev_tasks,
                success_count, fail_count, sandbox_fails, audit_fails, total_retries)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_tasks   = total_tasks + 1,
                dev_tasks     = dev_tasks + excluded.dev_tasks,
                success_count = success_count + excluded.success_count,
                fail_count    = fail_count + excluded.fail_count,
                sandbox_fails = sandbox_fails + excluded.sandbox_fails,
                audit_fails   = audit_fails + excluded.audit_fails,
                total_retries = total_retries + excluded.total_retries
        """, (
            today,
            1 if expert_mode == "developer" else 0,
            1 if success else 0,
            0 if success else 1,
            0 if sandbox_ok else 1,
            0 if audit_ok else 1,
            retry_count
        ))

        db.commit()
        db.close()
        log.info(f"[MEMORY] Minta elmentve – {expert_mode} | siker: {success} | retry: {retry_count}")

    except Exception as e:
        log.error(f"[MEMORY] Mentési hiba: {e}")


# ═══════════════════════════════════════════════════════════════
#  FIX TANÍTÓADAT MENTŐ – v2.1
# ═══════════════════════════════════════════════════════════════
def save_fix_sample(
    prompt: str,
    bad_code: str,
    gemini_issues: list,
    gemini_score: int,
    fixed_code: str,
    fix_round: int,
    fix_succeeded: bool
):
    """
    Egy javítási kör teljes adatát menti el.

    Tanítópár struktúra:
      INPUT:  bad_code + gemini_issues  (mit csinált rosszul)
      OUTPUT: fixed_code                (hogyan kell helyesen)
    """
    try:
        import json
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            INSERT INTO fix_samples
            (prompt, bad_code, gemini_issues, gemini_score, fixed_code, fix_round, fix_succeeded)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            prompt[:2000],
            bad_code[:5000],
            json.dumps(gemini_issues, ensure_ascii=False)[:1000],
            gemini_score,
            fixed_code[:5000],
            fix_round,
            1 if fix_succeeded else 0
        ))

        db.commit()
        db.close()
        log.info(f"[MEMORY] Fix minta elmentve – kör: {fix_round} | siker: {fix_succeeded}")

    except Exception as e:
        log.error(f"[MEMORY] Fix mentési hiba: {e}")


# ═══════════════════════════════════════════════════════════════
#  STATISZTIKA LEKÉRDEZŐ (v1.0 – változatlan)
# ═══════════════════════════════════════════════════════════════
def get_stats(days: int = 7) -> dict:
    """Összesített statisztikák az elmúlt N napból."""
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT
                SUM(total_tasks)   as total,
                SUM(dev_tasks)     as dev,
                SUM(success_count) as success,
                SUM(fail_count)    as fail,
                SUM(sandbox_fails) as sandbox_f,
                SUM(audit_fails)   as audit_f,
                SUM(total_retries) as retries,
                COALESCE(SUM(review_count), 0) as reviews
            FROM daily_stats
            WHERE date >= date('now', ? || ' days')
        """, (f"-{days}",))

        row = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM training_data")
        total_samples = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM training_data WHERE success = 1")
        success_samples = cursor.fetchone()[0]

        db.close()

        if row and row[0]:
            total, dev, success, fail, sandbox_f, audit_f, retries, reviews = row
            return {
                "days": days,
                "total_tasks": total or 0,
                "dev_tasks": dev or 0,
                "success": success or 0,
                "fail": fail or 0,
                "sandbox_fails": sandbox_f or 0,
                "audit_fails": audit_f or 0,
                "retries": retries or 0,
                "reviews": reviews or 0,
                "success_rate": round((success or 0) / max(total or 1, 1) * 100, 1),
                "total_samples": total_samples,
                "success_samples": success_samples
            }
        else:
            return {
                "days": days, "total_tasks": 0, "dev_tasks": 0,
                "success": 0, "fail": 0, "sandbox_fails": 0,
                "audit_fails": 0, "retries": 0, "reviews": 0,
                "success_rate": 0,
                "total_samples": total_samples,
                "success_samples": success_samples
            }

    except Exception as e:
        log.error(f"[MEMORY] Statisztika lekérdezési hiba: {e}")
        return {}


def format_stats_message(stats: dict) -> str:
    """Telegram-barát statisztika üzenet."""
    if not stats:
        return "❌ Statisztika nem elérhető."

    sr = stats.get("success_rate", 0)
    sr_icon = "✅" if sr >= 80 else "⚠️" if sr >= 50 else "❌"

    return (
        f"📊 *AXON Statisztika – elmúlt {stats['days']} nap*\n\n"
        f"*Feladatok összesen:* {stats['total_tasks']}\n"
        f"*Kód feladatok:* {stats['dev_tasks']}\n"
        f"*Sikeres:* {stats['success']} | *Sikertelen:* {stats['fail']}\n"
        f"{sr_icon} *Sikerességi arány:* {sr}%\n\n"
        f"*Sandbox hibák:* {stats['sandbox_fails']}\n"
        f"*Audit hibák:* {stats['audit_fails']}\n"
        f"*Összes javítási kör:* {stats['retries']}\n"
        f"*Manuális /review:* {stats.get('reviews', 0)} alkalom\n\n"
        f"🧠 *Tanítóadatok összesen:* {stats['total_samples']}\n"
        f"   ebből sikeres: {stats['success_samples']}\n"
        f"   ebből hibás: {stats['total_samples'] - stats['success_samples']}\n"
        f"   _(hibás minták ugyanolyan értékesek!)_"
    )


def log_task_cost(task: str, input_tokens: int, output_tokens: int, cost_usd: float, calls: int) -> None:
    """
    Egy feladat teljes Claude API költségét menti el.
    A DEVELOPER pipeline végén hívandó (_pop_task_tokens után).
    """
    try:
        db = sqlite3.connect(DB_PATH)
        today = datetime.now().strftime("%Y-%m-%d")
        db.execute("""
            INSERT INTO api_costs (date, task, input_tok, output_tok, cost_usd, calls)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today, task[:200], input_tokens, output_tokens, cost_usd, calls))
        db.commit()
        db.close()
        log.info(f"[COST] Feladat cost mentve: ${cost_usd:.4f} ({input_tokens}in/{output_tokens}out)")
    except Exception as e:
        log.error(f"[COST] Mentési hiba: {e}")


def get_cost_stats(days: int = 7) -> dict:
    """API cost statisztikák az elmúlt N napból."""
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT
                COUNT(*)        as task_count,
                SUM(input_tok)  as total_in,
                SUM(output_tok) as total_out,
                SUM(cost_usd)   as total_cost,
                AVG(cost_usd)   as avg_cost,
                MAX(cost_usd)   as max_cost
            FROM api_costs
            WHERE date >= date('now', ? || ' days')
        """, (f"-{days}",))
        row = cursor.fetchone()

        # Legdrágább feladat
        cursor.execute("""
            SELECT task, cost_usd, input_tok, output_tok
            FROM api_costs
            WHERE date >= date('now', ? || ' days')
            ORDER BY cost_usd DESC LIMIT 1
        """, (f"-{days}",))
        top = cursor.fetchone()

        # Mai nap cost
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT SUM(cost_usd) FROM api_costs WHERE date = ?", (today,))
        today_cost = cursor.fetchone()[0] or 0.0

        db.close()

        return {
            "days":       days,
            "task_count": row[0] or 0,
            "total_in":   row[1] or 0,
            "total_out":  row[2] or 0,
            "total_cost": row[3] or 0.0,
            "avg_cost":   row[4] or 0.0,
            "max_cost":   row[5] or 0.0,
            "today_cost": today_cost,
            "top_task":   top[0][:60] if top else None,
            "top_cost":   top[1] if top else 0.0,
        }
    except Exception as e:
        log.error(f"[COST] Statisztika hiba: {e}")
        return {}


def format_cost_stats_message(cs: dict) -> str:
    """Telegram-barát cost statisztika üzenet."""
    if not cs:
        return "❌ Cost statisztika nem elérhető."

    top_line = ""
    if cs.get("top_task"):
        top_line = f"\n🏆 *Legdrágább feladat:* ${cs['top_cost']:.4f}\n   _{cs['top_task']}_"

    return (
        f"💰 *API Cost – elmúlt {cs['days']} nap*\n\n"
        f"*Mai nap:* ${cs['today_cost']:.4f}\n"
        f"*{cs['days']} nap összesen:* ${cs['total_cost']:.4f}\n"
        f"*Feladatok száma:* {cs['task_count']}\n"
        f"*Átlagos feladatköltség:* ${cs['avg_cost']:.4f}\n\n"
        f"*Token összesen:* {cs['total_in']//1000}k in / {cs['total_out']//1000}k out"
        f"{top_line}"
    )


# ═══════════════════════════════════════════════════════════════
#  FEW-SHOT TANULÁS – v6.3
#  Szemantikus relevancia: feladat hasonlóság + hibatípus szűrés
#  Csak fix_succeeded=1 minták, minimum 1 előfordulás elég
# ═══════════════════════════════════════════════════════════════

def _similarity_score(text_a: str, text_b: str) -> float:
    """
    Egyszerű TF-IDF-szerű szóhalmaz hasonlóság.
    Jaccard index: közös szavak / összes egyedi szó.
    Nem kell ML — 5 sor, megbízható, 0 függőség.
    """
    def tokenize(t: str) -> set:
        return set(re.sub(r'[^a-záéíóöőúüű\w]', ' ', t.lower()).split())

    words_a = tokenize(text_a)
    words_b = tokenize(text_b)
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union        = words_a | words_b
    return len(intersection) / len(union)


def _extract_error_type(error_text: str) -> str:
    """Kinyeri a hibatípust a stderr szövegből."""
    if not error_text:
        return "unknown"
    for etype in [
        "FileNotFoundError", "AssertionError", "ImportError",
        "AttributeError", "TypeError", "ValueError", "KeyError",
        "IndexError", "NameError", "SyntaxError", "ModuleNotFoundError",
        "ZeroDivisionError", "RuntimeError", "PermissionError"
    ]:
        if etype in error_text:
            return etype
    return "unknown"


def get_relevant_few_shot_samples(
    current_task: str,
    error_text:   str = "",
    max_samples:  int = 2
) -> list[dict]:
    """
    Szemantikusan releváns fix mintákat kér le a fix_samples táblából.

    Rangsorolás:
      1. Feladat hasonlóság (Jaccard) — fő szignál
      2. Hibatípus egyezés — bónusz
      3. fix_succeeded=1 — kötelező szűrő
      4. Legfrissebb — döntetlen esetén

    Returns:
        [{"prompt": str, "bad_code": str, "issues": str,
          "fixed_code": str, "score": float}, ...]
    """
    try:
        import json as _json
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT prompt, bad_code, gemini_issues, fixed_code, gemini_score, timestamp
            FROM fix_samples
            WHERE fix_succeeded = 1
            ORDER BY timestamp DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        db.close()

        if not rows:
            return []

        current_error_type = _extract_error_type(error_text)
        scored = []

        for prompt, bad_code, issues_json, fixed_code, gem_score, ts in rows:
            # Feladat hasonlóság
            sim = _similarity_score(current_task, prompt or "")

            # Hibatípus bónusz
            error_bonus = 0.0
            if error_text and issues_json:
                try:
                    issues_list = _json.loads(issues_json) if isinstance(issues_json, str) else issues_json
                    issues_str  = " ".join(issues_list) if isinstance(issues_list, list) else str(issues_list)
                    sample_error_type = _extract_error_type(issues_str + (bad_code or ""))
                    if sample_error_type == current_error_type and current_error_type != "unknown":
                        error_bonus = 0.2
                except Exception:
                    pass

            final_score = sim + error_bonus

            if final_score > 0.05:  # minimum relevancia küszöb
                scored.append({
                    "prompt":     (prompt or "")[:200],
                    "bad_code":   (bad_code or "")[:800],
                    "issues":     issues_json or "[]",
                    "fixed_code": (fixed_code or "")[:800],
                    "score":      final_score
                })

        # Rangsor: score szerint csökkenő, top N
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_samples]

    except Exception as e:
        log.error(f"[FEW-SHOT] Lekérdezési hiba: {e}")
        return []


def get_successful_patterns(current_task: str, max_patterns: int = 2) -> list[dict]:
    """
    Sikeres feladatok közül lekéri a leghasonlóbbakat.
    Generálás ELŐTT futtatandó – "ilyen feladatnál ez működött" hint.

    Returns:
        [{"prompt": str, "code_snippet": str, "similarity": float}, ...]
    """
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()

        cursor.execute("""
            SELECT prompt, generated_code
            FROM training_data
            WHERE success = 1
              AND expert_mode = 'developer'
              AND generated_code IS NOT NULL
              AND length(generated_code) > 100
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        rows = cursor.fetchall()
        db.close()

        if not rows:
            return []

        scored = []
        for prompt, code in rows:
            sim = _similarity_score(current_task, prompt or "")
            if sim > 0.08:  # minimum hasonlóság küszöb
                # Csak az első 20 sort vesszük a kód struktúrájából
                code_lines  = (code or "").splitlines()
                snippet     = "\n".join(code_lines[:20])
                scored.append({
                    "prompt":       (prompt or "")[:150],
                    "code_snippet": snippet,
                    "similarity":   sim
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:max_patterns]

    except Exception as e:
        log.error(f"[FEW-SHOT] Sikeres pattern lekérdezési hiba: {e}")
        return []


def increment_review_count() -> None:
    """
    Növeli a mai nap review_count számlálóját.
    /review parancsnál hívandó.
    """
    try:
        db = sqlite3.connect(DB_PATH)
        today = datetime.now().strftime("%Y-%m-%d")
        db.execute("""
            INSERT INTO daily_stats (date, review_count)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET
                review_count = review_count + 1
        """, (today,))
        db.commit()
        db.close()
        log.info("[MEMORY] review_count növelve")
    except Exception as e:
        log.error(f"[MEMORY] review_count hiba: {e}")


def format_cache_stats_message(cs: dict) -> str:
    """Telegram-barát cache statisztika üzenet."""
    if not cs:
        return "❌ Cache statisztika nem elérhető."

    ratio = cs.get("hit_ratio", 0)
    icon = "🟢" if ratio >= 50 else "🟡" if ratio >= 20 else "🔴"

    return (
        f"⚡ *AXON Cache – elmúlt {cs['days']} nap*\n\n"
        f"{icon} *Hit arány:* {ratio}%\n"
        f"*Cache találat:* {cs['hits']} alkalom\n"
        f"*Cache miss:* {cs['misses']} alkalom\n"
        f"*Megtakarított API hívás:* {cs['saved_calls']}\n\n"
        f"💾 *Cache-elt feladatok:* {cs['cached_tasks']}\n"
        f"🏆 *Összes találat (all-time):* {cs['all_time_hits']}"
    )
