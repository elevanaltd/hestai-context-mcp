"""EPIC4 PR-5 phase 1C (RED): the linker and intake_context read records via ``read_record``.

hc #220 item 5: ``read_text`` applies universal newlines, which folds ``\\r\\r\\n`` into a
valid fence. PR-4's ``read_record`` re-reads a YAML record as raw bytes; the PR-5 write
path must route through it.

* intake_context (prose-mode context) reads every record through ``read_record`` and,
  because prose mode stays OCTAVE, keeps YAML out of the few-shot corpus (strict
  ``.oct.md``/``.md`` pairing, as ``assemble_context`` already does).
* the linker reads the record it just wrote back through ``read_record`` (inside the
  throwaway worktree, before the commit) and refuses to commit bytes the reader rejects.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    emit_yaml_record,
    read_record,
)
from hestai_context_mcp.tools.governance import intake_context, linker
from hestai_context_mcp.tools.governance.type_checker import validate_record_content

from ._agr_fixtures import write_record, write_yaml_record

pytestmark = pytest.mark.unit

TOKEN = "HO-ESCAPES-20261029"
OCT = "HO-CUBIC-A-20260101"
YAML_OTHER = "HO-CUBIC-T-20260301"

CORE = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.4",
    "TOKEN": TOKEN,
    "STATUS": "RATIFIED",
    "TIER": "STRATEGIC",
    "AUTHORED_AT": "2026-10-29T00:00:00Z",
    "DECISION": "A binding decision sentence.",
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


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> MagicMock:
    spy = MagicMock(side_effect=read_record)
    monkeypatch.setattr(module, "read_record", spy, raising=False)
    return spy


# --- intake_context ---------------------------------------------------------------


def test_intake_context_reads_every_decision_file_through_read_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_record(tmp_path, token=OCT, authored_at="2026-01-01T00:00:00Z")
    spy = _spy(monkeypatch, intake_context)
    intake_context.assemble_intake_context(tmp_path, "prose")
    paths = {call.args[0].name for call in spy.call_args_list}
    assert f"{OCT}.oct.md" in paths


def test_a_yaml_front_matter_file_named_oct_md_is_not_in_the_corpus(tmp_path: Path) -> None:
    write_record(tmp_path, token=OCT, authored_at="2026-01-01T00:00:00Z")
    write_yaml_record(tmp_path, token=YAML_OTHER, filename=f"{YAML_OTHER}.oct.md")
    ctx = intake_context.assemble_intake_context(tmp_path, "prose")
    assert OCT in ctx.corpus
    assert YAML_OTHER not in ctx.corpus  # strict pairing: .oct.md is OCTAVE-only


def test_pin_yaml_records_stay_out_of_the_octave_prose_corpus(tmp_path: Path) -> None:
    write_record(tmp_path, token=OCT, authored_at="2026-01-01T00:00:00Z")
    write_yaml_record(tmp_path, token=YAML_OTHER)
    ctx = intake_context.assemble_intake_context(tmp_path, "prose")
    assert YAML_OTHER not in ctx.corpus


# --- linker -----------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _hermetic_repo(repo: Path) -> None:
    """Repo with a real bare origin, repo-local identity, hooks off, branch main (CI has none)."""
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "core.hooksPath", str(repo / ".git" / "no-hooks"))
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    bare = repo.parent / f"{repo.name}-origin.git"
    _git(repo.parent, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in _SCRUB:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _hermetic_repo(root)
    return root


def _run(
    repo: Path, content: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], MagicMock]:
    validation = validate_record_content(repo, content)
    assert validation.valid, validation.errors
    open_pr = MagicMock(
        return_value=("https://github.com/elevanaltd/hestai-context-mcp/pull/1", None)
    )
    monkeypatch.setattr(linker, "_open_pr", open_pr)
    out = linker.run_linker(
        working_dir=repo, validation=validation, octave_content=content, dry_run=False
    )
    return out, open_pr


def test_linker_reads_the_written_yaml_record_back_through_read_record(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _spy(monkeypatch, linker)
    out, _ = _run(repo, emit_yaml_record(CORE, None, None), monkeypatch)
    assert out["error"] is None, out
    read = [call.args[0] for call in spy.call_args_list]
    # the read-back happens in the throwaway worktree, never in the operator's tree
    assert any(p.name == f"{TOKEN}.md" and repo not in p.parents for p in read)


def test_linker_refuses_to_commit_a_record_the_reader_rejects(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write: Callable[[Path, str], str | None] = linker._write_file

    def corrupting_write(target: Path, content: str) -> str | None:
        # What a newline-folding write could produce: a doubled CR on the closing fence.
        return real_write(target, content.replace("\n---\n", "\n---\r\r\n"))

    monkeypatch.setattr(linker, "_write_file", corrupting_write)
    out, open_pr = _run(repo, emit_yaml_record(CORE, None, None), monkeypatch)
    assert out["error"] is not None and "read-back" in out["error"]
    assert out["branch"] is None
    open_pr.assert_not_called()
    # nothing reached origin and the base commit is untouched
    heads = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert [line.split("\t")[1] for line in heads.splitlines()] == ["refs/heads/main"]
    count = subprocess.run(
        ["git", "rev-list", "--all", "--count"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert count == "1"
