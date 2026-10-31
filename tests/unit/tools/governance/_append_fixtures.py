"""Shared hermetic real-git fixtures for the append_ruling suites (issue #203 S2).

A bare ``origin`` plus a clone, both with repo-local identity, a pinned ``main``
symbolic ref, hooks disabled, autocrlf and gpgsign off, and the developer's / CI's
global and system git config isolated (``isolate_git_env``), so the suites run the
same on a laptop and in CI with no network. The records are fake governance
fixtures: no client, finance or staff data.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

TOPIC_TOKEN = "TOPIC-RELEASE-NOTES-20261015"
TOPIC_PATH = f".hestai/decisions/topics/{TOPIC_TOKEN}.md"

# Canonical quoted-YAML topic record (ADR-RFC-ARCH-004 §1.1, §1.7) plus a body.
TOPIC_RECORD = (
    "---\n"
    'type: "DECISION_RECORD"\n'
    'version: "1.5"\n'
    f'token: "{TOPIC_TOKEN}"\n'
    'status: "RATIFIED"\n'
    'tier: "OPERATIONAL"\n'
    'authored_at: "2026-10-15T00:00:00Z"\n'
    'decision: "The release-notes rules in force are the ones listed under current."\n'
    'because: "One long-running record per topic keeps the current rules in one place."\n'
    'revision: "2026-10-15: R2 added; R2 replaces R1"\n'
    'topic: "release-notes"\n'
    'ratified_by: "human:operator<fixture>"\n'
    "current:\n"
    '  R2: "Release notes ship with every tagged build."\n'
    '  R3: "Notes name the issue for each change."\n'
    "rulings:\n"
    "  R2:\n"
    '    rule: "Release notes ship with every tagged build."\n'
    '    verbatim: "every tag gets notes, no exceptions"\n'
    '    ruled: "Fixture operator, 2026-10-15, fixture session"\n'
    '    replaces: "R1"\n'
    "  R3:\n"
    '    rule: "Notes name the issue for each change."\n'
    '    verbatim: "link the issue on every line"\n'
    '    ruled: "Fixture operator, 2026-10-15, fixture session"\n'
    "---\n"
    "\n# Release notes\n\nFixture body, kept byte for byte.\n"
)

PLAIN_TOKEN = "HO-PLAIN-RECORD-20261015"
PLAIN_PATH = f".hestai/decisions/{PLAIN_TOKEN}.md"
PLAIN_RECORD = (
    "---\n"
    'type: "DECISION_RECORD"\n'
    'version: "1.5"\n'
    f'token: "{PLAIN_TOKEN}"\n'
    'status: "RATIFIED"\n'
    'tier: "OPERATIONAL"\n'
    'authored_at: "2026-10-15T00:00:00Z"\n'
    'decision: "A plain record without a topic."\n'
    'because: "Fixture for the not-a-topic refusal."\n'
    'ratified_by: "human:operator<fixture>"\n'
    "---\n"
)

OCTAVE_TOKEN = "TOPIC-OCTAVE-FORM-20261015"
OCTAVE_PATH = f".hestai/decisions/{OCTAVE_TOKEN}.oct.md"
OCTAVE_RECORD = f"""===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.3"
  TOKEN::{OCTAVE_TOKEN}
  TOPIC::octave-form
  STATUS::RATIFIED
  TIER::OPERATIONAL
  AUTHORED_AT::"2026-10-15T00:00:00Z"
  DECISION::"An OCTAVE topic record."
  BECAUSE::"Fixture for the YAML-only refusal."
  RATIFIED_BY::"human:operator<fixture>"
CURRENT:
  R1::"A rule."
RULINGS:
  R1:
    RULE::"A rule."
    VERBATIM::"a rule"
    RULED::"Fixture operator"
