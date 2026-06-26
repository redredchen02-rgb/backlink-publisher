"""GSC (Google Search Console) integration package.

No top-level imports of ``googleapiclient`` or ``google.oauth2`` here —
those must stay inside method bodies to avoid discovery-cache side effects
at import time.
"""


__all__: list[str] = []