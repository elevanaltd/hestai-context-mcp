"""Shared HTTP-response parsing for ``gh api --include`` output.

Both ``submit_review`` (posting the verdict comment) and
``review_gate_retrigger`` (re-triggering the gate) shell out to ``gh api
--include`` and need to parse the resulting raw HTTP response into a status
code, headers, and body. This was duplicated (rework #2, PR #148 finding 6
-- CRS + CIV): CIV pointed at the exact precedent to follow --
``_resolve_github_token`` was de-duplicated into
``tools/shared/github_auth.py`` after an earlier CIV review flagged the
same class of copy. This module is that single source of truth for
HTTP-response parsing; ``review_gate_retrigger`` simply discards the
headers it doesn't need.
"""

from __future__ import annotations


def parse_gh_api_response(raw_output: str) -> tuple[int, dict[str, str], str]:
    """Parse ``gh api --include`` output into (status_code, headers, body).

    Args:
        raw_output: Raw HTTP response text from ``gh api --include``.

    Returns:
        Tuple of (status_code, headers_dict, body_string). Header keys are
        lowercased for consistent access. On any parse failure (missing
        header/body separator, malformed status line, non-integer status
        code), returns ``(0, {}, raw_output)`` so callers can treat status
        0 uniformly as "could not parse".
    """
    if "\r\n\r\n" in raw_output:
        parts = raw_output.split("\r\n\r\n", 1)
        line_separator = "\r\n"
    elif "\n\n" in raw_output:
        parts = raw_output.split("\n\n", 1)
        line_separator = "\n"
    else:
        return 0, {}, raw_output

    if len(parts) != 2:
        return 0, {}, raw_output

    header_section, body = parts
    lines = header_section.split(line_separator)

    status_line = lines[0]
    status_parts = status_line.split()
    if len(status_parts) < 2:
        return 0, {}, raw_output

    try:
        status_code = int(status_parts[1])
    except (ValueError, IndexError):
        return 0, {}, raw_output

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key.lower()] = value

    return status_code, headers, body
