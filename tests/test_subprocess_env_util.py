"""Tests for backlink_publisher._util.subprocess_env."""
from __future__ import annotations

__tier__ = "unit"
import os

from backlink_publisher._util.subprocess_env import utf8_child_env


def test_utf8_child_env_merges_into_given_dict():
    result = utf8_child_env({"FOO": "bar"})

    assert result == {"FOO": "bar", "PYTHONIOENCODING": "utf-8"}


def test_utf8_child_env_none_copies_os_environ_without_mutating_it():
    before = dict(os.environ)

    result = utf8_child_env(None)

    assert result["PYTHONIOENCODING"] == "utf-8"
    for key, value in before.items():
        assert os.environ.get(key) == value
    assert dict(os.environ) == before


def test_utf8_child_env_overrides_existing_pythonioencoding():
    result = utf8_child_env({"PYTHONIOENCODING": "cp950"})

    assert result["PYTHONIOENCODING"] == "utf-8"
