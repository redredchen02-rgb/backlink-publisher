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
	node --test tests/js/test_lib_api.mjs tests/js/test_lib_dom.mjs

# ── Code quality targets (Phase 3 F4) ────────────────────────────────────────

.PHONY: lint type-check coverage clean-all

lint:
	@ruff check src/ tests/ || true
	@ruff format --check src/ tests/ || true

type-check:
	@mypy src/backlink_publisher/_util/ src/backlink_publisher/config/ 2>&1 | tail -5 || true

coverage:
	@PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/ --cov=src/backlink_publisher \
		--cov-report=html --cov-report=term-missing -q --timeout=30

clean-all:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache .mypy_cache htmlcov .coverage
	@echo "Cleaned build artifacts"
