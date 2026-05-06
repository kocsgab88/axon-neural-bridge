"""
    A  X  O  N  |  R E T R Y  E N G I N E  v1.0
    ─────────────────────────────────────────────
    Forrás: Claw Code (Claude Code clean-room port) – claw_provider.rs
    Pattern: send_with_retry + exponential backoff

    Eredeti Rust logika Pythonra fordítva:
        - max_retries: 2 (összesen 3 kísérlet)
        - initial_backoff: 200ms
        - max_backoff: 2s
        - backoff_for_attempt: initial * 2^(attempt-1), capped at max

    Retryable hibák (Anthropic API-ra szabva):
        - APIStatusError: 529 (overloaded), 500 (internal), 503 (unavailable)
        - APIConnectionError / APITimeoutError – hálózati probléma
        - RateLimitError (429) – exponential backoff különösen hasznos itt

    Nem retryable:
        - AuthenticationError (401) – rossz API key, retry nem segít
        - PermissionDeniedError (403)
        - InvalidRequestError (400) – prompt hibás, retry sem javítja
"""

import time
import logging
from typing import Callable, TypeVar, Any

import anthropic

log = logging.getLogger("AXON")

# ── Config (Claw Code DEFAULT_* konstansok alapján) ─────────────────────────
MAX_RETRIES       = 2          # összesen 3 kísérlet (0, 1, 2)
INITIAL_BACKOFF   = 0.2        # 200ms – Rust: Duration::from_millis(200)
MAX_BACKOFF       = 2.0        # 2s    – Rust: Duration::from_secs(2)

# ── Retryable hibaosztályok ──────────────────────────────────────────────────
_RETRYABLE_STATUS = {500, 503, 529}  # internal, unavailable, overloaded

def _is_retryable(exc: Exception) -> bool:
    """Eldönti hogy egy Anthropic API hiba megér-e újrapróbálkozást."""
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False

def _backoff_for_attempt(attempt: int) -> float:
    """
    Exponential backoff – Rust backoff_for_attempt() Python portja.
    attempt 1 → 0.2s, attempt 2 → 0.4s, capped at MAX_BACKOFF.
    """
    multiplier = 2 ** (attempt - 1)
    delay = INITIAL_BACKOFF * multiplier
    return min(delay, MAX_BACKOFF)

T = TypeVar("T")

def call_with_retry(fn: Callable[[], T], label: str = "Claude") -> T:
    """
    Szinkron retry wrapper.
    fn: egy paramétermentes callable ami Anthropic hívást végez.
    label: logban megjelenik (pl. "S1", "S2", "routing").

    Használat:
        result = call_with_retry(
            lambda: claude.messages.create(...),
            label="S1"
        )
    """
    attempts = 0
    last_exc: Exception | None = None

    while True:
        attempts += 1
        try:
            return fn()
        except Exception as exc:
            if _is_retryable(exc) and attempts <= MAX_RETRIES + 1:
                last_exc = exc
            else:
                # Nem retryable, vagy elfogytak a kísérletek
                raise

        if attempts > MAX_RETRIES:
            break

        delay = _backoff_for_attempt(attempts)
        log.warning(
            f"[RETRY] {label} – {type(last_exc).__name__} "
            f"(attempt {attempts}/{MAX_RETRIES + 1}), "
            f"backoff {delay:.1f}s"
        )
        time.sleep(delay)

    # RetriesExhausted – Rust ApiError::RetriesExhausted portja
    log.error(
        f"[RETRY] {label} – összes kísérlet ({attempts}) kimerült. "
        f"Utolsó hiba: {type(last_exc).__name__}: {last_exc}"
    )
    raise last_exc  # type: ignore[misc]
