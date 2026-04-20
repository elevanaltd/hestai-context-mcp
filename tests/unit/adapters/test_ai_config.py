"""Config + credential resolution tests for ``adapters.ai_config``.

Covers:
- Provider / model env-var precedence (legacy env vars only; no new ones).
- Keyring-first credential precedence; env-var fallback.
- Keyring service-name migration from legacy ``"hestai-mcp"`` to the new
  service name ``"hestai-context-mcp"`` (read-legacy → write-new →
  delete-legacy, with INFO log), per HO-confirmed migration.
- Fail-closed: no credential values are ever returned in logs or __repr__.

These tests mock the ``keyring`` module surface; the implementation must
read credentials via ``keyring.get_password`` / write via
``keyring.set_password`` / delete via ``keyring.delete_password`` so that
this mocking strategy is representative.

PROD::I2 CREDENTIAL_SAFETY and PROD::I6 LEGACY_INDEPENDENCE are the
binding invariants tested here.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

# --- Fake keyring --------------------------------------------------------


class FakeKeyring:
    """In-memory replacement for the subset of the ``keyring`` module used."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self.set_calls: list[tuple[str, str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []

    # keyring module API
    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password
        self.set_calls.append((service, username, password))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise Exception("password not found")  # keyring raises PasswordDeleteError
        del self._store[(service, username)]
        self.delete_calls.append((service, username))


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """Install a fake ``keyring`` module so tests don't touch the OS keyring."""
    fk = FakeKeyring()
    import hestai_context_mcp.adapters.ai_config as cfg_mod

    monkeypatch.setattr(cfg_mod, "keyring", fk, raising=True)
    return fk


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every env var this module reads before each test."""
    for var in (
        "HESTAI_AI_PROVIDER",
        "HESTAI_AI_MODEL",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# --- Module shape --------------------------------------------------------


class TestConfigModuleShape:
    def test_module_importable(self):
        import hestai_context_mcp.adapters.ai_config  # noqa: F401

    def test_exposes_public_api(self):
        from hestai_context_mcp.adapters import ai_config

        for name in (
            "LEGACY_KEYRING_SERVICE",
            "KEYRING_SERVICE",
            "resolve_provider",
            "resolve_model",
            "resolve_api_key",
            "get_provider_base_url",
        ):
            assert hasattr(ai_config, name), f"ai_config missing public name {name!r}"

    def test_service_name_is_hestai_context_mcp(self):
        from hestai_context_mcp.adapters.ai_config import KEYRING_SERVICE, LEGACY_KEYRING_SERVICE

        assert KEYRING_SERVICE == "hestai-context-mcp"
        assert LEGACY_KEYRING_SERVICE == "hestai-mcp"


# --- Provider / model resolution -----------------------------------------


class TestResolveProvider:
    def test_default_is_openrouter(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider

        assert resolve_provider() == "openrouter"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider

        monkeypatch.setenv("HESTAI_AI_PROVIDER", "openai")
        assert resolve_provider() == "openai"


class TestResolveModel:
    def test_default_is_gemini_flash_lite(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        assert resolve_model() == "google/gemini-2.0-flash-lite"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "some/other-model")
        assert resolve_model() == "some/other-model"


class TestProviderBaseUrl:
    @pytest.mark.parametrize(
        "provider,expected",
        [
            ("openai", "https://api.openai.com/v1"),
            ("openrouter", "https://openrouter.ai/api/v1"),
        ],
    )
    def test_known_providers(self, provider: str, expected: str):
        from hestai_context_mcp.adapters.ai_config import get_provider_base_url

        assert get_provider_base_url(provider) == expected

    def test_unknown_provider_raises(self):
        from hestai_context_mcp.adapters.ai_config import get_provider_base_url

        with pytest.raises(ValueError):
            get_provider_base_url("not-a-provider")


# --- Credential resolution ----------------------------------------------


class TestResolveApiKeyPrecedence:
    """Precedence: keyring (new service) → keyring (legacy, migrated) → env."""

    def test_returns_none_when_nothing_configured(self, clean_env, fake_keyring):
        from hestai_context_mcp.adapters.ai_config import resolve_api_key

        assert resolve_api_key(provider="openrouter") is None

    def test_keyring_new_service_wins(self, clean_env, fake_keyring, monkeypatch):
        from hestai_context_mcp.adapters.ai_config import KEYRING_SERVICE, resolve_api_key

        fake_keyring.set_password(KEYRING_SERVICE, "openrouter-key", "KR_KEY")
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")

        assert resolve_api_key(provider="openrouter") == "KR_KEY"

    def test_env_used_when_keyring_empty(self, clean_env, fake_keyring, monkeypatch):
        from hestai_context_mcp.adapters.ai_config import resolve_api_key

        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")
        assert resolve_api_key(provider="openrouter") == "ENV_KEY"

    def test_env_var_name_matches_provider(self, clean_env, fake_keyring, monkeypatch):
        from hestai_context_mcp.adapters.ai_config import resolve_api_key

        monkeypatch.setenv("OPENAI_API_KEY", "ENV_OAI")
        assert resolve_api_key(provider="openai") == "ENV_OAI"
        # And cross-provider env var must not leak:
        assert resolve_api_key(provider="openrouter") is None


# --- Keyring migration (legacy → new service) ---------------------------


class TestKeyringMigration:
    """Legacy ``hestai-mcp`` entry must be migrated to ``hestai-context-mcp``.

    Migration shape (per HO directive): on first read of a provider key, if
    the new service has no entry but the legacy service does, copy to new,
    delete legacy, log at INFO. Must leave no credential in two places
    (PROD::I2).
    """

    def test_migrates_from_legacy_when_new_absent(
        self, clean_env, fake_keyring, caplog: pytest.LogCaptureFixture
    ):
        from hestai_context_mcp.adapters.ai_config import (
            KEYRING_SERVICE,
            LEGACY_KEYRING_SERVICE,
            resolve_api_key,
        )

        fake_keyring.set_password(LEGACY_KEYRING_SERVICE, "openrouter-key", "SECRET_MIGRATED")

        with caplog.at_level(logging.INFO, logger="hestai_context_mcp.adapters.ai_config"):
            result = resolve_api_key(provider="openrouter")

        assert result == "SECRET_MIGRATED"
        # New service entry populated:
        assert fake_keyring.get_password(KEYRING_SERVICE, "openrouter-key") == "SECRET_MIGRATED"
        # Legacy entry deleted:
        assert fake_keyring.get_password(LEGACY_KEYRING_SERVICE, "openrouter-key") is None
        # Migration was logged at INFO, never logs the secret value:
        migration_records = [r for r in caplog.records if "migrat" in r.message.lower()]
        assert migration_records, "expected an INFO log record mentioning migration"
        for rec in migration_records:
            assert "SECRET_MIGRATED" not in rec.message
            assert "SECRET_MIGRATED" not in str(rec.args) if rec.args else True

    def test_self_heal_when_both_present(
        self, clean_env, fake_keyring, caplog: pytest.LogCaptureFixture
    ):
        """When new entry exists AND a lingering legacy entry exists, the legacy
        duplicate is self-healed (deleted) on the fast path.

        CE review ``ce-issue5-20260420-1`` flagged the prior "preserve
        legacy when new exists" behaviour as a crash-window
        duplicate-persistence leak (PROD::I2): if a migration crashes
        between ``set(NEW)`` and ``delete(LEGACY)``, the legacy entry
        survives indefinitely because subsequent reads take the fast
        path. The self-heal path closes the window.
        """
        from hestai_context_mcp.adapters.ai_config import (
            KEYRING_SERVICE,
            LEGACY_KEYRING_SERVICE,
            resolve_api_key,
        )

        fake_keyring.set_password(KEYRING_SERVICE, "openrouter-key", "NEW_KEY")
        fake_keyring.set_password(LEGACY_KEYRING_SERVICE, "openrouter-key", "LEGACY_KEY")

        with caplog.at_level(logging.INFO, logger="hestai_context_mcp.adapters.ai_config"):
            assert resolve_api_key(provider="openrouter") == "NEW_KEY"

        # Legacy duplicate removed; new entry untouched.
        assert (
            fake_keyring.get_password(LEGACY_KEYRING_SERVICE, "openrouter-key") is None
        ), "self-heal must remove lingering legacy entry"
        assert fake_keyring.get_password(KEYRING_SERVICE, "openrouter-key") == "NEW_KEY"

        # INFO-logged; neither secret is in the message.
        heal_records = [r for r in caplog.records if "self-heal" in r.message.lower()]
        assert heal_records, "expected an INFO log record mentioning self-heal"
        for rec in heal_records:
            assert "NEW_KEY" not in rec.getMessage()
            assert "LEGACY_KEY" not in rec.getMessage()

    def test_fast_path_with_no_legacy_does_not_call_delete(self, clean_env, fake_keyring):
        """Self-heal must not call delete when there is no legacy entry.

        Guard against needless keyring mutations (or ``PasswordDeleteError``
        from backends that raise when asked to delete a non-existent key).
        """
        from hestai_context_mcp.adapters.ai_config import KEYRING_SERVICE, resolve_api_key

        fake_keyring.set_password(KEYRING_SERVICE, "openrouter-key", "NEW_KEY")
        assert resolve_api_key(provider="openrouter") == "NEW_KEY"
        assert fake_keyring.delete_calls == []

    def test_no_migration_when_neither_present(self, clean_env, fake_keyring):
        from hestai_context_mcp.adapters.ai_config import resolve_api_key

        assert resolve_api_key(provider="openrouter") is None
        assert fake_keyring.set_calls == []
        assert fake_keyring.delete_calls == []


# --- Provider-agnostic import guard -------------------------------------


class TestConfigNoLegacyImport:
    """PROD::I6: the config module must not import from ``hestai_mcp``."""

    def test_no_hestai_mcp_import(self):
        import inspect

        import hestai_context_mcp.adapters.ai_config as cfg

        src = inspect.getsource(cfg)
        assert "import hestai_mcp" not in src
        assert "from hestai_mcp" not in src


# --- Fail-closed: no secret leakage in logs -----------------------------


def test_resolve_api_key_never_logs_secret_value(
    clean_env, fake_keyring, caplog: pytest.LogCaptureFixture, monkeypatch
):
    """PROD::I2: neither keyring values nor env values may be written to logs.

    TMG A1: captures at INFO level (the production default) so that a log
    statement above DEBUG still cannot leak a secret. Also asserts at
    DEBUG just in case a future verbose diagnostic path is added.
    """
    from hestai_context_mcp.adapters.ai_config import KEYRING_SERVICE, resolve_api_key

    fake_keyring.set_password(KEYRING_SERVICE, "openrouter-key", "SECRET_AAA")
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET_BBB")

    # Run twice so we verify at both production (INFO) and verbose (DEBUG) levels.
    for level in (logging.INFO, logging.DEBUG):
        caplog.clear()
        with caplog.at_level(level, logger="hestai_context_mcp.adapters.ai_config"):
            resolve_api_key(provider="openrouter")
        for rec in caplog.records:
            msg = rec.getMessage()
            assert "SECRET_AAA" not in msg, f"Secret leaked at level {level}: {msg!r}"
            assert "SECRET_BBB" not in msg, f"Secret leaked at level {level}: {msg!r}"


# Dead-import helper so ``Any`` stays reachable by mypy when adding fields.
_ = Any
