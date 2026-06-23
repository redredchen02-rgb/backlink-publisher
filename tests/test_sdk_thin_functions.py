"""U8 (plan 2026-06-22-001): the sdk thin functions delegate to PipelineAPI and
normalize Python input to JSONL.

The heavy in-process↔subprocess byte/exit parity is already locked elsewhere
(``test_pipeline_inprocess_characterization.py`` for plan/validate,
``test_publish_inprocess_sdk_parity.py`` for publish). These tests pin the NEW
sdk surface: ``plan``/``validate``/``publish`` accept a ``list[dict]`` / ``dict``
/ JSONL string, serialize once via ``_to_jsonl``, and forward verbatim to the
matching ``PipelineAPI`` method (``publish`` → ``publish_seed``).
"""

from __future__ import annotations

__tier__ = "unit"

import json
from unittest import mock

from backlink_publisher import sdk
from backlink_publisher.sdk.api import PipeResult


def test_to_jsonl_passthrough_string() -> None:
    raw = '{"a": 1}\n{"b": 2}'
    assert sdk._to_jsonl(raw) == raw


def test_to_jsonl_single_dict() -> None:
    assert json.loads(sdk._to_jsonl({"a": 1})) == {"a": 1}
    assert "\n" not in sdk._to_jsonl({"a": 1})


def test_to_jsonl_list_of_dicts_is_one_line_each() -> None:
    out = sdk._to_jsonl([{"a": 1}, {"b": 2}])
    lines = out.split("\n")
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"b": 2}]


def test_plan_delegates_to_pipeline_api_plan() -> None:
    sentinel = PipeResult(stdout="planned", success=True, exit_code=0)
    with mock.patch.object(sdk.PipelineAPI, "plan", return_value=sentinel) as m:
        result = sdk.plan([{"target_url": "https://x/y"}], work_count=7)
    assert result is sentinel
    (jsonl_arg,), kwargs = m.call_args
    assert json.loads(jsonl_arg) == {"target_url": "https://x/y"}
    assert kwargs == {"work_count": 7}


def test_validate_delegates_with_no_check_urls() -> None:
    sentinel = PipeResult(stdout="ok", success=True, exit_code=0)
    with mock.patch.object(sdk.PipelineAPI, "validate", return_value=sentinel) as m:
        result = sdk.validate([{"id": "r1"}], no_check_urls=False)
    assert result is sentinel
    (jsonl_arg,), kwargs = m.call_args
    assert json.loads(jsonl_arg) == {"id": "r1"}
    assert kwargs == {"no_check_urls": False}


def test_publish_delegates_to_publish_seed() -> None:
    """sdk.publish forwards to publish_seed (rows are self-describing) — NOT the
    platform/mode publish()."""
    sentinel = PipeResult(stdout="published", success=True, exit_code=0)
    with mock.patch.object(sdk.PipelineAPI, "publish_seed", return_value=sentinel) as m:
        result = sdk.publish([{"platform": "blogger", "target_url": "https://x/y"}])
    assert result is sentinel
    (jsonl_arg,), kwargs = m.call_args
    assert json.loads(jsonl_arg) == {"platform": "blogger", "target_url": "https://x/y"}
    assert kwargs == {}


def test_publish_accepts_a_jsonl_string_unchanged() -> None:
    sentinel = PipeResult(success=True, exit_code=0)
    with mock.patch.object(sdk.PipelineAPI, "publish_seed", return_value=sentinel) as m:
        sdk.publish('{"platform": "blogger"}')
    (jsonl_arg,), _ = m.call_args
    assert jsonl_arg == '{"platform": "blogger"}'
