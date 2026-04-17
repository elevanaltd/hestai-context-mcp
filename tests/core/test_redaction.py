"""Tests for RedactionEngine credential safety.

Comprehensive test suite covering detection and redaction of sensitive
credentials from session transcripts. Written as TDD RED phase -- these
tests define the expected behavior before implementation.

Security-critical: these tests verify that no credentials leak into archives.

NOTE: All credential-like strings in this file are SYNTHETIC TEST DATA.
They are deliberately crafted to match credential patterns for testing
the RedactionEngine's detection capabilities. None are real credentials.
All are prefixed or annotated to make this obvious.
"""

from __future__ import annotations

import pytest

from hestai_context_mcp.core.redaction import RedactionEngine, RedactionResult

# ---------------------------------------------------------------------------
# Synthetic test credential factories (conftest-style, inline for clarity)
# ---------------------------------------------------------------------------

# These are SYNTHETIC values that match credential FORMAT but are not real.
# Prefixed with obvious markers where format allows.
FAKE_SK_KEY = "sk-TESTONLY0000000000000000000000"  # nosec: synthetic test data
FAKE_SK_KEY_2 = "sk-TESTONLY1111111111111111111111"  # nosec: synthetic test data
FAKE_SK_KEY_3 = "sk-TESTONLYaabbccddeeffgghh1234"  # nosec: synthetic test data
FAKE_SK_KEY_JSON = "sk-TESTONLYAbc123Def456Ghi789Jkl"  # nosec: synthetic test data
FAKE_SK_KEY_ENV = "sk-TESTONLYabcdefghijklmnopqrstuv"  # nosec: synthetic test data
FAKE_SK_KEY_LONG = "sk-TESTONLYLongKeyRedacted123456"  # nosec: synthetic test data

FAKE_AWS_KEY_AKIA = "AKIATESTONLY00000000"  # nosec: synthetic 20-char AWS format
FAKE_AWS_KEY_ASIA = "ASIATESTONLY00000000"  # nosec: synthetic 20-char AWS format
FAKE_AWS_KEY_CFG = "AKIATESTONLY11111111"  # nosec: synthetic 20-char AWS format
FAKE_AWS_KEY_SHORT = "AKIA12345678AB"  # nosec: intentionally wrong length (14 not 16)

FAKE_BEARER = "eyTESTONLY.not-a-real-jwt.synthetic"  # nosec: synthetic bearer
FAKE_BEARER_PADDED = "dGVzdE9OTFlub3RyZWFs"  # nosec: base64 of "testONLYnotreal"

FAKE_PEM_RSA_BODY = "TESTONLY+NOT+A+REAL+KEY+AAAAAAAAAA\nTESTONLY+BBBBBBBBBBBBBBBBBBBBBBBB"
FAKE_PEM_EC_BODY = "TESTONLY+EC+NOT+REAL+CCCCCCCCCCCC"
FAKE_PEM_GENERIC_BODY = "TESTONLY+GENERIC+NOT+REAL+DDDDDD"
FAKE_PEM_PUBLIC_BODY = "TESTONLY+PUBLIC+NOT+PRIVATE+EEEE"

FAKE_DB_PASS = "testonly_not_real_password"  # nosec: synthetic password
FAKE_DB_PASS_SPECIAL = "t3st@nly!"  # nosec: synthetic password with special chars
FAKE_DB_PASS_AT = "t3st@pass"  # nosec: synthetic password with @ symbol
FAKE_DB_PASS_REDIS = "testonlyredispass"  # nosec: synthetic password
FAKE_DB_PASS_MULTI = "testonly123"  # nosec: synthetic password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> RedactionEngine:
    """Provide a fresh RedactionEngine instance."""
    return RedactionEngine()


# ---------------------------------------------------------------------------
# RedactionResult interface tests
# ---------------------------------------------------------------------------


