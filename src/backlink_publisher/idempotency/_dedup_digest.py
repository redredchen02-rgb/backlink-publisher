"""Key digest and store token mixin for DedupStore."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets as _secrets
import time

from ._store_types import _DIGEST_LEN, _SECRET_SUFFIX, DedupKey


class DigestMixin:
    """Provides keyed HMAC digest and store token methods."""

    path: Path  # provided by the concrete subclass

    def _secret_path(self) -> Path:
        return self.path.with_name(self.path.name + _SECRET_SUFFIX)

    def _load_or_create_secret(self) -> bytes:
        """Per-store HMAC secret. Created once (O_CREAT|O_EXCL, fsync'd, 0o600)."""
        sp = self._secret_path()
        existing = self._read_secret(sp)
        if existing:
            return existing
        sp.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        token = _secrets.token_bytes(32)
        try:
            fd = os.open(str(sp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Lost the create race: the winner is mid-write. Re-read with a short
            # backoff until its bytes are visible rather than returning `token`.
            for _ in range(50):
                won = self._read_secret(sp)
                if won:
                    return won
                time.sleep(0.01)
            return self._read_secret(sp) or token
        try:
            os.write(fd, token)
            os.fsync(fd)
        finally:
            os.close(fd)
        return token

    @staticmethod
    def _read_secret(sp: Path) -> bytes:
        try:
            return sp.read_bytes()
        except FileNotFoundError:
            return b""

    def key_digest(self, key: DedupKey) -> str:
        """Keyed HMAC over the key tuple, truncated to _DIGEST_LEN hex chars."""
        secret = self._load_or_create_secret()
        msg = "\x1f".join(key.as_tuple()).encode("utf-8")
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:_DIGEST_LEN]

    def store_token(self) -> str:
        """Per-store identity token embedded in the preview manifest."""
        secret = self._load_or_create_secret()
        return hmac.new(
            secret, b"dedup-store-generation-v1", hashlib.sha256
        ).hexdigest()[:_DIGEST_LEN]
