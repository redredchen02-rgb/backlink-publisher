"""Error report sanitizer service — Plan 2026-07-01-002 Unit 1 (R7).

Turns a raw client-submitted frontend error report into a version safe to
persist or display, by *composing* three existing/complementary sanitization
layers rather than building a fourth mechanism from scratch:

Layer 1 (free text)
    Every string-valued field is run through
    :func:`backlink_publisher.events.scrubber.scrub_text` (regex + entropy
    secret detection). Fields whose key looks like a URL (``url`` or
    ``*_url``) additionally get a query-string pass that masks parameters
    whose *name* looks like a token/session/CSRF identifier —
    ``scrub_text``'s regex/entropy rules don't reliably catch a clean,
    short value like ``?session=abc123``, because it isn't shaped like a
    known secret pattern and is well under the 32-char entropy floor.

Layer 2 (structured fields)
    Any dict-valued field (e.g. a ``context`` blob) is redacted with
    :func:`backlink_publisher._util.logger._redact_in_place` /
    ``_SENSITIVE_KEYS`` — the same case-insensitive exact-key-name matcher
    the pipeline logger uses, reused verbatim on a copy so the caller's
    input is never mutated.

Layer 3 (exact known-credential values) — new in this plan
    Security review found ``scrub_text``'s regex/entropy detector has a
    structural blind spot for *this project's own* platform credentials
    (dev.to / HackMD / Mataroa / Qiita / GitHub-Pages / GitLab-Pages /
    Zenn / Hatena / Tumblr / WordPress.com tokens, the FRW image-gen key,
    and the LLM/image-gen API keys): they are manually-pasted opaque
    strings with no format validation, and may be short or hex-shaped.
    Pure-hex-alphabet Shannon entropy tops out at 4.0 bits/char — always
    below ``scrub_text``'s 4.5 threshold — and the entropy check only
    scans strings >= 32 chars, so a short or non-32/non-64-char credential
    is mathematically invisible to it. The new user-description free-text
    field this plan adds is exactly where an operator is likely to paste
    such a token while describing a problem.

    The fix is not to guess a secret's *shape* but to use the fact that we
    already know its *exact value*: :func:`_known_secret_values` gathers
    every actually-configured credential value this project knows about,
    and every string leaf (free-text or structured) gets checked for an
    exact substring match against that set. This is *inspired by* — not a
    literal reuse of — the offline, pre-commit ``rg -nF -f <token-file>``
    doc-lint technique documented in
    ``docs/solutions/best-practices/self-doc-sanitization-leak-recurrence-2026-05-15.md``;
    that precedent is a manual/offline grep gate over committed docs, not
    runtime Flask code, so the mechanism here is new even though the idea
    (compare against *known values*, not guessed shapes) is the same.

Every string field is additionally length-capped (4000 chars, mirroring the
precedent in
``docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md``)
with a visible ``<TRUNCATED:N more chars>`` marker — never a silent cut.

Sanitization never raises and never silently drops a field or the whole
report: a field (or, if the top-level payload itself isn't a dict, the
whole payload) whose shape can't be cleanly handled degrades to a
best-effort str()-ified + scrubbed version, and the returned dict carries
``sanitize_degraded: True`` so callers can surface that honestly rather than
pretending the report was fully clean.
"""
from __future__ import annotations

from collections.abc import Iterable
import copy
import json
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backlink_publisher._util.logger import _MAX_REDACT_DEPTH, _redact_in_place
from backlink_publisher.events.scrubber import scrub_text

#: Length cap per field — mirrors the 4000-char precedent from
#: typed-error-envelope-over-stderr-truncation-2026-05-27.md, bounding both
#: the 64KB fetch/keepalive transport limit and on-disk storage growth.
_MAX_FIELD_LEN: Final[int] = 4000

#: Generic redaction marker used by Layer 2 (`_redact_in_place`, reused
#: as-is), the URL query-string filter, and Layer 3 (exact known-value
#: match). Deliberately distinct from `scrub_text`'s own ``<REDACTED>``
#: marker so a reader of a sanitized report can tell which layer fired.
_MASK: Final[str] = "***"

