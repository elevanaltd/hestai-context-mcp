"""RedactionEngine patterns must be line-bounded (#256, PROD::I2).

Defects pinned here:

1. ``db_password`` was not line-bounded. Its user part ``[^:]+`` and its
   "last @" lookahead ``(?=[^@]*$)`` crossed newlines. As a result, in
   multi-line content (the whole-file archive path ``copy_and_redact``), a
   connection-string password survived whenever a later line held an ``@``.
   A URL on one line plus an ``@`` on a later line also turned unrelated
   text into a fake password marker.
2. A private key with a BEGIN line and no END line (truncated output)
   matched no pattern, so the key material was archived in clear.

SYNTHETIC DATA ONLY: every credential-shaped value below is FAKE and is
assembled at runtime from parts, so no contiguous credential literal exists
in this file (secret-scanner safe). Assertion messages never echo values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.redaction import RedactionEngine

pytestmark = [pytest.mark.unit, pytest.mark.security]

_DASHES = "-" * 5
_PW_MARKER = "[REDACTED_" + "PASSWORD]"
_KEY_MARKER = "[REDACTED_" + "PRIVATE_KEY]"


def _fake_password(tag: str) -> str:
    """A FAKE password, assembled from parts."""
    return "fk" + tag + "Pw" + "x9" + "Qz"


def _db_uri(password: str, scheme: str = "postgresql", host: str = "db.example.test") -> str:
    """A FAKE scheme://user:password@host URI, assembled from parts."""
    return scheme + "://" + "svc" + "user" + ":" + password + "@" + host + ":5432/app"


def _email(local: str = "alice") -> str:
    """A plain (non-secret) email address, assembled from parts."""
    return local + "@" + "example.org"


def _pem_line(edge: str, kind: str = "RSA ") -> str:
    """A PEM armour line (``edge`` is BEGIN or END), assembled from parts."""
    return _DASHES + edge + " " + kind + "PRIVATE" + " KEY" + _DASHES


def _fake_key_body(tag: str) -> list[str]:
    """FAKE base64-shaped key body lines (not a real key), assembled from parts."""
    return [
        "MIIE" + "FAKE" + tag + "A" * 24,
        "FAKE" + tag + "B" * 28 + "=",
    ]


# ---------------------------------------------------------------------------
# (a) password redacted when a LATER line contains '@'
# ---------------------------------------------------------------------------


class TestDbPasswordLaterAtOnAnotherLine:
    """A later '@' on another line must not rescue the password (#256 defect 1)."""

    def test_redact_content_password_redacted_when_later_line_has_at(self) -> None:
        pw = _fake_password("A1")
        text = "conn " + _db_uri(pw) + "\nnotes\nmail " + _email() + "\n"
        out = RedactionEngine.redact_content(text)
        assert pw not in out, "connection-string password leaked"
        assert _PW_MARKER in out

    def test_redact_reports_db_password_type_when_later_line_has_at(self) -> None:
        pw = _fake_password("A2")
        text = _db_uri(pw) + "\n" + _email() + "\n"
        result = RedactionEngine().redact(text)
        assert pw not in result.redacted_text, "connection-string password leaked"
        assert "db_password" in result.redacted_types
        assert result.redaction_count == 1

    def test_every_uri_line_redacted_when_several_lines_hold_uris(self) -> None:
        pw1, pw2 = _fake_password("A3"), _fake_password("A4")
        text = _db_uri(pw1) + "\n" + _db_uri(pw2, scheme="mysql") + "\n"
        out = RedactionEngine.redact_content(text)
        assert pw1 not in out, "first-line password leaked"
        assert pw2 not in out, "second-line password leaked"
        assert out.count(_PW_MARKER) == 2

    def test_crlf_line_endings_password_redacted(self) -> None:
        pw = _fake_password("A5")
        text = _db_uri(pw) + "\r\nmail " + _email() + "\r\n"
        out = RedactionEngine.redact_content(text)
        assert pw not in out, "connection-string password leaked"
        assert _email() in out


# ---------------------------------------------------------------------------
# (b) no over-redaction across lines
# ---------------------------------------------------------------------------


class TestNoCrossLineOverRedaction:
    """A URL line plus a later email line must stay as it is (#256 defect 1).

    Scope: physical lines, i.e. real '\\n' (one JSONL record per line). An
    escaped newline inside one JSON string is part of the same physical line
    and is NOT covered here; that same-line behaviour is unchanged by #256.
    """

    def test_url_line_then_email_line_unchanged(self) -> None:
        text = "see https://example.com/docs\ncontact: " + _email("bob") + "\n"
        result = RedactionEngine().redact(text)
        assert result.redacted_text == text
        assert result.redaction_count == 0

    def test_password_line_then_email_line_keeps_email(self) -> None:
        pw = _fake_password("B1")
        text = _db_uri(pw) + "\nreply to " + _email("carol") + "\n"
        out = RedactionEngine.redact_content(text)
        assert pw not in out, "connection-string password leaked"
        assert "reply to " + _email("carol") in out
        assert "db.example.test:5432/app" in out


