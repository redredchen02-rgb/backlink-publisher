"""Tests for idempotency._dedup_digest module."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Generator

import pytest

from backlink_publisher.idempotency._dedup_connection import ConnectionMixin
from backlink_publisher.idempotency._dedup_digest import DigestMixin
from backlink_publisher.idempotency._store_types import _DIGEST_LEN, _SECRET_SUFFIX, DedupKey


class TestDigestStore(ConnectionMixin, DigestMixin):
    """A test store that combines ConnectionMixin and DigestMixin."""

    def __init__(self, path: Path) -> None:
        self.path = path


@pytest.fixture
def digest_store(tmp_path: Path) -> Generator[TestDigestStore, None, None]:
    """Create a TestDigestStore with schema initialized."""
    store = TestDigestStore(tmp_path / "test.db")
    # Initialize schema
    with store.connect() as conn:
        pass
    yield store


class TestSecretPath:
    """Tests for DigestMixin._secret_path() method."""

    def test_secret_path_format(self, digest_store: TestDigestStore) -> None:
        secret_path = digest_store._secret_path()
        expected = digest_store.path.parent / (digest_store.path.name + _SECRET_SUFFIX)
        assert secret_path == expected


class TestReadSecret:
    """Tests for DigestMixin._read_secret() static method."""

    def test_read_secret_existing_file(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "test.secret"
        secret_file.write_bytes(b"test_secret_bytes")
        result = TestDigestStore._read_secret(secret_file)
        assert result == b"test_secret_bytes"

    def test_read_secret_missing_file(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "nonexistent.secret"
        result = TestDigestStore._read_secret(secret_file)
        assert result == b""


class TestLoadOrCreateSecret:
    """Tests for DigestMixin._load_or_create_secret() method."""

    def test_load_or_create_secret_first_time(self, digest_store: TestDigestStore) -> None:
        secret = digest_store._load_or_create_secret()
        assert len(secret) == 32  # secrets.token_bytes(32) returns 32 bytes
        # Verify file was created
        secret_path = digest_store._secret_path()
        assert secret_path.exists()
        assert secret_path.read_bytes() == secret

    def test_load_or_create_secret_subsequent(self, digest_store: TestDigestStore) -> None:
        # First call creates
        secret1 = digest_store._load_or_create_secret()
        # Second call reads existing
        secret2 = digest_store._load_or_create_secret()
        assert secret1 == secret2

    def test_load_or_create_secret_file_permissions(self, digest_store: TestDigestStore) -> None:
        digest_store._load_or_create_secret()
        secret_path = digest_store._secret_path()
        # Check file permissions (0o600 = owner read/write only)
        mode = secret_path.stat().st_mode
        assert mode & 0o600  # Owner read/write
        assert not (mode & 0o066)  # No group/other access


class TestKeyDigest:
    """Tests for DigestMixin.key_digest() method."""

    def test_key_digest_deterministic(self, digest_store: TestDigestStore) -> None:
        key = DedupKey(platform="blogger", account="user", target_url="http://example.com")
        digest1 = digest_store.key_digest(key)
        digest2 = digest_store.key_digest(key)
        assert digest1 == digest2

    def test_key_digest_different_keys(self, digest_store: TestDigestStore) -> None:
        key1 = DedupKey(platform="blogger", account="user", target_url="http://example.com")
        key2 = DedupKey(platform="medium", account="user", target_url="http://example.com")
        digest1 = digest_store.key_digest(key1)
        digest2 = digest_store.key_digest(key2)
        assert digest1 != digest2

    def test_key_digest_length(self, digest_store: TestDigestStore) -> None:
        key = DedupKey(platform="blogger", account="user", target_url="http://example.com")
        digest = digest_store.key_digest(key)
        assert len(digest) == _DIGEST_LEN

    def test_key_digest_format(self, digest_store: TestDigestStore) -> None:
        key = DedupKey(platform="blogger", account="user", target_url="http://example.com")
        digest = digest_store.key_digest(key)
        # Should be hex string
        assert all(c in "0123456789abcdef" for c in digest)


class TestStoreToken:
    """Tests for DigestMixin.store_token() method."""

    def test_store_token_deterministic(self, digest_store: TestDigestStore) -> None:
        token1 = digest_store.store_token()
        token2 = digest_store.store_token()
        assert token1 == token2

    def test_store_token_length(self, digest_store: TestDigestStore) -> None:
        token = digest_store.store_token()
        assert len(token) == _DIGEST_LEN

    def test_store_token_format(self, digest_store: TestDigestStore) -> None:
        token = digest_store.store_token()
        # Should be hex string
        assert all(c in "0123456789abcdef" for c in token)

    def test_store_token_uses_fixed_message(self, digest_store: TestDigestStore) -> None:
        # Manually compute expected token
        secret = digest_store._load_or_create_secret()
        expected = hmac.new(
            secret, b"dedup-store-generation-v1", hashlib.sha256
        ).hexdigest()[:_DIGEST_LEN]
        token = digest_store.store_token()
        assert token == expected


class TestDigestIntegration:
    """Integration tests for DigestMixin."""

    def test_key_digest_changes_with_secret(self, tmp_path: Path) -> None:
        # Create two stores with different paths (different secrets)
        store1 = TestDigestStore(tmp_path / "store1.db")
        store2 = TestDigestStore(tmp_path / "store2.db")
        # Initialize schemas
        with store1.connect() as conn:
            pass
        with store2.connect() as conn:
            pass
        
        key = DedupKey(platform="blogger", account="user", target_url="http://example.com")
        digest1 = store1.key_digest(key)
        digest2 = store2.key_digest(key)
        # Different stores should have different digests (different secrets)
        assert digest1 != digest2

    def test_store_token_changes_with_secret(self, tmp_path: Path) -> None:
        # Create two stores with different paths (different secrets)
        store1 = TestDigestStore(tmp_path / "store1.db")
        store2 = TestDigestStore(tmp_path / "store2.db")
        # Initialize schemas
        with store1.connect() as conn:
            pass
        with store2.connect() as conn:
            pass
        
        token1 = store1.store_token()
        token2 = store2.store_token()
        # Different stores should have different tokens (different secrets)
        assert token1 != token2
