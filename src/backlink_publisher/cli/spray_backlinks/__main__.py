"""Package entry-point: forward to the same ``main()`` the pyproject console
script uses, so ``python -m backlink_publisher.cli.spray_backlinks`` works after
the package split (an empty ``__main__`` would silently drop all output for the
``-m`` callers — CI and webui dispatch). Mirrors ``cli/plan_backlinks/__main__``.
"""

from . import main

raise SystemExit(main() or 0)