class TestRedactionResult:
    """Test the RedactionResult data structure."""

    def test_result_has_redacted_text(self, engine: RedactionEngine) -> None:
        """RedactionResult must expose the redacted text."""
        result = engine.redact(f"some text with {FAKE_SK_KEY}")
        assert isinstance(result, RedactionResult)
        assert isinstance(result.redacted_text, str)

    def test_result_has_redaction_count(self, engine: RedactionEngine) -> None:
        """RedactionResult must report how many redactions were made."""
        result = engine.redact(FAKE_SK_KEY)
        assert isinstance(result.redaction_count, int)
        assert result.redaction_count >= 1

    def test_result_has_redaction_types(self, engine: RedactionEngine) -> None:
        """RedactionResult must report which types of credentials were redacted."""
        result = engine.redact(FAKE_SK_KEY)
        assert isinstance(result.redacted_types, list)
        assert len(result.redacted_types) >= 1

    def test_result_no_redactions_for_clean_text(self, engine: RedactionEngine) -> None:
        """Clean text should produce zero redactions."""
        result = engine.redact("This is perfectly normal text with no secrets.")
        assert result.redacted_text == "This is perfectly normal text with no secrets."
        assert result.redaction_count == 0
        assert result.redacted_types == []


# ---------------------------------------------------------------------------
# AI API key detection
# ---------------------------------------------------------------------------


class TestAIAPIKeyRedaction:
    """Test redaction of AI service API keys (OpenAI, Anthropic, etc.)."""

    def test_openai_api_key(self, engine: RedactionEngine) -> None:
        """Detect OpenAI-style API keys starting with sk-."""
        text = f"My key is {FAKE_SK_KEY_3}"
        result = engine.redact(text)
        assert FAKE_SK_KEY_3 not in result.redacted_text
        assert "[REDACTED_API_KEY]" in result.redacted_text
        assert result.redaction_count == 1

    def test_api_key_in_env_format(self, engine: RedactionEngine) -> None:
        """Detect API keys in environment variable format."""
        text = f"OPENAI_API_KEY={FAKE_SK_KEY_ENV}"  # nosec: synthetic
        result = engine.redact(text)
        assert FAKE_SK_KEY_ENV not in result.redacted_text
        assert "[REDACTED_API_KEY]" in result.redacted_text

    def test_api_key_in_json_format(self, engine: RedactionEngine) -> None:
        """Detect API keys embedded in JSON-like content."""
        text = f'{{"api_key": "{FAKE_SK_KEY_JSON}"}}'  # nosec: synthetic
        result = engine.redact(text)
        assert FAKE_SK_KEY_JSON not in result.redacted_text

    def test_multiple_api_keys(self, engine: RedactionEngine) -> None:
        """Detect multiple API keys in the same text."""
        text = f"Key 1: {FAKE_SK_KEY} Key 2: {FAKE_SK_KEY_2}"
        result = engine.redact(text)
        assert result.redaction_count == 2

    def test_short_sk_prefix_not_redacted(self, engine: RedactionEngine) -> None:
        """Short strings starting with sk- should NOT be redacted (false positive guard)."""
        text = "The variable sk-short is not a key."
        result = engine.redact(text)
        # sk-short is only 5 chars after sk-, below the 20-char threshold
        assert result.redaction_count == 0


# ---------------------------------------------------------------------------
# AWS key detection
# ---------------------------------------------------------------------------


