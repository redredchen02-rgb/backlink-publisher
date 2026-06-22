"""Re-export shim — real code lives in backlink_publisher.sdk.api (plan 2026-06-22-001 U5a).

All names that external callers depended on (routes, scheduler, tests) are
re-exported explicitly so import paths remain stable while the implementation
lives in core.
"""
from backlink_publisher.sdk.api import (  # noqa: F401
    PipelineAPI,
    PipeResult,
    parse_publish_results,
    publish_state_summary,
    run_pipe_capture,  # re-exported as test-patch seam (tests/test_pipeline_api_seam.py)
    run_pipe,
    _typed_error_result,
    _parse_jsonl_rows,
)
