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

from hestai_context_mcp.core.redaction import (
    REDACTION_ENGINE_VERSION,
    RedactionEngine,
    RedactionResult,
)

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


# ---------------------------------------------------------------------------
# G1: Multi-line PEM block evasion (stream-mode CRITICAL gap)
# ---------------------------------------------------------------------------

# Synthetic PEM block bodies — NOT real keys
_PEM_BODY_G1 = (
    "MIIEowIBAAKTESTONLYNotARealKeyAAAAAAAAAAAAAAAAAAAAAAAA\n"
    "TESTONLYBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBb=\n"
    "TESTONLYCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCc="
)  # nosec: synthetic test data

_MULTILINE_RSA_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n" + _PEM_BODY_G1 + "\n-----END RSA PRIVATE KEY-----"
)  # nosec: synthetic test data

_MULTILINE_GENERIC_PEM = (
    "-----BEGIN PRIVATE KEY-----\n" + _PEM_BODY_G1 + "\n-----END PRIVATE KEY-----"
)  # nosec: synthetic test data


class TestG1MultiLinePemStreamMode:
    """G1: Verify multi-line PEM blocks are redacted via copy_and_redact (streaming path).

    The CRITICAL bug: copy_and_redact iterated line-by-line, so the DOTALL regex
    never saw a span from BEGIN to END. These tests prove the fix.
    """

    def test_multiline_pem_redacted_by_redact_method(self, engine: RedactionEngine) -> None:
        """Baseline: engine.redact() handles multi-line PEM correctly (full buffer)."""
        result = engine.redact(_MULTILINE_RSA_PEM)
        assert "[REDACTED_PRIVATE_KEY]" in result.redacted_text
        assert "TESTONLY" not in result.redacted_text
        assert result.redaction_count >= 1

    def test_multiline_pem_redacted_via_copy_and_redact(self, tmp_path) -> None:
        """G1 adversarial: copy_and_redact MUST redact a multi-line PEM block.

        This is the actual streaming path used by clock_out archival. A multi-line
        PEM block that spans many lines must be fully redacted — not left verbatim.
        """
        src = tmp_path / "transcript.jsonl"
        dst = tmp_path / "redacted.jsonl"
        content = (
            '{"role": "user", "content": "Here is my key:\\n'
            + _MULTILINE_RSA_PEM.replace("\n", "\\n")
            + '"}\n'
            '{"role": "assistant", "content": "Received."}\n'
        )
        src.write_text(content, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        output = dst.read_text(encoding="utf-8")
        assert "BEGIN RSA PRIVATE KEY" not in output
        assert "END RSA PRIVATE KEY" not in output
        assert "[REDACTED_PRIVATE_KEY]" in output

    def test_multiline_pem_literal_newlines_via_copy_and_redact(self, tmp_path) -> None:
        """G1 adversarial: PEM block with literal newlines across file lines.

        When a PEM block is stored with real newlines (not escaped), the streaming
        path must still redact it. This is the hardest case for a line-by-line reader.
        """
        src = tmp_path / "transcript_literal.jsonl"
        dst = tmp_path / "redacted_literal.jsonl"
        # Embed real newlines — this is what a pasted key in a transcript looks like
        content = "prefix text\n" + _MULTILINE_RSA_PEM + "\nsuffix text\n"
        src.write_text(content, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        output = dst.read_text(encoding="utf-8")
        assert "BEGIN RSA PRIVATE KEY" not in output
        assert "END RSA PRIVATE KEY" not in output
        assert "TESTONLY" not in output
        assert "[REDACTED_PRIVATE_KEY]" in output
        # Surrounding content preserved
        assert "prefix text" in output
        assert "suffix text" in output

    def test_generic_multiline_pem_via_copy_and_redact(self, tmp_path) -> None:
        """G1 adversarial: Generic PRIVATE KEY PEM block with literal newlines."""
        src = tmp_path / "generic_pem.jsonl"
        dst = tmp_path / "generic_pem_redacted.jsonl"
        content = "before\n" + _MULTILINE_GENERIC_PEM + "\nafter\n"
        src.write_text(content, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        output = dst.read_text(encoding="utf-8")
        assert "BEGIN PRIVATE KEY" not in output
        assert "[REDACTED_PRIVATE_KEY]" in output


# ---------------------------------------------------------------------------
# G2: GitHub Personal Access Token patterns (CRITICAL gap)
# ---------------------------------------------------------------------------

# Synthetic GitHub PAT shapes — NOT real tokens
# Classic PAT prefixes: ghp_, gho_, ghu_, ghs_, ghr_ + exactly 36 alphanumeric chars
# (GitHub classic PAT total length = prefix(4) + underscore(1) + 36 = 41 chars)
FAKE_GHP_TOKEN = "ghp_TESTONLYNotARealTokenAAAAAAAAAAAAAAA"  # nosec: 36 chars after ghp_
FAKE_GHO_TOKEN = "gho_TESTONLYNotARealTokenBBBBBBBBBBBBBBB"  # nosec: 36 chars after gho_
FAKE_GHU_TOKEN = "ghu_TESTONLYNotARealTokenCCCCCCCCCCCCCCC"  # nosec: 36 chars after ghu_
FAKE_GHS_TOKEN = "ghs_TESTONLYNotARealTokenDDDDDDDDDDDDDDD"  # nosec: 36 chars after ghs_
FAKE_GHR_TOKEN = "ghr_TESTONLYNotARealTokenEEEEEEEEEEEEEEE"  # nosec: 36 chars after ghr_
# Fine-grained PAT: github_pat_ + exactly 82 alphanumeric/underscore chars (total 93)
FAKE_GITHUB_PAT_FG = "github_pat_TESTONLYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec: synthetic, 82 chars after github_pat_


class TestG2GitHubPATRedaction:
    """G2: GitHub Personal Access Token redaction (classic and fine-grained)."""

    def test_ghp_classic_pat_redacted(self, engine: RedactionEngine) -> None:
        """Classic PAT with ghp_ prefix must be redacted."""
        result = engine.redact(f"token: {FAKE_GHP_TOKEN}")
        assert FAKE_GHP_TOKEN not in result.redacted_text
        assert "[REDACTED_GITHUB_TOKEN]" in result.redacted_text
        assert result.redaction_count >= 1

    def test_gho_classic_pat_redacted(self, engine: RedactionEngine) -> None:
        """Classic PAT with gho_ prefix must be redacted."""
        result = engine.redact(FAKE_GHO_TOKEN)
        assert FAKE_GHO_TOKEN not in result.redacted_text
        assert "[REDACTED_GITHUB_TOKEN]" in result.redacted_text

    def test_ghu_classic_pat_redacted(self, engine: RedactionEngine) -> None:
        """Classic PAT with ghu_ prefix must be redacted."""
        result = engine.redact(FAKE_GHU_TOKEN)
        assert FAKE_GHU_TOKEN not in result.redacted_text

    def test_ghs_classic_pat_redacted(self, engine: RedactionEngine) -> None:
        """Classic PAT with ghs_ prefix must be redacted."""
        result = engine.redact(FAKE_GHS_TOKEN)
        assert FAKE_GHS_TOKEN not in result.redacted_text

    def test_ghr_classic_pat_redacted(self, engine: RedactionEngine) -> None:
        """Classic PAT with ghr_ prefix must be redacted."""
        result = engine.redact(FAKE_GHR_TOKEN)
        assert FAKE_GHR_TOKEN not in result.redacted_text

    def test_github_pat_fine_grained_redacted(self, engine: RedactionEngine) -> None:
        """Fine-grained PAT with github_pat_ prefix must be redacted."""
        result = engine.redact(f"gh auth token output: {FAKE_GITHUB_PAT_FG}")
        assert FAKE_GITHUB_PAT_FG not in result.redacted_text
        assert "[REDACTED_GITHUB_TOKEN]" in result.redacted_text

    def test_github_pat_in_copy_and_redact(self, tmp_path) -> None:
        """GitHub PAT must be redacted via the streaming copy_and_redact path."""
        src = tmp_path / "transcript.jsonl"
        dst = tmp_path / "redacted.jsonl"
        src.write_text(
            f'{{"output": "token {FAKE_GHP_TOKEN}"}}\n',
            encoding="utf-8",
        )
        RedactionEngine.copy_and_redact(src, dst)
        output = dst.read_text(encoding="utf-8")
        assert FAKE_GHP_TOKEN not in output
        assert "[REDACTED_GITHUB_TOKEN]" in output

    def test_github_pat_type_in_redacted_types(self, engine: RedactionEngine) -> None:
        """Redacted types must include 'github_token' when a PAT is found."""
        result = engine.redact(FAKE_GHP_TOKEN)
        assert "github_token" in result.redacted_types


# ---------------------------------------------------------------------------
# G7: Widened sk- pattern — hyphens and underscores in token body
# ---------------------------------------------------------------------------

# Synthetic Anthropic / OpenAI key shapes with hyphens and underscores
FAKE_ANT_KEY = "sk-ant-api03-TESTONLYNotARealKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
FAKE_PROJ_KEY = (
    "sk-proj-TESTONLYNotARealProjectKeyBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"  # nosec
)
FAKE_SVCACCT_KEY = (
    "sk-svcacct-TESTONLYNotARealServiceKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
)


class TestG7WideSkPattern:
    """G7: sk- pattern widened to include hyphens and underscores in token body.

    Anthropic uses sk-ant-api03-... and OpenAI uses sk-proj-..., sk-svcacct-...
    These have hyphens and underscores in the token body. The original pattern
    [a-zA-Z0-9]{20,} would terminate at the first hyphen, leaving the entropy
    tail in cleartext.
    """

    def test_anthropic_key_full_token_redacted(self, engine: RedactionEngine) -> None:
        """Anthropic sk-ant-api03-... key: FULL token must be replaced, not just prefix."""
        result = engine.redact(f"ANTHROPIC_API_KEY={FAKE_ANT_KEY}")
        assert FAKE_ANT_KEY not in result.redacted_text
        assert "[REDACTED_API_KEY]" in result.redacted_text
        # The entropy tail must not survive
        assert "TESTONLY" not in result.redacted_text

    def test_openai_proj_key_full_token_redacted(self, engine: RedactionEngine) -> None:
        """OpenAI sk-proj-... key: FULL token must be replaced."""
        result = engine.redact(FAKE_PROJ_KEY)
        assert FAKE_PROJ_KEY not in result.redacted_text
        assert "[REDACTED_API_KEY]" in result.redacted_text

    def test_openai_svcacct_key_full_token_redacted(self, engine: RedactionEngine) -> None:
        """OpenAI sk-svcacct-... key: FULL token must be replaced."""
        result = engine.redact(FAKE_SVCACCT_KEY)
        assert FAKE_SVCACCT_KEY not in result.redacted_text

    def test_sk_key_with_hyphens_entropy_tail_not_leaked(self, engine: RedactionEngine) -> None:
        """Adversarial: confirm no partial match leaves entropy tail in cleartext."""
        # This is the specific failure mode: regex stops at first hyphen
        token = "sk-ant-api03-TESTONLYaabbccddeeffgghh"  # nosec: synthetic
        result = engine.redact(token)
        assert result.redacted_text == "[REDACTED_API_KEY]"

    def test_sk_short_still_not_redacted(self, engine: RedactionEngine) -> None:
        """Short sk- strings (below threshold) still must not be redacted (no regression)."""
        result = engine.redact("sk-short is not a key")
        assert result.redaction_count == 0

    def test_sk_key_in_copy_and_redact(self, tmp_path) -> None:
        """Anthropic key must be fully redacted via copy_and_redact streaming path."""
        src = tmp_path / "transcript.jsonl"
        dst = tmp_path / "redacted.jsonl"
        src.write_text(
            f'{{"api_key": "{FAKE_ANT_KEY}"}}\n',
            encoding="utf-8",
        )
        RedactionEngine.copy_and_redact(src, dst)
        output = dst.read_text(encoding="utf-8")
        assert FAKE_ANT_KEY not in output
        assert "[REDACTED_API_KEY]" in output


# ---------------------------------------------------------------------------
# Negative cases: must NOT redact (false-positive prevention)
# ---------------------------------------------------------------------------


class TestFalsePositivePrevention:
    """Verify that common identifiers are NOT over-redacted.

    These are the negative cases: strings that LOOK like they could match
    but must pass through unchanged.
    """

    def test_uuid_not_redacted(self, engine: RedactionEngine) -> None:
        """Standard UUID (8-4-4-4-12 hex) must not be redacted."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = engine.redact(f"session_id: {uuid}")
        assert uuid in result.redacted_text
        assert result.redaction_count == 0

    def test_git_commit_sha_not_redacted(self, engine: RedactionEngine) -> None:
        """40-character hex git commit SHA must not be redacted."""
        sha = "c019894a1b2c3d4e5f6789012345678901234567"
        result = engine.redact(f"commit: {sha}")
        assert sha in result.redacted_text
        assert result.redaction_count == 0

    def test_session_id_from_server_not_redacted(self, engine: RedactionEngine) -> None:
        """Session IDs produced by this server (UUID format) must not be redacted."""
        # Session IDs are UUIDs: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        session_id = "531a518f-48c1-4e4c-9e23-f8aa5fb5532e"
        result = engine.redact(f"session_id: {session_id}")
        assert session_id in result.redacted_text
        assert result.redaction_count == 0

    def test_short_hexadecimal_not_redacted(self, engine: RedactionEngine) -> None:
        """Short hex strings (commit short SHAs) must not be redacted."""
        short_sha = "c019894"
        result = engine.redact(f"ref: {short_sha}")
        assert short_sha in result.redacted_text
        assert result.redaction_count == 0


# ---------------------------------------------------------------------------
# Engine version integrity
# ---------------------------------------------------------------------------


class TestEngineVersion:
    """Verify REDACTION_ENGINE_VERSION is correctly bumped after pattern additions."""

    def test_engine_version_is_2(self) -> None:
        """REDACTION_ENGINE_VERSION must be '2' after Phase 1 pattern additions.

        Bump policy: increment on every pattern addition so downstream readers
        can identify artifacts produced by an older (potentially incomplete)
        redactor.
        """
        assert REDACTION_ENGINE_VERSION == "2"
