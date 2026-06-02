"""Internal constants for the dedup store."""

from __future__ import annotations
from typing import Literal

#: Filename of the dedup store inside ``_config_dir()``. Separate from
#: ``events.db`` on purpose.
_DB_FILENAME: str = "dedup.db"

#: Per-store HMAC secret suffix.
_SECRET_SUFFIX: str = ".hmac-secret"

#: Hex length of the key digest surfaced in the manifest stderr summary.
_DIGEST_LEN: int = 16

#: State type alias.
State = Literal["attempting", "done", "failed", "uncertain"]

#: Terminal states the gate treats as "already settled — skip" (done) or
#: "confirmed not landed — re-publishable" (failed).
_TERMINAL: frozenset[str] = frozenset({"done", "failed"})

#: Absolute age (seconds) beyond which an `attempting` row is considered
#: crashed regardless of PID liveness.
_STALE_TTL_S: int = 3600
