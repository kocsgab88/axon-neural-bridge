"""
    A  X  O  N  |  S E S S I O N  C O M P A C T I O N  v1.0
    ──────────────────────────────────────────────────────────
    Forrás: Claw Code (Claude Code clean-room port) – main.rs
    Pattern: compact_session() + CompactionConfig + format_compact_report()

    Az eredeti Rust logika elvei Pythonra fordítva:
        - Ha a history meghaladja a token-küszöböt → összefoglaltat Claude-dal
        - Az összefoglalás HELYETTESÍTI a régi history-t (nem hozzáadja)
        - Az összefoglalás egy "assistant" turn formájában marad meg
        - A legutóbbi N turn érintetlenül marad (fresh context)

    AXON-specifikus döntések:
        - Küszöb: 6000 karakter (az axon_memory.py 8000-es trim előtt aktivál)
        - KEEP_RECENT_TURNS: 3 – az utolsó 3 user+assistant pár marad érintetlen
        - Compaction csak DEVELOPER pipeline history-n fut (CREATIVE nincs history,
          PLANNER/ANALYST ritkán éri el a küszöböt)
        - Ha nincs mit tömöríteni → no-op, visszatér az eredeti history-val

    Kapcsolódó fájlok:
        - axon_memory.py: add_to_history(), get_history(), clear_history()
        - axon_telegram_v6.py: /compact parancs hívja ezt
"""

import logging
from dataclasses import dataclass

log = logging.getLogger("AXON")

# ── Config ───────────────────────────────────────────────────────────────────
COMPACTION_CHAR_THRESHOLD = 6000   # ennyi karakter felett aktivál
KEEP_RECENT_TURNS = 3              # utolsó N user+assistant pár érintetlen marad
COMPACTION_MAX_TOKENS = 1000       # összefoglaló max hossza

# ── Típusok ──────────────────────────────────────────────────────────────────
@dataclass
class CompactionResult:
    compacted_history: list[dict]   # az új, tömörített history
    removed_turns: int              # hány turn-t tömörítettünk
    kept_turns: int                 # hány turn maradt érintetlenül
    skipped: bool                   # True ha nem kellett tömöríteni
    summary_chars: int              # összefoglaló hossza karakterben


def _history_char_count(history: list[dict]) -> int:
    """History teljes karakter hossza."""
    return sum(len(turn.get("content", "")) for turn in history)


def _build_compaction_prompt(old_turns: list[dict]) -> str:
    """
    Összefoglaló prompt az eltömörítendő turnökhöz.
    Claw Code elvei alapján: tömör, tényszerű, kontextus-megőrző összefoglalás.
    """
    conversation_text = ""
    for turn in old_turns:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        prefix = "User" if role == "user" else "Assistant"
        conversation_text += f"\n{prefix}: {content}\n"

    return (
        "Az alábbi korábbi beszélgetés-részletből készíts tömör összefoglalót. "
        "Fókuszálj a technikai döntésekre, implementált kódra, megoldott hibákra és "
        "nyitott feladatokra. Csak a folytatáshoz releváns információkat tartsd meg. "
        "Max 800 karakter.\n\n"
        f"KORÁBBI BESZÉLGETÉS:\n{conversation_text}\n\n"
        "ÖSSZEFOGLALÓ (tömör, tényszerű):"
    )


