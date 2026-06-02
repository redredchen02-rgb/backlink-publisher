"""Type definitions and constants for the dedup store."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .._util.url import canonicalize_url
from ..config import _config_dir

# Database filename
_DB_FILENAME: str = "dedup.db"

# Per-store HMAC secret suffix
_SECRET_SUFFIX: str = ".hmac-secret"

# Hex length of key digest
_DIGEST_LEN: int = 16

# Stale TTL for attempting rows (seconds)
_STALE_TTL_S: int = 3600

# State type
State = Literal["attempting", "done", "failed", "uncertain"]

# Gate verdict type
GateVerdict = Literal["dispatch", "skip", "hold", "conflict"]


def _now() -> float:
    """Monotonic-ish current time in seconds."""
    return time.time()


def _default_dedup_db_path() -> Path:
    """Default path for the dedup database."""
    return _config_dir() / _DB_FILENAME


@dataclass(frozen=True)
class DedupKey:
    """Identity of a logical backlink: a post on ``platform`` (published by
    ``account``) that links to ``target_url``.

    ``target_url`` is canonicalized on construction (``canonicalize_url``) so
    scheme/host-case/trailing-slash/utm differences collapse to one key. ``account``
    defaults to a stable marker today (one account per channel); it is part of the
    key so a future second account on the same platform is a *distinct* key and is
    not false-skipped.
    """

    platform: str
    target_url: str
    account: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_url", canonicalize_url(self.target_url))

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.platform, self.account, self.target_url)


@dataclass(frozen=True)
class DedupRecord:
    """A persisted dedup row."""

    platform: str
    account: str
    target_url: str
    state: State
    verify_ok: bool | None
    live_url: str | None
    run_id: str | None
    owner_pid: int | None
    owner_run_id: str | None
    owner_started_at: float | None
    updated_at: float

    @property
    def key(self) -> DedupKey:
        # target_url is already canonical in the row; reconstruct without
        # re-canonicalizing (idempotent anyway).
        return DedupKey(
            platform=self.platform, target_url=self.target_url, account=self.account
        )


@dataclass(frozen=True)
class IntentOutcome:
    """Result of :meth:`DedupStore.intent_write`.

    ``won`` True  -> this caller inserted ``attempting`` and owns the dispatch.
    ``won`` False -> a row already existed (``existing_state`` set); the caller
                     must NOT dispatch — it holds (or skips, per the gate).
    """

    won: bool
    existing_state: State | None = None


@dataclass(frozen=True)
class GateDecision:
    """Result of :meth:`DedupStore.gate_and_claim`. ``record`` is the pre-claim
    row (``None`` for an absent key) — carried so the caller can emit the recorded
    ``live_url`` on a SKIP and surface the held state on a HOLD.
    """

    verdict: GateVerdict
    record: DedupRecord | None = None