===END===
"""

_SCRUB = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_COUNT",
    "GIT_DIR",
    "GIT_WORK_TREE",
)


def isolate_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub git/gh env and isolate global and system git config (main's F5 pattern)."""
    for var in _SCRUB:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _configure(repo: Path, email: str = "test@test.com", name: str = "Test") -> None:
    git(["config", "core.hooksPath", str(repo / ".git" / "no-hooks")], repo)
    git(["config", "user.email", email], repo)
    git(["config", "user.name", name], repo)
    git(["config", "user.useConfigOnly", "true"], repo)
    git(["config", "core.autocrlf", "false"], repo)
    git(["config", "commit.gpgsign", "false"], repo)


def init_topic_repo(tmp_path: Path, records: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Create ``origin.git`` (bare) and a clone ``repo`` whose main holds ``records``.

    ``records`` maps repo-relative paths to file text; defaults to the YAML topic
    record, a plain (non-topic) YAML record and an OCTAVE topic record.
    """
    if records is None:
        records = {TOPIC_PATH: TOPIC_RECORD, PLAIN_PATH: PLAIN_RECORD, OCTAVE_PATH: OCTAVE_RECORD}
    repo = tmp_path / "repo"
    bare = tmp_path / "origin.git"
    repo.mkdir()
    git(["init"], repo)
    _configure(repo)
    (repo / "README.md").write_text("fixture\n")
    manifest = repo / ".hestai" / "MANIFEST.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("| TOKEN | path |\n|---|---|\n")
    for rel, text in records.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    git(["add", "."], repo)
    git(["commit", "-m", "initial"], repo)
    git(["branch", "-M", "main"], repo)
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    git(["symbolic-ref", "HEAD", "refs/heads/main"], bare)
    git(["remote", "add", "origin", str(bare)], repo)
    git(["push", "-u", "origin", "main"], repo)
    return repo, bare


def second_session_clone(bare: Path, dest: Path) -> Path:
    """Clone ``bare`` as a separate session (pushes the primary clone never sees)."""
    subprocess.run(["git", "clone", str(bare), str(dest)], check=True, capture_output=True)
    _configure(dest, email="other@test.com", name="Other")
    return dest


def push_main_change(bare: Path, dest: Path, rel: str, text: str, message: str) -> str:
    """From a second session, commit ``text`` at ``rel`` on main and push it."""
    scratch = second_session_clone(bare, dest)
    target = scratch / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    git(["add", rel], scratch)
    git(["commit", "-m", message], scratch)
    git(["push", "origin", "main"], scratch)
    return git(["rev-parse", "HEAD"], scratch)


def push_branch(
    bare: Path, dest: Path, branch: str, *, merge: bool = False, edit: str | None = TOPIC_PATH
) -> None:
    """From a second session, push ``branch`` (one commit) to origin.

    The commit edits the record at ``edit`` (in its markdown body, as a real
    creation or append branch changes the file), so the content-match merged
    signal does not clear it; ``edit=None`` pushes a marker file only. A missing
    ``edit`` path raises ``FileNotFoundError`` rather than silently editing nothing.
    """
    scratch = second_session_clone(bare, dest)
    if edit is not None and not (scratch / edit).is_file():
        raise FileNotFoundError(f"push_branch: edit path {edit} does not exist on main")
    git(["checkout", "-b", branch, "origin/main"], scratch)
    (scratch / f"marker-{branch.replace('/', '-')}.txt").write_text("marker\n")
    if edit is not None:
        with (scratch / edit).open("a", encoding="utf-8") as fh:
            fh.write(f"pending change on {branch}\n")
    git(["add", "."], scratch)
    git(["commit", "-m", f"marker {branch}"], scratch)
    git(["push", "origin", branch], scratch)
    if merge:
        git(["checkout", "main"], scratch)
        git(["merge", "--no-ff", branch, "-m", "merge"], scratch)
        git(["push", "origin", "main"], scratch)


def blob_bytes(repo: Path, ref: str, rel: str) -> bytes:
    """Exact bytes of ``rel`` at ``ref`` (no text decoding)."""
    return subprocess.run(
        ["git", "show", f"{ref}:{rel}"], cwd=str(repo), check=True, capture_output=True
    ).stdout
