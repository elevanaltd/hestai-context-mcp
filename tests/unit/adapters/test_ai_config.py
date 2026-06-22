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
import os
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
        "HESTAI_AI_MODEL_ANALYSIS",
        "HESTAI_AI_MODEL_CRITICAL",
        "HESTAI_AI_PROVIDER_ROUTING",
        "HESTAI_AI_PROVIDER_ORDER",
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


class TestResolveModelTierAware:
    """Issue #77: ``resolve_model(tier)`` maps a tier to its env var.

    Tiers and their env vars:
        * ``default``  -> ``HESTAI_AI_MODEL``
        * ``analysis`` -> ``HESTAI_AI_MODEL_ANALYSIS``
        * ``critical`` -> ``HESTAI_AI_MODEL_CRITICAL``

    Fallback chain for the non-default tiers when their specific var is
    unset: tier var -> ``HESTAI_AI_MODEL`` -> ``DEFAULT_MODEL``. The
    zero-arg call (``resolve_model()``) keeps its pre-#77 default-tier
    behaviour exactly (back-compatibility).
    """

    def test_default_tier_is_backcompat_zero_arg(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import DEFAULT_MODEL, resolve_model

        # No arg and tier="default" must agree, and both equal the legacy default.
        assert resolve_model() == DEFAULT_MODEL
        assert resolve_model("default") == DEFAULT_MODEL

    def test_default_tier_reads_hestai_ai_model(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "base/model")
        assert resolve_model() == "base/model"
        assert resolve_model("default") == "base/model"

    def test_analysis_tier_reads_analysis_var(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "base/model")
        monkeypatch.setenv("HESTAI_AI_MODEL_ANALYSIS", "analysis/model")
        assert resolve_model("analysis") == "analysis/model"
        # The default tier is unaffected by the analysis var.
        assert resolve_model("default") == "base/model"

    def test_critical_tier_reads_critical_var(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL_CRITICAL", "critical/model")
        assert resolve_model("critical") == "critical/model"

    def test_analysis_falls_back_to_hestai_ai_model_when_unset(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        # Analysis-specific var unset -> falls back to HESTAI_AI_MODEL.
        monkeypatch.setenv("HESTAI_AI_MODEL", "base/model")
        assert resolve_model("analysis") == "base/model"

    def test_analysis_falls_back_to_default_model_when_all_unset(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import DEFAULT_MODEL, resolve_model

        # Neither the analysis var nor HESTAI_AI_MODEL set -> DEFAULT_MODEL.
        assert resolve_model("analysis") == DEFAULT_MODEL

    def test_critical_falls_back_to_default_model_when_all_unset(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import DEFAULT_MODEL, resolve_model

        assert resolve_model("critical") == DEFAULT_MODEL

    def test_unknown_tier_raises_value_error(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        with pytest.raises(ValueError):
            resolve_model("nonsense-tier")


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


class TestResolveProviderPayload:
    """Issue #96: config-sourced OpenRouter upstream-routing pin.

    ``resolve_provider_payload(provider)`` returns the generic
    ``{"provider": {...}}`` payload the adapter merges into the request body —
    or ``None`` to send no routing preference. The pin is:

      * config-sourced (NOT a hardcoded ``if model == "minimax-m3"`` branch),
      * **prefer, not require**: ``allow_fallbacks`` stays True so a preferred
        upstream outage degrades gracefully instead of hard-failing,
      * env-overridable (order list) and disableable, so it is not brittle.
    """

    def test_exposed_in_public_api(self):
        from hestai_context_mcp.adapters import ai_config

        assert hasattr(ai_config, "resolve_provider_payload")
        assert "resolve_provider_payload" in ai_config.__all__

    def test_openrouter_default_pins_preferred_order_with_fallbacks(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider_payload

        payload = resolve_provider_payload("openrouter")
        assert payload is not None
        provider = payload["provider"]
        assert isinstance(provider["order"], list) and provider["order"]
        # Prefer, not require: graceful degradation on a preferred-upstream outage.
        assert provider["allow_fallbacks"] is True

    def test_non_openrouter_provider_has_no_routing_payload(self, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider_payload

        assert resolve_provider_payload("openai") is None

    def test_order_is_env_overridable(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider_payload

        monkeypatch.setenv("HESTAI_AI_PROVIDER_ORDER", "Foo, Bar ,Baz")
        payload = resolve_provider_payload("openrouter")
        assert payload is not None
        # Comma-separated, trimmed, order preserved.
        assert payload["provider"]["order"] == ["Foo", "Bar", "Baz"]

    def test_routing_disabled_by_env_returns_none(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider_payload

        monkeypatch.setenv("HESTAI_AI_PROVIDER_ROUTING", "off")
        assert resolve_provider_payload("openrouter") is None

    def test_empty_order_env_disables_routing(self, monkeypatch: pytest.MonkeyPatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_provider_payload

        # An explicitly empty / whitespace order list means "no preference".
        monkeypatch.setenv("HESTAI_AI_PROVIDER_ORDER", "   ,  ")
        assert resolve_provider_payload("openrouter") is None


class TestResolveModelPerRepoOverride:
    """Issue #106 / HO-INTAKE-MODEL-RESOLUTION-CENTRALIZED-20260620.

    Model selection is centralized-by-default (the process environment wins,
    so every caller repo gets the same model) with an explicit per-repo
    opt-in: only when the caller's ``working_dir/.env`` sets
    ``PER_REPO_OVERRIDE`` truthy does that repo's own
    ``HESTAI_AI_MODEL[_TIER]`` take effect. The caller ``.env`` is parsed for
    those keys ONLY — never ``load_dotenv``'d into the shared process
    (PROD::I2: zero caller-secret ingress).
    """

    @staticmethod
    def _write_env(tmp_path, body: str) -> str:
        (tmp_path / ".env").write_text(body, encoding="utf-8")
        return str(tmp_path)

    def test_working_dir_none_is_backcompat(self, monkeypatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        assert resolve_model("default", working_dir=None) == "process/model"

    def test_no_override_flag_ignores_repo_env(self, tmp_path, monkeypatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        wd = self._write_env(tmp_path, "HESTAI_AI_MODEL=repo/model\n")
        # No PER_REPO_OVERRIDE -> default behaviour: process env wins, repo .env ignored.
        assert resolve_model("default", working_dir=wd) == "process/model"

    def test_override_true_uses_repo_model(self, tmp_path, monkeypatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        wd = self._write_env(tmp_path, "PER_REPO_OVERRIDE=true\nHESTAI_AI_MODEL=repo/model\n")
        assert resolve_model("default", working_dir=wd) == "repo/model"

    def test_override_true_is_tier_aware(self, tmp_path, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        wd = self._write_env(
            tmp_path,
            "PER_REPO_OVERRIDE=1\nHESTAI_AI_MODEL=repo/base\nHESTAI_AI_MODEL_ANALYSIS=repo/analysis\n",
        )
        assert resolve_model("analysis", working_dir=wd) == "repo/analysis"
        assert resolve_model("default", working_dir=wd) == "repo/base"

    def test_override_true_tier_falls_back_to_repo_base(self, tmp_path, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        wd = self._write_env(tmp_path, "PER_REPO_OVERRIDE=true\nHESTAI_AI_MODEL=repo/base\n")
        # analysis var absent in the repo .env -> repo base.
        assert resolve_model("analysis", working_dir=wd) == "repo/base"

    def test_override_true_but_no_repo_model_falls_back_to_process(
        self, tmp_path, monkeypatch, clean_env
    ):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        wd = self._write_env(tmp_path, "PER_REPO_OVERRIDE=true\n")
        assert resolve_model("default", working_dir=wd) == "process/model"

    def test_override_true_no_model_anywhere_falls_back_to_default(self, tmp_path, clean_env):
        from hestai_context_mcp.adapters.ai_config import DEFAULT_MODEL, resolve_model

        wd = self._write_env(tmp_path, "PER_REPO_OVERRIDE=true\n")
        assert resolve_model("default", working_dir=wd) == DEFAULT_MODEL

    def test_override_falsey_values_do_not_trigger(self, tmp_path, monkeypatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        for val in ("false", "0", "no", '""'):
            wd = self._write_env(tmp_path, f"PER_REPO_OVERRIDE={val}\nHESTAI_AI_MODEL=repo/model\n")
            assert resolve_model("default", working_dir=wd) == "process/model", val

    def test_missing_env_file_is_backcompat(self, tmp_path, monkeypatch, clean_env):
        from hestai_context_mcp.adapters.ai_config import resolve_model

        monkeypatch.setenv("HESTAI_AI_MODEL", "process/model")
        # working_dir exists but has no .env file at all.
        assert resolve_model("default", working_dir=str(tmp_path)) == "process/model"

    def test_caller_env_not_loaded_into_process(self, tmp_path, clean_env):
        """PROD::I2 — parsing the caller .env must NOT leak its secrets into os.environ."""
        from hestai_context_mcp.adapters.ai_config import resolve_model

        wd = self._write_env(
            tmp_path,
            "PER_REPO_OVERRIDE=true\nHESTAI_AI_MODEL=repo/model\nSECRET_TOKEN=supersecret\n",
        )
        assert resolve_model("default", working_dir=wd) == "repo/model"
        assert "SECRET_TOKEN" not in os.environ


# Dead-import helper so ``Any`` stays reachable by mypy when adding fields.
_ = Any
