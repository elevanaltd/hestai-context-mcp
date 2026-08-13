"""Unit tests for the shared ``gh api --include`` response parser.

Extracted (rework #2, PR #148 finding 6 -- CRS + CIV) from two duplicated
copies: ``submit_review._parse_http_response`` and
``review_gate_retrigger._parse_http_response`` (a header-dropping variant).
CIV pointed at the exact precedent to follow: ``_resolve_github_token`` was
de-duplicated into ``tools/shared/github_auth.py`` after an earlier CIV
review flagged the same class of copy. This module is that single source
of truth for HTTP-response parsing; ``review_gate_retrigger`` now simply
discards the headers it doesn't need.
"""

from __future__ import annotations

from hestai_context_mcp.tools.shared.gh_http import parse_gh_api_response


class TestParseGhApiResponse:
    def test_parses_status_headers_and_body_crlf(self) -> None:
        raw = (
            "HTTP/2 201 Created\r\n"
            "content-type: application/json\r\n"
            "x-ratelimit-remaining: 42\r\n"
            "\r\n"
            '{"html_url": "https://github.com/owner/repo/pull/1#issuecomment-1"}'
        )
        status, headers, body = parse_gh_api_response(raw)

        assert status == 201
        assert headers["content-type"] == "application/json"
        assert headers["x-ratelimit-remaining"] == "42"
        assert body == '{"html_url": "https://github.com/owner/repo/pull/1#issuecomment-1"}'

    def test_parses_status_headers_and_body_lf(self) -> None:
        raw = "HTTP/2 200 OK\ncontent-type: application/json\n\n{}"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 200
        assert headers["content-type"] == "application/json"
        assert body == "{}"

    def test_header_keys_lowercased(self) -> None:
        raw = "HTTP/2 200 OK\nX-RateLimit-Remaining: 10\n\n{}"
        _status, headers, _body = parse_gh_api_response(raw)

        assert headers["x-ratelimit-remaining"] == "10"
        assert "X-RateLimit-Remaining" not in headers

    def test_no_header_body_separator_returns_zero_status(self) -> None:
        raw = "not a valid HTTP response at all"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 0
        assert headers == {}
        assert body == raw

    def test_malformed_status_line_missing_code_returns_zero_status(self) -> None:
        raw = "HTTP/2\n\n{}"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 0
        assert headers == {}
        assert body == raw

    def test_non_integer_status_code_returns_zero_status(self) -> None:
        raw = "HTTP/2 NOTANUMBER Created\n\n{}"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 0
        assert headers == {}
        assert body == raw

    def test_error_response_body_without_headers_still_parses(self) -> None:
        raw = "HTTP/2 404 Not Found\n\n{}"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 404
        assert headers == {}
        assert body == "{}"

    def test_header_line_without_colon_space_is_skipped(self) -> None:
        raw = "HTTP/2 200 OK\nnot-a-real-header-line\ncontent-type: application/json\n\n{}"
        _status, headers, _body = parse_gh_api_response(raw)

        assert headers == {"content-type": "application/json"}

    def test_empty_body_after_headers(self) -> None:
        raw = "HTTP/2 204 No Content\ncontent-type: application/json\n\n"
        status, headers, body = parse_gh_api_response(raw)

        assert status == 204
        assert headers["content-type"] == "application/json"
        assert body == ""
