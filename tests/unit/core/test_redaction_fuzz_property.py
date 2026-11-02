"""Seeded planted-secret property test for the RedactionEngine (#261) + #264 pins.

The property (scope ruled by HW-PROGRAMME2 for #261): no planted fake PRIVATE
KEY body survives any path, and the two-pass helper and a whole-text call
agree on every case. The single-line residual classes are tracked in #264 and
pinned below as strict xfails, so #264 starts from a RED that flips when fixed.

Full-size run by hand: ``.venv/bin/python -m tests.unit.core.fuzz_redaction 261 20000``

SYNTHETIC DATA ONLY: every secret is FAKE and assembled at runtime from parts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.redaction import RedactionEngine
from tests.unit.core.fuzz_redaction import PATHS, PRIVATE_KEY_KINDS, run

pytestmark = [pytest.mark.unit, pytest.mark.security]

FUZZ_SEED = 261
FUZZ_CASES_PER_MODE = 1000


@pytest.mark.parametrize("mode", ["A", "B"], ids=["abutting", "separated"])
def test_no_private_key_body_survives_and_paths_agree(tmp_path: Path, mode: str) -> None:
    report = run(FUZZ_SEED, FUZZ_CASES_PER_MODE, mode, tmp_path)
    assert report.cases == FUZZ_CASES_PER_MODE
    for path in PATHS:
        assert report.leak_total(path, PRIVATE_KEY_KINDS) == 0, f"key body leaked via {path}"
    assert report.differ == 0, "two-pass helper and whole-text call disagree"


# ---------------------------------------------------------------------------
# #264 residual classes: pre-existing (also on the v2 engine), not fixed here
# ---------------------------------------------------------------------------


def _password() -> str:
    return "fkPw" + "264" + "x9"


def _bearer_value() -> str:
    return "FAKEbearer" + "264"


def _sk_token() -> str:
    return "sk-" + "TESTONLY" + "0" * 20


def _db_uri() -> str:
    return "postgresql://svcuser:" + _password() + "@db.example.test/app"


_RESIDUAL_264 = {
    # B1: bearer_token eats the URI scheme, so db_password cannot anchor.
    "B1_bearer_word_then_db_uri": "Bearer " + _db_uri(),
    # B2: the first match takes "Bearer" as the value; the real token survives.
    "B2_bearer_twice_then_token": "Bearer Bearer " + _bearer_value(),
    # A1: ai_api_key eats the abutting scheme word.
    "A1_sk_token_abutting_db_uri": _sk_token() + _db_uri(),
    # A2: bearer_token's value eats the abutting scheme word.
    "A2_bearer_value_abutting_db_uri": "Bearer " + _bearer_value() + _db_uri(),
    # A3: ai_api_key eats the abutting "Bearer" keyword.
    "A3_sk_token_abutting_bearer": _sk_token() + "Bearer " + _bearer_value(),
}


@pytest.mark.xfail(strict=True, reason="#264")
@pytest.mark.parametrize("text", _RESIDUAL_264.values(), ids=_RESIDUAL_264.keys())
def test_residual_264_secret_does_not_survive(text: str) -> None:
    out = RedactionEngine.redact_content(text)
    assert _password() not in out, "db password survived"
    assert _bearer_value() not in out, "bearer token survived"