#: Query-string parameter names known to carry a token/session/CSRF value by
#: naming convention alone — exact (case-insensitive) match against the
#: whole param name.
_SENSITIVE_QUERY_EXACT: Final[frozenset[str]] = frozenset({
    "token", "access_token", "accesstoken", "api_key", "apikey",
    "session", "session_id", "sessionid", "sid",
    "sig", "signature",
    "csrf", "csrf_token", "csrftoken", "xsrf", "xsrf_token", "xsrftoken",
    "auth", "auth_token", "authtoken", "authorization",
    "secret", "client_secret", "clientsecret",
    "password", "refresh_token", "refreshtoken", "id_token", "idtoken",
})

#: Longer/specific-enough markers that are safe to match as a *substring* of
#: a query-param name (e.g. ``csrfmiddlewaretoken``) without the
#: false-positive risk of a bare 3-letter fragment like "sid"/"sig" (which
#: collide with ordinary English words such as "inside"/"design" — those two
#: stay exact-match-only, above).
_SENSITIVE_QUERY_SUBSTRINGS: Final[tuple[str, ...]] = (
    "token", "secret", "password", "csrf", "xsrf", "session", "api_key",
    "apikey", "authorization",
)

# ── Layer 3: per-platform secret-field curation ─────────────────────────────
#
# webui_app.services.credential_service._TOKEN_FIELDS_DISPATCH (mirrored by
# src/backlink_publisher/config/tokens.py's save_*_token functions) mixes
# real secret fields (api_key/token/consumer_secret/...) with non-secret
# identifier fields (hatena_id, blog_id, blog_identifier, site, github_repo,
# username) in the SAME per-platform tuple. This map lists, per channel,
# which of that tuple's field names are NOT secret — every other field in
# the tuple is treated as secret. Deliberately a deny-list (not an
# allow-list of secret fields): a future platform added to
# _TOKEN_FIELDS_DISPATCH without a curated entry here defaults to "every
# field is secret", which over-redacts a non-secret identifier rather than
# risking a leaked credential.
_NON_SECRET_TOKEN_FIELDS: Final[dict[str, frozenset[str]]] = {
    "tumblr": frozenset({"blog_identifier"}),
    "wordpresscom": frozenset({"site"}),
    "hatena": frozenset({"hatena_id", "blog_id"}),
    "zenn": frozenset({"github_repo", "username"}),
    # ghpages / gitlabpages: single "token" field in the dispatch tuple,
    # nothing non-secret to exclude.
}


# ── URL query-string token filtering (Layer 1 extra pass) ───────────────────


def _is_sensitive_query_param(name: str) -> bool:
    """True if *name* (a URL query-param key) looks like a token/session/CSRF
    identifier by naming convention — independent of the value's shape."""
    n = name.casefold()
    if n in _SENSITIVE_QUERY_EXACT:
        return True
    return any(marker in n for marker in _SENSITIVE_QUERY_SUBSTRINGS)


