"""Re-export shim — real code lives in backlink_publisher.sdk._cli_runner (plan 2026-06-22-001 U5a).

webui.py calls _wire_content_fetch_ttl_from_env() at startup; routes import
run_pipe / run_pipe_capture via PipelineAPI. All names are re-exported here
so existing import paths remain stable.
"""
from backlink_publisher.sdk._cli_runner import (  # noqa: F401
    _BANNER_RE,
    _is_fetch_verify_disabled,
    _MAX_SURFACED_ERROR,
    _parse_lines,
    _parse_run_result,
    _REPO_ROOT,
    _SRC_DIR,
    _wire_content_fetch_ttl_from_env,
    describe_cli_error,
    run_pipe,
    run_pipe_capture,
    strip_cli_diagnostic_banner,
    surface_cli_error,
)
