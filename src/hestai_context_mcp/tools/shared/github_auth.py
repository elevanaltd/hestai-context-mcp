"""Shared GitHub token resolution -- single source of truth.

This module is the one audited code path for resolving a GitHub token across
the governance tools. It was extracted to remove a CIV-flagged duplication:
``governance.linker`` and ``submit_review`` each carried byte-identical copies
of the three-tier lookup, the 5-second timeout constant, and the token-shape
regex. Both now import from here.

Security invariant: the resolved value is opaque. Callers MUST NOT log it,
embed it in error messages, or include it in any structured response. Funneling
token handling through this single helper is precisely what makes that
invariant auditable.
"""

import os
import re
import subprocess

# Timeout for the ``gh auth token`` precondition gate. Short by design: the
# call is a local CLI invocation, not a network request, and a hang here would
# block every caller until an unrelated global timeout fires.
GH_AUTH_TIMEOUT_SECONDS = 5

# Auth error message lists ALL three lookup tiers so operators can diagnose
# which one needs configuring. The token value itself is NEVER included in this
# message (security invariant -- see resolve_github_token).
AUTH_ERROR_MESSAGE = (
    "GitHub credentials not found. Set GITHUB_TOKEN or GH_TOKEN environment "
    "variable, or authenticate the gh CLI (so `gh auth token` returns a token)."
)

# Token-shape sanity guard for the ``gh auth token`` tier (issue #34 CE
# rework). The aim is NOT cryptographic validation -- it is to reject
# obviously-malformed payloads (error text echoed to stdout, HTML wrappers,
# multi-line junk) so the failure-mode contract collapses inside
# resolve_github_token rather than propagating to the GitHub API. PERMISSIVE on
# accepts: a false negative breaks the user's workflow on a valid credential.
#
# Accepted shapes:
#   - Modern gh prefixes (per GitHub's published taxonomy, 2021-04+):
#     ghp_ (personal), gho_ (OAuth), ghu_ (user-to-server),
#     ghs_ (server-to-server), ghr_ (refresh) followed by >=20
#     [A-Za-z0-9_] characters.
#   - Fine-grained personal access tokens (2022+): github_pat_ prefix followed
#     by >=20 [A-Za-z0-9_] characters. Added per cubic P1 finding on PR #35 --
#     without this alternation, ``gh auth token`` returning a valid
#     fine-grained PAT would be silently rejected.
#   - Classic 40-char lowercase hex personal access tokens for accounts that
#     have not rotated since the prefix scheme rolled out.
#
# Compiled once at import time to avoid per-call recompilation.
_TOKEN_SHAPE_RE = re.compile(
    r"^(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[a-f0-9]{40})$"
)


def resolve_github_token() -> str | None:
    """Resolve a GitHub token via three-tier lookup.

    Lookup order (first hit wins):
      1. ``GITHUB_TOKEN`` environment variable.
      2. ``GH_TOKEN`` environment variable.
      3. ``gh auth token`` subprocess (5 s timeout) -- uses the operator's
         authenticated ``gh`` CLI keyring. The MCP server runs as a stdio
         subprocess and does NOT inherit gh keyring credentials, so this tier
         is what makes the tools usable for agents who have not exported a
         token into the launch environment. (Issue #34)

    Returns:
        The resolved token string, or ``None`` if no tier supplied a token.

    Security:
        The returned value is opaque -- callers MUST NOT log it, embed it in
        error messages, or include it in any structured response. This helper
        exists precisely so that token handling is funneled through a single
        audited code path.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token

    # Tier 3: ``gh auth token``. Catch ``Exception`` so any failure mode here
    # (gh missing -> FileNotFoundError, gh hung -> TimeoutExpired, gh corrupted
    # -> OSError, anything else -> unhandled) becomes a clean None return rather
    # than an exception that would crash the stdio MCP server. ``BaseException``
    # is intentionally NOT caught -- a KeyboardInterrupt or SystemExit during
    # this call should propagate.
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=GH_AUTH_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return None

    if result.returncode != 0:
        return None

    candidate = (result.stdout or "").strip()
    if not candidate:
        return None

    # Shape sanity guard (CE rework): reject malformed payloads BEFORE they
    # reach the GitHub API. Silent rejection -- the candidate is NEVER logged or
    # surfaced (security invariant).
    if not _TOKEN_SHAPE_RE.match(candidate):
        return None

    return candidate