def _filter_url_query_tokens(url: str) -> str:
    """Mask query-string params that look like tokens by name; keep the rest.

    A clean-looking ``?session=abc123`` won't necessarily trip
    ``scrub_text``'s regex/entropy rules, but by naming convention it is
    still a token — this filter is the necessary supplement, scoped to
    fields recognised as URLs (see :func:`_is_url_field`).

    Best-effort: a URL that fails to parse is returned unchanged rather than
    raising — this is a defensive filter layered in front of ``scrub_text``,
    not a URL validator.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    filtered = [
        (k, _MASK if _is_sensitive_query_param(k) else v) for k, v in pairs
    ]
    new_query = urlencode(filtered)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _is_url_field(key: str) -> bool:
    k = key.casefold()
    return k == "url" or k.endswith("_url")


# ── shared finishing helpers (length cap + Layer 3 exact-value mask) ───────


def _apply_length_cap(s: str) -> str:
    """Cap *s* at ``_MAX_FIELD_LEN`` chars with a visible truncation marker
    (never a silent cut) — same convention `scrub_text` uses for its own,
    much larger, internal cap."""
    if len(s) <= _MAX_FIELD_LEN:
        return s
    overflow = len(s) - _MAX_FIELD_LEN
    return s[:_MAX_FIELD_LEN] + f"<TRUNCATED:{overflow} more chars>"


def _mask_known_secret_values(s: str, known_secrets: frozenset[str]) -> str:
    """Exact-substring-replace every known configured credential value in *s*.

    Longest-first so a shorter secret that happens to be a substring of a
    longer one can't partially consume the longer match before it is
    replaced whole.
    """
    for secret in sorted(known_secrets, key=len, reverse=True):
        if secret and secret in s:
            s = s.replace(secret, _MASK)
    return s


# ── Layer 1: free-text fields ────────────────────────────────────────────────


def _sanitize_string_field(key: str, value: str, known_secrets: frozenset[str]) -> str:
    """Layer 1: URL query-token filter (if applicable) -> `scrub_text` ->
    Layer 3 exact-value match -> length cap."""
    if _is_url_field(key):
        value = _filter_url_query_tokens(value)
    cleaned, _hits = scrub_text(value)
    cleaned = _mask_known_secret_values(cleaned, known_secrets)
    return _apply_length_cap(cleaned)


# ── Layer 2: structured fields ───────────────────────────────────────────────


def _finalize_leaf(value: Any, known_secrets: frozenset[str], depth: int = 0) -> Any:
    """Post-``_redact_in_place`` pass: recursively apply Layer-3 exact-value
    masking + the length cap to whatever string leaves survived key-name
    redaction (a value under a non-sensitive key name can still happen to
    *equal* a known credential). Containers recurse; scalars pass through.

    Depth-capped (mirrors `_redact_in_place`'s own `_MAX_REDACT_DEPTH` guard)
    so a pathological self-referencing structure can't recurse forever.
    """
    if depth >= _MAX_REDACT_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: _finalize_leaf(v, known_secrets, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_finalize_leaf(v, known_secrets, depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(_finalize_leaf(v, known_secrets, depth + 1) for v in value)
    if isinstance(value, str):
        return _apply_length_cap(_mask_known_secret_values(value, known_secrets))
    return value


def _sanitize_structured_field(value: dict, known_secrets: frozenset[str]) -> dict:
    """Layer 2: key-name redaction, reusing `_redact_in_place`/`_SENSITIVE_KEYS`
    verbatim on a deep copy (never mutates the caller's input), followed by
    the Layer-3 + length-cap finishing pass over whatever wasn't already
    key-redacted."""
    working = copy.deepcopy(value)
    _redact_in_place(working)
    return _finalize_leaf(working, known_secrets)


# ── per-field dispatch + degrade path ────────────────────────────────────────


def _sanitize_value(key: str, value: Any, known_secrets: frozenset[str]) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string_field(key, value, known_secrets)
    if isinstance(value, dict):
        return _sanitize_structured_field(value, known_secrets)
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(key, item, known_secrets) for item in value]
    # Unexpected shape (custom object, bytes, set, ...) — signal the caller
    # to degrade this field rather than silently coercing it.
    raise TypeError(f"unsupported field type for {key!r}: {type(value).__name__}")


def _best_effort_string(value: Any, known_secrets: frozenset[str]) -> str:
    """Degrade path for a field (or whole payload) whose shape
    :func:`sanitize_error_report` can't cleanly handle: stringify, scrub,
    mask known secrets, cap length. Never raises — any failure along the
    way falls back to a fixed placeholder rather than propagating."""
    try:
        text = str(value)
    except Exception:
        return "<unrepresentable>"
    try:
        text, _hits = scrub_text(text)
    except Exception:
        pass
    try:
        text = _mask_known_secret_values(text, known_secrets)
    except Exception:
        pass
    return _apply_length_cap(text)


def sanitize_error_report(report: Any) -> dict[str, Any]:
    """Turn a raw client-submitted error report into a version safe to
    persist or display. See the module docstring for the three composed
    layers.

    Never raises. A field with an unexpected shape — or, if *report* itself
    isn't a dict, the whole payload — degrades to a best-effort sanitized
    string rather than being silently dropped or aborting the submission;
    the returned dict then carries ``sanitize_degraded: True``. A cleanly
    sanitized report carries ``sanitize_degraded: False`` so callers can
    always rely on the key being present.
    """
    known_secrets = _known_secret_values()

    if not isinstance(report, dict):
        return {
            "sanitize_degraded": True,
            "raw": _best_effort_string(report, known_secrets),
        }

    result: dict[str, Any] = {}
    degraded = False
    for key, value in report.items():
        try:
            result[key] = _sanitize_value(key, value, known_secrets)
        except Exception:
            degraded = True
            result[key] = _best_effort_string(value, known_secrets)

    result["sanitize_degraded"] = degraded
    return result


# ── Layer 3: known-secret-value collection ──────────────────────────────────


def _collect_json_field_values(path: Path, fields: Iterable[str], out: set[str]) -> None:
    """Best-effort: read *path* as JSON, add the named string fields to *out*.

    Missing file / corrupt JSON / non-dict content are all silently
    skipped — this is a defense-in-depth gatherer, not a validator, and must
    never raise (callers rely on that for the "never abort" contract)."""
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for field_name in fields:
        v = data.get(field_name)
        if isinstance(v, str) and v:
            out.add(v)


def _known_secret_values() -> frozenset[str]:
    """Gather every actually-configured credential value this project knows
    about, for Layer 3's exact-substring match. See the module docstring.

    Sources (all best-effort — a missing/corrupt file, an unavailable
    import, or an unconfigured credential is silently skipped, never
    raised):

    - ``webui_app.services.credential_service._TOKEN_DISPATCH`` — the
      single-secret-field channels (devto, hackmd, mataroa, qiita): the one
      field *is* the secret.
    - ``..._TOKEN_FIELDS_DISPATCH`` — the mixed channels (tumblr,
      wordpresscom, ghpages, gitlabpages, hatena, zenn), curated per
      platform via ``_NON_SECRET_TOKEN_FIELDS`` so identifier fields
      (hatena_id, blog_id, blog_identifier, site, github_repo, username)
      are excluded rather than treated as secret.
    - ``backlink_publisher._util.secrets.load_frw_token()`` — the FRW
      image-gen API key.
    - ``webui_app.services.settings_service.load_llm_settings()`` — the LLM
      ``api_key`` / ``image_gen_api_key``.

    Re-reads from disk on every call (no caching) so a config change (or a
    test that rebinds ``BACKLINK_PUBLISHER_CONFIG_DIR``) is reflected
    immediately rather than through a stale snapshot.
    """
    values: set[str] = set()

    try:
        from backlink_publisher.config import _config_dir
        config_dir = _config_dir()
    except Exception:
        config_dir = None

    if config_dir is not None:
        try:
            from webui_app.services import credential_service
        except Exception:
            credential_service = None  # type: ignore[assignment]

        if credential_service is not None:
            for _channel, entry in credential_service._TOKEN_DISPATCH.items():
                try:
                    _save_fn, basename, field_key = entry
                    _collect_json_field_values(config_dir / basename, (field_key,), values)
                except Exception:
                    continue

            for channel, entry in credential_service._TOKEN_FIELDS_DISPATCH.items():
                try:
                    _save_fn, basename, field_names = entry
                    non_secret = _NON_SECRET_TOKEN_FIELDS.get(channel, frozenset())
                    secret_fields = [f for f in field_names if f not in non_secret]
                    _collect_json_field_values(config_dir / basename, secret_fields, values)
                except Exception:
                    continue

    try:
        from backlink_publisher._util.secrets import load_frw_token
        frw_key = load_frw_token()
        if frw_key:
            values.add(frw_key)
    except Exception:
        pass

    try:
        from webui_app.services.settings_service import load_llm_settings
        llm_settings = load_llm_settings()
        for field_name in ("api_key", "image_gen_api_key"):
            v = llm_settings.get(field_name)
            if isinstance(v, str) and v:
                values.add(v)
    except Exception:
        pass

    return frozenset(v for v in values if isinstance(v, str) and v)