class TestAWSKeyRedaction:
    """Test redaction of AWS access keys."""

    def test_aws_access_key_akia(self, engine: RedactionEngine) -> None:
        """Detect AWS access keys starting with AKIA."""
        text = f"aws_access_key_id = {FAKE_AWS_KEY_AKIA}"  # nosec: synthetic
        result = engine.redact(text)
        assert FAKE_AWS_KEY_AKIA not in result.redacted_text
        assert "[REDACTED_AWS_KEY]" in result.redacted_text

    def test_aws_temporary_key_asia(self, engine: RedactionEngine) -> None:
        """Detect AWS temporary credentials starting with ASIA."""
        text = FAKE_AWS_KEY_ASIA  # nosec: synthetic
        result = engine.redact(text)
        assert FAKE_AWS_KEY_ASIA not in result.redacted_text
        assert "[REDACTED_AWS_KEY]" in result.redacted_text

    def test_aws_key_in_config(self, engine: RedactionEngine) -> None:
        """Detect AWS keys in config file format."""
        # nosec: all values are synthetic test data
        text = f"[default]\naws_access_key_id = {FAKE_AWS_KEY_CFG}\nregion = us-east-1"
        result = engine.redact(text)
        assert FAKE_AWS_KEY_CFG not in result.redacted_text

    def test_akia_like_but_wrong_length_not_redacted(self, engine: RedactionEngine) -> None:
        """AKIA prefix with wrong length should not match (exactly 16 after prefix)."""
        # AKIA + only 10 chars (too short for the 16-char requirement)
        text = f"{FAKE_AWS_KEY_SHORT} is not a full key"
        result = engine.redact(text)
        assert result.redaction_count == 0


# ---------------------------------------------------------------------------
# Bearer token detection
# ---------------------------------------------------------------------------


class TestBearerTokenRedaction:
    """Test redaction of Bearer authentication tokens."""

    def test_bearer_token(self, engine: RedactionEngine) -> None:
        """Detect standard Bearer tokens in Authorization headers."""
        # nosec: synthetic JWT-format string, not a real token
        text = f"Authorization: Bearer {FAKE_BEARER}"
        result = engine.redact(text)
        assert FAKE_BEARER not in result.redacted_text
        assert "Bearer [REDACTED_BEARER]" in result.redacted_text

    def test_bearer_token_with_padding(self, engine: RedactionEngine) -> None:
        """Detect Bearer tokens with base64 padding characters."""
        text = f"Bearer {FAKE_BEARER_PADDED}=="  # nosec: synthetic
        result = engine.redact(text)
        assert FAKE_BEARER_PADDED not in result.redacted_text

    def test_bearer_word_alone_not_redacted(self, engine: RedactionEngine) -> None:
        """The word 'Bearer' alone without a token should not trigger redaction."""
        text = "The Bearer of bad news arrived."
        result = engine.redact(text)
        # The key test is that meaningful prose is not mangled.
        assert "bad news arrived" in result.redacted_text


# ---------------------------------------------------------------------------
# PEM private key detection
# ---------------------------------------------------------------------------


class TestPrivateKeyRedaction:
    """Test redaction of PEM-encoded private keys."""

    def test_rsa_private_key(self, engine: RedactionEngine) -> None:
        """Detect RSA private key blocks."""
        # nosec: synthetic PEM block, not a real key
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            f"{FAKE_PEM_RSA_BODY}\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = engine.redact(text)
        assert "TESTONLY" not in result.redacted_text or "[REDACTED" in result.redacted_text
        assert "[REDACTED_PRIVATE_KEY]" in result.redacted_text

    def test_ec_private_key(self, engine: RedactionEngine) -> None:
        """Detect EC private key blocks."""
        # nosec: synthetic PEM block, not a real key
        text = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            f"{FAKE_PEM_EC_BODY}\n"
            "-----END EC PRIVATE KEY-----"
        )
        result = engine.redact(text)
        assert "[REDACTED_PRIVATE_KEY]" in result.redacted_text

    def test_generic_private_key(self, engine: RedactionEngine) -> None:
        """Detect generic PRIVATE KEY blocks."""
        # nosec: synthetic PEM block, not a real key
        text = (
            "-----BEGIN PRIVATE KEY-----\n" f"{FAKE_PEM_GENERIC_BODY}\n" "-----END PRIVATE KEY-----"
        )
        result = engine.redact(text)
        assert FAKE_PEM_GENERIC_BODY not in result.redacted_text

    def test_public_key_not_redacted(self, engine: RedactionEngine) -> None:
        """Public keys should NOT be redacted (only PRIVATE keys)."""
        text = "-----BEGIN PUBLIC KEY-----\n" f"{FAKE_PEM_PUBLIC_BODY}\n" "-----END PUBLIC KEY-----"
        result = engine.redact(text)
        assert FAKE_PEM_PUBLIC_BODY in result.redacted_text
        assert result.redaction_count == 0


