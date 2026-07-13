"""Low-level durable-write helpers shared across the package.

``safe_write.atomic_write`` and friends are the canonical way to persist files
(temp-file + fsync + atomic replace). Kept as an explicit regular package (not a
PEP-420 namespace package) so the import-linter layering contracts can track it.
"""