# ---------------------------------------------------------------------------
# (c) same-line behaviour preserved (the existing suite also runs unchanged)
# ---------------------------------------------------------------------------


class TestSameLineBehaviourPreserved:
    """Single-line inputs must redact exactly as before the fix."""

    def test_single_line_uri_output_shape_unchanged(self) -> None:
        pw = _fake_password("C1")
        text = _db_uri(pw)
        expected = "postgresql://svcuser:" + _PW_MARKER + "@db.example.test:5432/app"
        assert RedactionEngine.redact_content(text) == expected

    def test_single_line_password_containing_at_redacted_to_last_at(self) -> None:
        pw = "fk" + "@" + "Pw" + "C2"
        text = _db_uri(pw)
        out = RedactionEngine.redact_content(text)
        assert pw not in out, "connection-string password leaked"
        assert out.endswith("@db.example.test:5432/app")


# ---------------------------------------------------------------------------
# (d) unterminated private key: fail safe, redact BEGIN to end of content
# ---------------------------------------------------------------------------


class TestUnterminatedPrivateKey:
    """BEGIN with no END must still hide the key material (#256 defect 2)."""

    def test_unterminated_key_body_redacted(self) -> None:
        body = _fake_key_body("D1")
        text = "prefix\n" + _pem_line("BEGIN") + "\n" + "\n".join(body) + "\n"
        result = RedactionEngine().redact(text)
        for line in body:
            assert line not in result.redacted_text, "key material leaked"
        assert _KEY_MARKER in result.redacted_text
        assert "private_key" in result.redacted_types
        assert result.redacted_text.startswith("prefix\n")

    def test_unterminated_key_redacts_to_end_of_content(self) -> None:
        body = _fake_key_body("D2")
        text = _pem_line("BEGIN", kind="") + "\n" + "\n".join(body) + "\ntrailing words\n"
        out = RedactionEngine.redact_content(text)
        assert out == _KEY_MARKER

    def test_unterminated_key_on_one_jsonl_record_line(self) -> None:
        body = _fake_key_body("D3")
        record = '{"content": "' + _pem_line("BEGIN") + "\\n" + "\\n".join(body) + '"}'
        out = RedactionEngine.redact_content(record + "\n")
        for line in body:
            assert line not in out, "key material leaked"
        assert _KEY_MARKER in out

    def test_public_key_without_end_not_redacted(self) -> None:
        body = _fake_key_body("D4")
        text = _DASHES + "BEGIN PUBLIC" + " KEY" + _DASHES + "\n" + "\n".join(body) + "\n"
        result = RedactionEngine().redact(text)
        assert result.redacted_text == text
        assert result.redaction_count == 0


# ---------------------------------------------------------------------------
# (e) terminated BEGIN...END unchanged
# ---------------------------------------------------------------------------


class TestTerminatedPrivateKeyUnchanged:
    """A complete block is still replaced in place; surrounding text survives."""

    def test_complete_block_redacted_in_place(self) -> None:
        body = _fake_key_body("E1")
        block = _pem_line("BEGIN") + "\n" + "\n".join(body) + "\n" + _pem_line("END")
        text = "before\n" + block + "\nafter\n"
        out = RedactionEngine.redact_content(text)
        assert out == "before\n" + _KEY_MARKER + "\nafter\n"

    def test_complete_block_then_unterminated_block(self) -> None:
        body1, body2 = _fake_key_body("E2"), _fake_key_body("E3")
        block1 = _pem_line("BEGIN") + "\n" + "\n".join(body1) + "\n" + _pem_line("END")
        tail = _pem_line("BEGIN", kind="EC ") + "\n" + "\n".join(body2) + "\n"
        text = "a\n" + block1 + "\nmiddle\n" + tail
        out = RedactionEngine.redact_content(text)
        assert out == "a\n" + _KEY_MARKER + "\nmiddle\n" + _KEY_MARKER


# ---------------------------------------------------------------------------
# (f) end-to-end through copy_and_redact (the archive path, whole-file unit)
# ---------------------------------------------------------------------------


def _jsonl(*contents: str) -> str:
    return "".join('{"role": "user", "content": "' + c + '"}\n' for c in contents)