# ---------------------------------------------------------------------------
# Database connection string password detection
# ---------------------------------------------------------------------------


class TestDatabasePasswordRedaction:
    """Test redaction of passwords in database connection strings."""

    def test_postgres_connection_string(self, engine: RedactionEngine) -> None:
        """Detect password in PostgreSQL connection string."""
        # nosec: synthetic connection string
        text = f"postgresql://admin:{FAKE_DB_PASS}@db.example.com:5432/mydb"
        result = engine.redact(text)
        assert FAKE_DB_PASS not in result.redacted_text
        assert "[REDACTED_PASSWORD]" in result.redacted_text
        # Scheme and host should be preserved
        assert "postgresql://" in result.redacted_text
        assert "db.example.com" in result.redacted_text

    def test_mysql_connection_string(self, engine: RedactionEngine) -> None:
        """Detect password in MySQL connection string."""
        # nosec: synthetic connection string
        text = f"mysql://root:{FAKE_DB_PASS_SPECIAL}@localhost:3306/testdb"
        result = engine.redact(text)
        assert FAKE_DB_PASS_SPECIAL not in result.redacted_text
        assert "[REDACTED_PASSWORD]" in result.redacted_text

    def test_connection_string_with_at_in_password(self, engine: RedactionEngine) -> None:
        """Handle passwords containing @ symbols correctly."""
        # nosec: synthetic connection string
        text = f"postgresql://user:{FAKE_DB_PASS_AT}@host.com:5432/db"
        result = engine.redact(text)
        assert FAKE_DB_PASS_AT not in result.redacted_text
        assert "host.com" in result.redacted_text

    def test_redis_connection_string(self, engine: RedactionEngine) -> None:
        """Detect password in Redis connection string."""
        # nosec: synthetic connection string
        text = f"redis://default:{FAKE_DB_PASS_REDIS}@redis.example.com:6379/0"
        result = engine.redact(text)
        assert FAKE_DB_PASS_REDIS not in result.redacted_text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_input(self, engine: RedactionEngine) -> None:
        """Empty input should return empty result."""
        result = engine.redact("")
        assert result.redacted_text == ""
        assert result.redaction_count == 0

    def test_very_long_input(self, engine: RedactionEngine) -> None:
        """Large input should be processed without issues."""
        # 10KB of text with an embedded synthetic secret
        padding = "x" * (10 * 1024)
        text = f"{padding}\n{FAKE_SK_KEY_LONG}\n{padding}"
        result = engine.redact(text)
        assert FAKE_SK_KEY_LONG not in result.redacted_text
        assert result.redaction_count == 1

    def test_multiple_credential_types_in_same_text(self, engine: RedactionEngine) -> None:
        """Multiple different credential types in the same text."""
        # nosec: all values below are synthetic test data
        text = (
            f"API key: {FAKE_SK_KEY_ENV}\n"
            f"AWS: {FAKE_AWS_KEY_AKIA}\n"
            f"Auth: Bearer {FAKE_BEARER}\n"
            f"DB: postgresql://admin:{FAKE_DB_PASS_MULTI}@db.host.com:5432/mydb\n"
        )
        result = engine.redact(text)
        assert result.redaction_count >= 4
        assert FAKE_SK_KEY_ENV not in result.redacted_text
        assert FAKE_AWS_KEY_AKIA not in result.redacted_text
        assert FAKE_BEARER not in result.redacted_text
        assert FAKE_DB_PASS_MULTI not in result.redacted_text

    def test_unicode_content_preserved(self, engine: RedactionEngine) -> None:
        """Unicode characters in surrounding text should be preserved."""
        text = f"Hello! The key is {FAKE_SK_KEY_ENV}"
        result = engine.redact(text)
        assert "Hello!" in result.redacted_text

    def test_newlines_preserved(self, engine: RedactionEngine) -> None:
        """Newline structure should be preserved in output."""
        text = "line1\nline2\nline3"
        result = engine.redact(text)
        assert result.redacted_text == "line1\nline2\nline3"

    def test_only_whitespace_input(self, engine: RedactionEngine) -> None:
        """Whitespace-only input passes through unchanged."""
        result = engine.redact("   \n\t  \n  ")
        assert result.redacted_text == "   \n\t  \n  "
        assert result.redaction_count == 0

    def test_redacted_types_lists_each_type_once(self, engine: RedactionEngine) -> None:
        """If two API keys are found, 'ai_api_key' appears once in redacted_types."""
        text = f"{FAKE_SK_KEY} {FAKE_SK_KEY_2}"
        result = engine.redact(text)
        assert result.redaction_count == 2
        # The type should appear only once even though two instances were found
        type_count = result.redacted_types.count("ai_api_key")
        assert type_count == 1


