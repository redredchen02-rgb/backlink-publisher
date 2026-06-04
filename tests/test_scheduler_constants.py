"""Tests for named constants in webui_app/scheduler.py and equity_ledger.py (U1)."""
__tier__ = "unit"
import ast
import pathlib


_SCHEDULER_SRC = pathlib.Path("webui_app/scheduler.py").read_text()
_EQUITY_SRC = pathlib.Path("webui_app/routes/equity_ledger.py").read_text()


def _constant_value(src: str, name: str):
    """Return the integer value of a module-level constant (plain or annotated)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # Plain assignment: FOO = 300
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value
        # Annotated assignment: FOO: int = 300
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value
    return None


def test_rate_limit_retry_delay_constant_defined():
    assert _constant_value(_SCHEDULER_SRC, "_RATE_LIMIT_RETRY_DELAY_S") == 300


def test_stale_days_default_constant_defined():
    assert _constant_value(_EQUITY_SRC, "_STALE_DAYS_DEFAULT") == 30


def test_scheduler_uses_constant_not_bare_literal():
    """retry_delay assignment must reference _RATE_LIMIT_RETRY_DELAY_S, not 300."""
    tree = ast.parse(_SCHEDULER_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "retry_delay":
                    assert not isinstance(node.value, ast.Constant), (
                        "retry_delay must use _RATE_LIMIT_RETRY_DELAY_S, not a bare literal"
                    )


def test_equity_ledger_recheck_uses_constant_for_fallback():
    """recheck handler must reference _STALE_DAYS_DEFAULT, not bare 30."""
    tree = ast.parse(_EQUITY_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "equity_ledger_recheck":
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Constant) and subnode.value == 30:
                    raise AssertionError(
                        "Found bare 30 literal in equity_ledger_recheck; "
                        "should use _STALE_DAYS_DEFAULT"
                    )
