"""
Hermes Web UI -- ONE fail-closed public-reference decision for share snapshots.

``api/shares.py`` used to apply its privacy guard only while substituting
canonical ``MEDIA:`` tokens, so every OTHER URL-bearing shape in message
content reached the public share page unexamined. The share page loads
``static/ui.js`` and ``static/share.js`` calls ``renderMd()``, and that
renderer has several sinks that turn message text into a LIVE URL:

* ``_inlineMediaHtmlForRef()`` -- restores a stashed ``MEDIA:`` token. A local
  path becomes ``api/media?path=...``; a loopback http(s) ref is retargeted at
  ``document.baseURI``.
* ``_mdImageHtml()`` -- the outer AND inline ``![alt](url)`` passes. A
  ``file://`` target is routed through ``_inlineMediaHtmlForRef()`` (so it too
  becomes ``api/media?path=...``); an http(s) target becomes a direct
  ``<img src>``.
* ``_markdownHref()`` -- the outer AND inline ``[label](url)`` passes. A
  ``file://`` target becomes ``api/media?path=...&inline=1``.
* the autolink pass -- a bare ``http(s)://`` run in prose becomes ``<a href>``.
* ``_tag()`` -- a raw ``<img src="api/media?...">`` survives sanitisation,
  because ``_isSafeUrl()`` allows an ``api/`` relative src for images.

Each of those makes an ANONYMOUS viewer's browser issue an authenticated
same-origin request against our own ``/api/media`` route, or round-trips a host
filesystem path into a public snapshot. So the decision cannot live inside the
``MEDIA:`` substitution: it has to cover every token the client will turn into
a URL, and it has to be taken BEFORE publication.

Two properties this module exists to preserve:

1. **One pass, whole tokens.** :data:`SHARE_REFERENCE_RE` is a single
   alternation and every branch matches a COMPLETE parser-equivalent token.
   Callers replace the whole matched span or preserve it byte-for-byte, never
   part of it. ``re.sub`` then resumes AFTER the span, so the scanner can never
   restart inside a token it already refused -- the bug that made an external
   URL's tail rewritable when the old pattern rejected by non-match.
2. **Fail closed.** An unparseable value, an empty host, a value still
   percent-decoding at the bound, or a nested absolute/relative URL start in
   the path, query, or fragment all mean "placeholder the token".
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from api.helpers import (
    _LOCAL_TARGET_MARKERS,
    external_media_url_hides_local_target,
    media_token_pattern,
)

# Number of percent-decode rounds a probe gets before we stop and judge it.
# A single decode misses `%254d` (`%4d` after one pass, `M` after two), and an
# unbounded loop is a DoS on crafted input.
_DECODE_ROUNDS = 3

_MEDIA_KEYWORD = "MEDIA:"


def decode_probe_bounded(value: str, *, rounds: int = _DECODE_ROUNDS) -> tuple[str, bool]:
    """Percent-decode *value* up to *rounds* times; report whether it settled.

    Returns ``(decoded, still_changing)``. ``still_changing`` is ``True`` when
    the value was STILL mutating when the bound was reached.

    ``api.helpers._decode_url_component_bounded`` returns only the decoded
    string, so a value that never settles is indistinguishable there from one
    that decoded cleanly to something harmless -- and the caller then accepts
    it. At a publication boundary that is a hole, so this variant hands the
    verdict back to the caller instead of hiding it.
    """
    current = str(value or "")
    for _ in range(max(0, rounds)):
        nxt = unquote(current)
        if nxt == current:
            return current, False
        current = nxt
    return current, unquote(current) != current


# Nested URL starts that mean "this value leads back to a local or
# authenticated target". A superset of the marker tuple in api/helpers.py,
# imported rather than restated so the two can never drift:
#
# * ``http://`` / ``https://`` -- a SECOND absolute URL inside the path, query,
#   or fragment of the first. The token we are judging already carries its own
#   scheme, so another one is smuggled, not structural.
# * ``api/media`` -- the slash-less spelling of our own route, which is exactly
#   the form ``_isSafeUrl()`` accepts as an image src.
#
# The netloc is deliberately NOT probed, so an ordinary public CDN host is never
# refused for its name alone.
_NESTED_START_MARKERS: tuple[str, ...] = tuple(
    dict.fromkeys(_LOCAL_TARGET_MARKERS + ("http://", "https://", "api/media"))
)

_FILE_SCHEME_RE = re.compile(r"(?i)^file://")
_HTTP_SCHEME_RE = re.compile(r"(?i)^https?://")
# Our own media route as a RELATIVE URL. A `?` is required so the words
# "api/media" in ordinary prose are not mistaken for a URL; the dangerous shape
# always carries a query (`api/media?path=...`).
_API_MEDIA_RE = re.compile(r"(?i)^/?api/media\?")


def public_reference_hides_local_target(value: str) -> bool:
    """True when *value* must NOT be published into a public share snapshot.

    Covers every shape :data:`SHARE_REFERENCE_RE` can match, and answers for
    the WHOLE value across path, query, and fragment.

    Refused:

    * ``file://`` -- absolute and un-scoped, so it can name anything on the
      host. Never embeddable either (``_resolve_against_roots`` rejects it), so
      preserving it would only disclose a path.
    * a relative ``api/media?…`` / ``/api/media?…`` -- our authenticated route.
    * an http(s) URL that :func:`api.helpers.external_media_url_hides_local_target`
      already refuses (private host, empty host, unparseable, or a marker in
      the decoded path/query/fragment).
    * an http(s) URL whose probe is still percent-decoding at the bound.
    * an http(s) URL carrying a nested absolute or relative URL start.
    * anything else -- a shape we cannot reason about is refused, not accepted.

    Preserved: an ordinary public http(s) URL, including one with a harmless
    query string. Over-blocking a genuine public asset is also a failure.
    """
    v = str(value or "").strip()
    if not v:
        return True
    if _FILE_SCHEME_RE.match(v) or _API_MEDIA_RE.match(v):
        return True
    if not _HTTP_SCHEME_RE.match(v):
        # Not a shape this module classifies -- fail closed.
        return True
    # The host/marker half of the decision, reused verbatim so the server guard
    # and its client twin in static/ui.js keep agreeing on those rows.
    if external_media_url_hides_local_target(v):
        return True
    try:
        parts = urlsplit(v)
    except ValueError:
        return True
    probe = "".join((
        parts.path or "",
        "?" + parts.query if parts.query else "",
        "#" + parts.fragment if parts.fragment else "",
    ))
    decoded, still_changing = decode_probe_bounded(probe)
    if still_changing:
        return True
    lowered = decoded.lower()
    return any(marker in lowered for marker in _NESTED_START_MARKERS)


# ── The tokenizer ────────────────────────────────────────────────────────────
# One alternation over every shape the share renderer turns into a live URL.
# Each branch matches a COMPLETE token, so a caller's replace-or-preserve
# decision always covers the whole span.
#
# Character classes mirror the client regexes so the server and the renderer
# tokenize the same text the same way:
#   _URL_RUN      -> the autolink class in renderMd()
#   _MD_IMAGE_URL -> the `[^)]+` target class of the ![alt](url) passes
#   _MD_LINK_URL  -> the `[^\s)]+` target class of the [label](url) passes
# `\n` is additionally excluded from the Markdown target classes: a newline
# never appears inside a real target and excluding it keeps one refusal from
# swallowing the following line.
_URL_RUN = r"[^\s<>\"')\]]+"
_MD_IMAGE_URL = r"[^)\n]+"
_MD_LINK_URL = r"[^\s)\n]+"
# Only the schemes whose Markdown target a client sink turns into a local or
# authenticated URL. `data:image/` is validated separately by
# _isSafeDataImageUri() and carries no host path; `workspace://`, `session://`,
# `mailto:`, `tel:` and `message:` produce no fetchable local file URL.
_MD_SCHEMES = r"(?i:https?://|file://)"
# Same, plus the relative spelling of our own media route, so a Markdown
# image/link whose target is `/api/media?…` is refused as ONE whole token
# instead of leaving `![x](` and `)` behind as orphaned prose.
_MD_TARGET_STARTS = r"(?i:https?://|file://|/?api/media\?)"

SHARE_REFERENCE_PATTERN = (
    # 1. Canonical MEDIA: token. First so `MEDIA:https://…/MEDIA:/etc/x.png`
    #    stays ONE token instead of being re-entered at the nested keyword.
    r"(?P<media>" + media_token_pattern(extra_exclude=">") + r")"
    # 2. Markdown image, outer and inline passes.
    r"|(?P<mdimg>!\[[^\]]*\]\((?P<imgurl>" + _MD_TARGET_STARTS + _MD_IMAGE_URL + r")\))"
    # 3. Markdown link, outer and inline passes.
    r"|(?P<mdlink>\[[^\]]+\]\((?P<linkurl>" + _MD_TARGET_STARTS + _MD_LINK_URL + r")\))"
    # 4. Bare absolute URL in prose (autolink sink, and path disclosure for
    #    file://, which no sink linkifies but which still names a host file).
    r"|(?P<bare>" + _MD_SCHEMES + _URL_RUN + r")"
    # 5. Relative reference to our own authenticated media route. Reachable as
    #    a live image src through _isSafeUrl()/_tag().
    r"|(?P<apimedia>/?(?i:api/media)\?" + _URL_RUN + r")"
)

SHARE_REFERENCE_RE = re.compile(SHARE_REFERENCE_PATTERN)


def media_ref_of_match(match: re.Match) -> str:
    """Return the raw (still quoted) ref of a ``media`` branch match.

    The ``media`` branch wraps :func:`api.helpers.media_token_pattern`, whose
    own capture group is unnamed and whose index therefore depends on that
    helper's internals. Slice the matched TEXT instead: it always begins with
    the ``MEDIA:`` keyword and everything after it is the capture.
    """
    span = match.group("media") or ""
    return span[len(_MEDIA_KEYWORD):] if span.startswith(_MEDIA_KEYWORD) else span


def url_of_match(match: re.Match) -> str:
    """Return the URL a non-``media`` branch match carries.

    For the Markdown branches that is the target inside the parentheses; for
    the bare and relative branches the whole span IS the URL.
    """
    for name in ("imgurl", "linkurl"):
        value = match.group(name)
        if value is not None:
            return value
    return match.group(0)
