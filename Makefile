# Developer tooling targets — experimental, not part of the publishing pipeline.
# Prerequisite: pip install -e ".[dev-webwright]"
#
# Usage:
#   make scaffold PLATFORM=devto [LOGIN_URL=https://dev.to/enter]
#   make diagnose CHANNEL=velog

.PHONY: scaffold diagnose reconcile-check

scaffold:
ifndef PLATFORM
	$(error PLATFORM is required. Usage: make scaffold PLATFORM=devto [LOGIN_URL=https://...])
endif
	@python -c "import webwright" 2>/dev/null || \
		(echo "Error: webwright not installed. Run: pip install -e '.[dev-webwright]'" && exit 1)
	@python scripts/webwright_scaffold.py

diagnose:
ifndef CHANNEL
	$(error CHANNEL is required. Usage: make diagnose CHANNEL=velog)
endif
	@python -c "import webwright" 2>/dev/null || \
		(echo "Error: webwright not installed. Run: pip install -e '.[dev-webwright]'" && exit 1)
	@python scripts/webwright_diagnose.py

reconcile-check:
	@python -c "from backlink_publisher.events.reconciler import reconcile_all; reconcile_all()" \
		&& echo "RECONCILE OK" || (echo "RECONCILE FAILED" && exit 1)

.PHONY: test-js
test-js:
	node --test tests/js/test_lib_api.mjs tests/js/test_lib_dom.mjs tests/js/test_notifications.mjs tests/js/test_ui_states.mjs tests/js/test_ui_nav_badge.mjs

# ── Browser selector-drift checks (Plan 2026-06-15-001 B3) ───────────────────
# Static guard (CI, no browser): selector constants present + success regex valid.
.PHONY: selector-drift
selector-drift:
	@PYTHONPATH=src pytest tests/test_browser_selector_manifest.py -q

# Attended live drift check: re-verify selectors against the real sites. Requires
# an attached Chrome (BACKLINK_PUBLISHER_REAL_CHROME_ATTACH=1) — run by an
# operator on a schedule, NOT in CI. Surfaces a live DOM rename as a test failure.
.PHONY: selector-smoke
selector-smoke:
	@BACKLINK_PUBLISHER_REAL_CHROME_ATTACH=1 PYTHONPATH=src \
		pytest -m real_browser_publish_smoke -q tests/

# ── Accessibility audit (axe-core via Playwright) ────────────────────────────
# Audits the changed WebUI routes against axe-core; fails on moderate+ findings
# (override the bar with A11Y_FAIL_IMPACTS). Needs Playwright browsers + vendored
# tools/a11y/vendor/axe.min.js, so it is opt-in (NOT in CI), like selector-smoke.
.PHONY: test-a11y
test-a11y:
	@.venv/bin/python tools/a11y/audit.py

# ── Code quality targets (Phase 3 F4) ────────────────────────────────────────

.PHONY: lint type-check coverage clean-pyc clean-all setup-hooks

lint:
	@ruff check src/ tests/ || true
	@ruff format --check src/ tests/ || true

type-check:
	@mypy src/backlink_publisher/_util/ src/backlink_publisher/config/ 2>&1 | tail -5 || true

coverage:
	@PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/ --cov=src/backlink_publisher \
		--cov-report=html --cov-report=term-missing -q --timeout=30

setup-hooks:
	bash scripts/install-post-merge-hook.sh
	@echo "Git hooks installed. Set BACKLINK_PUBLISHER_WORKTREE_AUTOREMOVE=1 in shell rc for auto cleanup"

clean-pyc:
	@find . -type d -name __pycache__ -not -path '*/.venv/*' -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -not -path '*/.venv/*' -delete 2>/dev/null || true
	@echo "Cleaned __pycache__ and .pyc artifacts"

clean-all: clean-pyc
	@rm -rf .pytest_cache .mypy_cache htmlcov .coverage
	@echo "Cleaned all build artifacts"

# ── Static file optimization (C4) ──────────────────────────────

.PHONY: optimize-static
optimize-static:
	@echo "Optimizing static assets..."
	@python scripts/optimize_static.py

# ── Mutation testing (G4) ──────────────────────────────────────

.PHONY: mutate
mutate:
	@echo "Running mutation tests (mutmut)..."
	@PYTHONHASHSEED=0 PYTHONPATH=src mutmut run \
		--paths-to-mutate=src/backlink_publisher/_util/ \
		--paths-to-exclude=tests/

# ── Logging configuration check (E1) ──────────────────────────

.PHONY: check-log
check-log:
	@python -c "\
from backlink_publisher._util.structlog_config import configure_structlog; \
configure_structlog(); \
print('structlog configured OK')"
	@python -c "\
from backlink_publisher._util.logger import validate_logger; \
validate_logger.info('PipelineLogger still works'); \
print('PipelineLogger backward compat OK')"

# ── Docker targets (F2) ──────────────────────────────────────

.PHONY: docker-build docker-run

docker-build:
	@docker build -t backlink-publisher .

docker-run:
	@docker run -p 8888:8888 \
		-v ~/.config/backlink-publisher:/config \
		-e BACKLINK_PUBLISHER_CONFIG_DIR=/config \
		backlink-publisher