class TestCopyAndRedactEndToEnd:
    """The archive path reads the whole file as one buffer; it must be safe."""

    def test_archive_password_redacted_when_later_record_has_at(self, tmp_path: Path) -> None:
        pw = _fake_password("F1")
        src, dst = tmp_path / "t.jsonl", tmp_path / "t-redacted.jsonl"
        src.write_text(
            _jsonl("use " + _db_uri(pw), "ok", "ping " + _email("dave")), encoding="utf-8"
        )
        RedactionEngine.copy_and_redact(src, dst)
        out = dst.read_text(encoding="utf-8")
        assert pw not in out, "archive kept a connection-string password"
        assert _PW_MARKER in out
        assert "ping " + _email("dave") in out

    def test_archive_url_record_then_email_record_unchanged(self, tmp_path: Path) -> None:
        src, dst = tmp_path / "u.jsonl", tmp_path / "u-redacted.jsonl"
        content = _jsonl("docs at https://example.com/x", "mail " + _email("erin"))
        src.write_text(content, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        assert dst.read_text(encoding="utf-8") == content

    def test_archive_unterminated_key_redacted(self, tmp_path: Path) -> None:
        body = _fake_key_body("F2")
        src, dst = tmp_path / "k.jsonl", tmp_path / "k-redacted.jsonl"
        src.write_text(
            _jsonl("first", "key: " + _pem_line("BEGIN") + "\\n" + "\\n".join(body), "later"),
            encoding="utf-8",
        )
        RedactionEngine.copy_and_redact(src, dst)
        out = dst.read_text(encoding="utf-8")
        for line in body:
            assert line not in out, "archive kept private key material"
        assert _KEY_MARKER in out
        assert out.startswith(_jsonl("first"))

    def test_archive_key_split_across_records_redacted(self, tmp_path: Path) -> None:
        body = _fake_key_body("F3")
        src, dst = tmp_path / "s.jsonl", tmp_path / "s-redacted.jsonl"
        src.write_text(
            _jsonl(
                "start " + _pem_line("BEGIN"),
                "\\n".join(body),
                _pem_line("END") + " done",
                "after",
            ),
            encoding="utf-8",
        )
        RedactionEngine.copy_and_redact(src, dst)
        out = dst.read_text(encoding="utf-8")
        for line in body:
            assert line not in out, "archive kept private key material"
        assert _KEY_MARKER in out
        assert out.endswith(_jsonl("after"))


# ---------------------------------------------------------------------------
# (g) every line separator Python honours bounds db_password (#261 round 1)
# ---------------------------------------------------------------------------

#: Every boundary ``str.splitlines()`` honours except '\n' (covered above) and
#: '\r\n' (covered by the CRLF test). A lone '\r' or U+2028 inside a record
#: must end the "line" exactly like '\n' does.
_OTHER_SEPARATORS = {
    "CR": "\r",
    "VT": "\x0b",
    "FF": "\x0c",
    "FS": "\x1c",
    "GS": "\x1d",
    "RS": "\x1e",
    "NEL": "\x85",
    "LS": " ",
    "PS": " ",
}


class TestEverySeparatorBoundsDbPassword:
    """db_password must not run past any line separator (#261 CE + TMG)."""

    @pytest.mark.parametrize("sep", _OTHER_SEPARATORS.values(), ids=_OTHER_SEPARATORS.keys())
    def test_password_then_separator_then_email(self, sep: str) -> None:
        pw = _fake_password("G1")
        text = _db_uri(pw) + sep + "contact " + _email() + sep
        out = RedactionEngine.redact_content(text)
        expected = (
            "postgresql://svcuser:"
            + _PW_MARKER
            + "@db.example.test:5432/app"
            + sep
            + "contact "
            + _email()
            + sep
        )
        assert out == expected

    @pytest.mark.parametrize("sep", _OTHER_SEPARATORS.values(), ids=_OTHER_SEPARATORS.keys())
    def test_url_then_separator_then_email_unchanged(self, sep: str) -> None:
        text = "see https://example.com/docs" + sep + "contact: " + _email("bob") + sep
        result = RedactionEngine().redact(text)
        assert result.redacted_text == text
        assert result.redaction_count == 0

    @pytest.mark.parametrize("sep", _OTHER_SEPARATORS.values(), ids=_OTHER_SEPARATORS.keys())
    def test_password_with_at_then_separator_then_email(self, sep: str) -> None:
        pw = "fk" + "@" + "Pw" + "G2"
        text = _db_uri(pw) + sep + _email() + sep
        out = RedactionEngine.redact_content(text)
        assert "Pw" + "G2" not in out, "password fragment leaked"
        assert out.endswith("@db.example.test:5432/app" + sep + _email() + sep)

    @pytest.mark.parametrize("sep", [" ", " ", "\x85"], ids=["LS", "PS", "NEL"])
    def test_archive_password_record_with_separator_keeps_email(
        self, tmp_path: Path, sep: str
    ) -> None:
        pw = _fake_password("G3")
        src, dst = tmp_path / "g.jsonl", tmp_path / "g-redacted.jsonl"
        src.write_text(_jsonl("use " + _db_uri(pw) + sep + "mail " + _email()), encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        out = dst.read_text(encoding="utf-8")
        assert pw not in out, "archive kept a connection-string password"
        assert sep + "mail " + _email() in out


# ---------------------------------------------------------------------------
# (h) private-key header rule: case-insensitive, all key kinds (#261 round 1)
# ---------------------------------------------------------------------------


def _armour(edge: str, kind: str, dashes: str = _DASHES, pad: str = "") -> str:
    """An armour line built from parts: ``<dashes><pad><edge> <kind><pad><dashes>``."""
    return dashes + pad + edge + " " + kind + pad + dashes


#: (id, BEGIN line, END line) for private-key armours, built from parts.
_KEY_ARMOURS = [
    ("lower", _armour("begin", "rsa private" + " key"), _armour("end", "rsa private" + " key")),
    ("mixed", _armour("Begin", "Rsa Private" + " Key"), _armour("End", "Rsa Private" + " Key")),
    (
        "openssh",
        _armour("BEGIN", "OPENSSH PRIVATE" + " KEY"),
        _armour("END", "OPENSSH PRIVATE" + " KEY"),
    ),
    (
        "encrypted",
        _armour("BEGIN", "ENCRYPTED PRIVATE" + " KEY"),
        _armour("END", "ENCRYPTED PRIVATE" + " KEY"),
    ),
    ("dsa", _armour("BEGIN", "DSA PRIVATE" + " KEY"), _armour("END", "DSA PRIVATE" + " KEY")),
    (
        "pgp",
        _armour("BEGIN", "PGP PRIVATE" + " KEY BLOCK"),
        _armour("END", "PGP PRIVATE" + " KEY BLOCK"),
    ),
    (
        "pgp_lower",
        _armour("begin", "pgp private" + " key block"),
        _armour("end", "pgp private" + " key block"),
    ),
    (
        "ssh2",
        _armour("BEGIN", "SSH2 ENCRYPTED PRIVATE" + " KEY", dashes="-" * 4, pad=" "),
        _armour("END", "SSH2 ENCRYPTED PRIVATE" + " KEY", dashes="-" * 4, pad=" "),
    ),
]
_KEY_IDS = [a[0] for a in _KEY_ARMOURS]


class TestPrivateKeyHeaderRule:
    """Any case and any private-key kind must be caught, terminated or not."""

    @pytest.mark.parametrize(("name", "begin", "end"), _KEY_ARMOURS, ids=_KEY_IDS)
    def test_terminated_block_redacted_in_place(self, name: str, begin: str, end: str) -> None:
        body = _fake_key_body("H1")
        text = "before\n" + begin + "\n" + "\n".join(body) + "\n" + end + "\nafter\n"
        out = RedactionEngine.redact_content(text)
        assert out == "before\n" + _KEY_MARKER + "\nafter\n"

    @pytest.mark.parametrize(("name", "begin", "end"), _KEY_ARMOURS, ids=_KEY_IDS)
    def test_unterminated_block_redacted(self, name: str, begin: str, end: str) -> None:
        body = _fake_key_body("H2")
        text = "before\n" + begin + "\n" + "\n".join(body) + "\n"
        result = RedactionEngine().redact(text)
        assert result.redacted_text == "before\n" + _KEY_MARKER
        assert "private_key" in result.redacted_types

    @pytest.mark.parametrize(("name", "begin", "end"), _KEY_ARMOURS, ids=_KEY_IDS)
    def test_archive_unterminated_block_redacted(
        self, tmp_path: Path, name: str, begin: str, end: str
    ) -> None:
        body = _fake_key_body("H3")
        src, dst = tmp_path / "h.jsonl", tmp_path / "h-redacted.jsonl"
        src.write_text(_jsonl("first", begin + "\\n" + "\\n".join(body)), encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        out = dst.read_text(encoding="utf-8")
        for line in body:
            assert line not in out, "archive kept private key material"
        assert out.startswith(_jsonl("first"))

    @pytest.mark.parametrize(
        "begin",
        [
            _armour("begin", "public" + " key"),
            _armour("BEGIN", "PGP PUBLIC" + " KEY BLOCK"),
            _armour("BEGIN", "CERTIFICATE"),
        ],
        ids=["public_lower", "pgp_public", "certificate"],
    )
    def test_public_material_not_redacted(self, begin: str) -> None:
        text = begin + "\n" + "\n".join(_fake_key_body("H4")) + "\n"
        result = RedactionEngine().redact(text)
        assert result.redacted_text == text
        assert result.redaction_count == 0
