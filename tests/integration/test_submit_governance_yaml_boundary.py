"""EPIC4 PR-5 phase 1C (RED): the quoted-YAML write path across the REAL boundaries.

A temp repo with a real bare ``origin``, a stubbed ``gh`` on ``PATH`` (the only fake),
real git worktree / commit / push, then the record read back through
``lookup_decision`` from a clone of the pushed branch. Nothing is committed under the
repo's own ``.hestai/decisions``.
"""

from __future__ import annotations

import asyncio
import os
import stat
import subprocess
from pathlib import Path

import pytest

from hestai_context_mcp.core import agent_readable_governance_parser as _parser
from hestai_context_mcp.core.agent_readable_governance_parser import (
    emit_yaml_record,
    encode_yaml_scalar,
    read_record,
)
from hestai_context_mcp.tools import submit_governance as sg
from hestai_context_mcp.tools.lookup_decision import lookup_decision

pytestmark = pytest.mark.integration


def canonicalize_yaml_record(raw: str | bytes) -> str:
    """Late-bound so a missing implementation fails the test, not collection of the suite."""
    return _parser.canonicalize_yaml_record(raw)  # type: ignore[attr-defined,no-any-return]


TOKEN = "HO-ESCAPES-20261029"
PR_URL = "https://github.com/elevanaltd/hestai-context-mcp/pull/999"
CORE = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.4",
    "TOKEN": TOKEN,
    "STATUS": "RATIFIED",
    "TIER": "STRATEGIC",
    "AUTHORED_AT": "2026-10-29T00:00:00Z",
    "DECISION": 'Awkward "quoted" \\ decision\twith a tab.',
    "BECAUSE": "A one-sentence rationale.",
    "RATIFIED_BY": "human:operator",
}


_SCRUB = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_DIR",
    "GIT_WORK_TREE",
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


def _git_bytes(cwd: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True).stdout


@pytest.fixture()
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """(repo, bare remote); ``gh`` is a PATH stub that prints a PR URL."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bare = tmp_path / "origin.git"
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "core.hooksPath", str(repo / ".git" / "no-hooks"))
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text('#!/bin/sh\n[ "$1 $2" = "pr create" ] || exit 1\n' f"echo {PR_URL}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    for var in _SCRUB:
        monkeypatch.delenv(var, raising=False)
    return repo, bare


# Non-canonical on purpose: shuffled keys, CRLF front matter, an operator-ruling-shaped
# value with mixed quotes, and a CRLF markdown body that must survive byte for byte.
BODY = "# Notes\r\nkept\rverbatim\r\n\n"
OPERATOR_RULING = 'OPERATOR_RULING: "keep \'X\' and \\"Y\\"" -- it\'s "fine" \\ \t end'
SUBMITTED = (
    "---\r\n"
    'because: "A one-sentence rationale."\r\n'
    f"scope: {encode_yaml_scalar(OPERATOR_RULING)}\r\n"
    f'token:   "{TOKEN}"\r\n'
    'type: "DECISION_RECORD"\r\n'
    'version: "1.4"\r\n'
    'status: "RATIFIED"\r\n'
    'tier: "STRATEGIC"\r\n'
    'authored_at: "2026-10-29T00:00:00Z"\r\n'
    f"decision: {encode_yaml_scalar(CORE['DECISION'])}\r\n"
    "---\r\n" + BODY
)


def test_yaml_record_round_trips_through_submit_governance_and_lookup_decision(
    boundary: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, bare = boundary
    canonical = emit_yaml_record({**CORE, "SCOPE": OPERATOR_RULING}, None, None, body=BODY)
    assert canonicalize_yaml_record(SUBMITTED) == canonical  # the ruling, stated once

    result = asyncio.run(
        sg.submit_governance(
            working_dir=str(repo), octave_content=SUBMITTED, dry_run=False, review=False
        )
    )

    assert result["success"] is True, result
    assert result["pr_url"] == PR_URL
    assert result["target_path"] == f".hestai/decisions/{TOKEN}.md"
    branch = result["branch"]
    assert branch is not None

    # File bytes == canonical bytes (front matter canonical, body verbatim, CRs intact).
    on_branch = _git_bytes(repo, "show", f"{branch}:.hestai/decisions/{TOKEN}.md")
    assert on_branch == canonical.encode("utf-8")
    assert on_branch != SUBMITTED.encode("utf-8")
    # The MANIFEST regenerated by the linker indexes the .md record.
    manifest = _git(repo, "show", f"{branch}:.hestai/MANIFEST.md")
    assert f"| {TOKEN} | .hestai/decisions/{TOKEN}.md |" in manifest
    # The operator's own tree is untouched.
    assert not (repo / ".hestai" / "decisions" / f"{TOKEN}.md").exists()

    # Read it back as a consumer would: clone the pushed branch, lookup_decision.
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "--branch", branch, str(bare), str(clone))
    looked_up = lookup_decision(str(clone), TOKEN)
    assert looked_up["ok"] is True, looked_up
    record = looked_up["record"]
    assert record["token"] == TOKEN
    assert record["path"] == f".hestai/decisions/{TOKEN}.md"
    assert record["decision"] == CORE["DECISION"]
    assert record["status"] == "RATIFIED"

    # S2: write -> read -> emit is byte-identical to the file (body included).
    path = clone / ".hestai" / "decisions" / f"{TOKEN}.md"
    read_back = read_record(path)
    assert read_back.syntax == "yaml" and read_back.diagnostic is None
    assert canonicalize_yaml_record(path.read_bytes()) == path.read_bytes().decode("utf-8")
