# tests/webui_conftest_poc/ — WebUI test subdirectory (proof of concept for conftest split)
#
# Named to avoid colliding with the top-level ``webui.py`` module: a
# subpackage literally named ``webui`` shadows it on sys.path for any
# ``import webui`` in the suite, silently breaking ``webui.app`` lookups
# (found 2026-07-03 during WSL/Linux verification of the v0.6.0 plan's U1).