# ---------------------------------------------------------------------------
# Classmethod backward compat (redact_content)
# ---------------------------------------------------------------------------


class TestClassMethodCompat:
    """Test the classmethod interface for backward compatibility."""

    def test_redact_content_classmethod(self) -> None:
        """RedactionEngine.redact_content should work as a classmethod returning str."""
        result = RedactionEngine.redact_content(FAKE_SK_KEY_ENV)
        assert isinstance(result, str)
        assert FAKE_SK_KEY_ENV not in result
        assert "[REDACTED_API_KEY]" in result

    def test_redact_content_clean_text(self) -> None:
        """Clean text through classmethod passes through unchanged."""
        text = "No secrets here, just regular text."
        assert RedactionEngine.redact_content(text) == text


# ---------------------------------------------------------------------------
# File-based redaction (copy_and_redact)
# ---------------------------------------------------------------------------


class TestCopyAndRedact:
    """Test file-based redaction for session archive processing."""

    def test_copy_and_redact_basic(self, engine: RedactionEngine, tmp_path) -> None:
        """Copy a file with redaction applied."""
        src = tmp_path / "source.jsonl"
        dst = tmp_path / "redacted.jsonl"
        # nosec: synthetic test data
        src.write_text(
            f'{{"text": "key is {FAKE_SK_KEY_ENV}"}}\n{{"text": "normal line"}}\n',
            encoding="utf-8",
        )
        RedactionEngine.copy_and_redact(src, dst)
        content = dst.read_text(encoding="utf-8")
        assert FAKE_SK_KEY_ENV not in content
        assert "[REDACTED_API_KEY]" in content
        assert "normal line" in content

    def test_copy_and_redact_source_not_found(self, tmp_path) -> None:
        """copy_and_redact raises FileNotFoundError for missing source."""
        src = tmp_path / "nonexistent.jsonl"
        dst = tmp_path / "out.jsonl"
        with pytest.raises(FileNotFoundError):
            RedactionEngine.copy_and_redact(src, dst)

    def test_copy_and_redact_fail_closed(self, tmp_path) -> None:
        """If redaction fails, destination file should not exist (fail-closed)."""
        src = tmp_path / "source.bin"
        dst = tmp_path / "redacted.bin"
        # Write binary content that will fail UTF-8 decode
        src.write_bytes(b"\x80\x81\x82\x83")
        with pytest.raises(UnicodeDecodeError):
            RedactionEngine.copy_and_redact(src, dst)
        # Fail-closed: dst should not exist
        assert not dst.exists()