def compact_history(
    history: list[dict],
    call_claude_fn,          # szinkron Claude hívó: fn(system, user_msg, max_tokens) → str
    chat_id: str = "system"
) -> CompactionResult:
    """
    History tömörítés – Claw Code compact_session() Python portja.

    Args:
        history: a teljes jelenlegi history (list of {"role": ..., "content": ...})
        call_claude_fn: szinkron Claude hívó függvény (call_claude_sync)
        chat_id: csak logoláshoz

    Returns:
        CompactionResult – mindig tartalmaz érvényes compacted_history-t
    """
    total_chars = _history_char_count(history)

    # Threshold check – Claw Code: "Session is already below the compaction threshold"
    if total_chars < COMPACTION_CHAR_THRESHOLD:
        log.info(f"[COMPACT/{chat_id}] Nincs szükség tömörítésre ({total_chars} kar < {COMPACTION_CHAR_THRESHOLD})")
        return CompactionResult(
            compacted_history=history,
            removed_turns=0,
            kept_turns=len(history),
            skipped=True,
            summary_chars=0
        )

    # Szétválasztás: régi turnök (tömörítendő) + friss turnök (érintetlen)
    # Claw Code: KEEP_RECENT_TURNS user+assistant pár = 2*N turn
    keep_count = KEEP_RECENT_TURNS * 2   # user + assistant párok
    if len(history) <= keep_count:
        # Túl rövid a history hogy szétválasszuk – skip
        log.info(f"[COMPACT/{chat_id}] History túl rövid a szétválasztáshoz ({len(history)} turn)")
        return CompactionResult(
            compacted_history=history,
            removed_turns=0,
            kept_turns=len(history),
            skipped=True,
            summary_chars=0
        )

    old_turns = history[:-keep_count]    # tömörítendők
    recent_turns = history[-keep_count:] # érintetlenek

    log.info(
        f"[COMPACT/{chat_id}] Tömörítés: {len(old_turns)} régi turn → összefoglaló, "
        f"{len(recent_turns)} friss turn marad | {total_chars} kar"
    )

    # Claude összefoglaló hívás
    try:
        compaction_prompt = _build_compaction_prompt(old_turns)
        summary = call_claude_fn(
            system=(
                "Technikai összefoglaló szakértő vagy. "
                "Tömör, tényszerű összefoglalókat írsz korábbi AI-fejlesztői párbeszédekről. "
                "Csak a folytatáshoz szükséges információkat tartsd meg."
            ),
            user_msg=compaction_prompt,
            max_tokens=COMPACTION_MAX_TOKENS
        )
        summary = summary.strip()
    except Exception as exc:
        log.error(f"[COMPACT/{chat_id}] Összefoglaló hívás sikertelen: {exc} – compaction skip")
        return CompactionResult(
            compacted_history=history,
            removed_turns=0,
            kept_turns=len(history),
            skipped=True,
            summary_chars=0
        )

    # Új history: összefoglaló turn + friss turnök
    # Claw Code: a summary "assistant" role-ként kerül be, mintha az AI mondta volna
    summary_turn = {
        "role": "assistant",
        "content": f"[ÖSSZEFOGLALÓ – korábbi {len(old_turns)} turn tömörítve]\n{summary}"
    }
    compacted = [summary_turn] + recent_turns

    log.info(
        f"[COMPACT/{chat_id}] Kész: {len(old_turns)} turn → 1 összefoglaló, "
        f"{len(recent_turns)} friss turn megmaradt | "
        f"összefoglaló: {len(summary)} kar"
    )

    return CompactionResult(
        compacted_history=compacted,
        removed_turns=len(old_turns),
        kept_turns=len(recent_turns),
        skipped=False,
        summary_chars=len(summary)
    )


def format_compact_report(result: CompactionResult) -> str:
    """
    Telegram üzenet a tömörítés eredményéről.
    Claw Code format_compact_report() Python portja.
    """
    if result.skipped:
        return (
            "✅ *Compaction*\n"
            f"Nincs szükség tömörítésre – a history a küszöb alatt van "
            f"({COMPACTION_CHAR_THRESHOLD} kar).\n"
            f"Jelenlegi turnök: {result.kept_turns}"
        )
    return (
        "🗜 *Compaction kész*\n"
        f"Tömörített turnök: {result.removed_turns}\n"
        f"Megmaradt friss turnök: {result.kept_turns}\n"
        f"Összefoglaló hossza: {result.summary_chars} kar\n"
        "_Tipp: /history paranccsal ellenőrizheted az aktív kontextust._"
    )
