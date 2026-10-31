"""RED suite: linker side of append_ruling on merged YAML topic records (issue #203 S2).

Base read (#173 slice-1 lesson):
  * fetch origin, then resolve ``origin/main`` to an OID EXACTLY ONCE;
  * locate the record by its declared TOKEN among the decision blobs AT THAT OID
    (``.md`` YAML records and ``.oct.md`` OCTAVE records, strict extension pairing;
    never the local tree), read its exact blob bytes, hash them;
  * every git call used is one whose valid answers all exit 0, so ANY non-zero
    exit is "undetermined" and the read refuses; stderr never decides.

Append path: a throwaway worktree cut from the OID (not a name), branch
``governance/<UTC-date>-<slug>-r<n>``, MANIFEST untouched, the written file read back
through the reader, the linker's existing push, one PR whose body quotes each VERBATIM.

Hermetic real-git fixtures (bare origin + clone, repo-local identity, pinned ``main``,
global/system config isolated); no network, gh is patched.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.tools.governance.linker as linker
from hestai_context_mcp.tools.governance.linker import (
    _token_to_slug,
    build_append_pr_body,
    compute_append_branch_name,
    find_in_flight_branches_at_oid,
    read_append_base,
    run_append_linker,
)

from ._append_fixtures import (
    OCTAVE_PATH,
    OCTAVE_TOKEN,
    PLAIN_PATH,
    PLAIN_TOKEN,
    TOPIC_PATH,
    TOPIC_RECORD,
    TOPIC_TOKEN,
    blob_bytes,
    git,
    init_topic_repo,
    isolate_git_env,
    push_branch,
    push_main_change,
)

pytestmark = pytest.mark.integration

_SLUG = _token_to_slug(TOPIC_TOKEN)


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_git_env(monkeypatch)


class _GitRecorder:
    """Wrap the linker's git runners; record every argv and every stdin they are given."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[list[str]] = []
        self.stdins: list[tuple[list[str], bytes]] = []
        real_text = linker._run_git
        real_bytes = linker._run_git_bytes

        def text_runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            self.calls.append(list(args))
            return real_text(args, cwd)

        def bytes_runner(
            args: list[str], cwd: Path, stdin: bytes | None = None
        ) -> tuple[int, bytes, str]:
            self.calls.append(list(args))
            if stdin is not None:
                self.stdins.append((list(args), stdin))
            return real_bytes(args, cwd, stdin)

        monkeypatch.setattr(linker, "_run_git", text_runner)
        monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)

    def naming(self, needle: str) -> list[list[str]]:
        """Calls whose argv OR stdin mentions ``needle``."""
        hits = [c for c in self.calls if any(needle in a for a in c)]
        hits += [c for c, data in self.stdins if needle.encode() in data and c not in hits]
        return hits

    def by(self, subcommand: str) -> list[list[str]]:
        return [c for c in self.calls if c and c[0] == subcommand]


# ---------------------------------------------------------------------------
# read_append_base
# ---------------------------------------------------------------------------


class TestReadAppendBase:
    def test_reads_blob_bytes_and_hash_at_origin_main(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path)
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code is None, base.error
        assert base.main_oid == git(["rev-parse", "origin/main"], repo)
        assert base.path == TOPIC_PATH
        assert base.data == TOPIC_RECORD.encode("utf-8")
        assert base.from_record_hash == "sha256:" + hashlib.sha256(base.data).hexdigest()

    def test_ignores_the_local_tree_and_local_commits(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path)
        # Uncommitted local edit AND an unpushed local commit: neither is main.
        (repo / TOPIC_PATH).write_text("local junk\n")
        git(["commit", "-am", "local only"], repo)
        (repo / TOPIC_PATH).write_text("more local junk\n")
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.data == TOPIC_RECORD.encode("utf-8")

    def test_fetches_before_reading(self, tmp_path: Path) -> None:
        repo, bare = init_topic_repo(tmp_path)
        updated = TOPIC_RECORD.replace("no exceptions", "no exceptions at all")
        new_oid = push_main_change(bare, tmp_path / "other", TOPIC_PATH, updated, "update")
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.main_oid == new_oid
        assert base.data == updated.encode("utf-8")

    def test_locates_record_by_token_not_by_file_name(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path, {".hestai/decisions/odd-name.md": TOPIC_RECORD})
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.path == ".hestai/decisions/odd-name.md"

    def test_preserves_bytes_exactly(self, tmp_path: Path) -> None:
        crlf = TOPIC_RECORD.replace("\n", "\r\n")
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: crlf})
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.data == crlf.encode("utf-8")
        assert base.data == blob_bytes(repo, "origin/main", TOPIC_PATH)

    def test_unknown_token_is_not_found(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path)
        base = read_append_base(repo, "TOPIC-NOWHERE-20261015")
        assert base.error_code == "TOKEN_NOT_FOUND_AT_MAIN"
        assert base.data is None and base.from_record_hash is None

    def test_token_only_in_the_markdown_body_is_not_found(self, tmp_path: Path) -> None:
        body_only = TOPIC_RECORD + 'token: "HO-BODY-ONLY-20261015"\n'
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: body_only})
        base = read_append_base(repo, "HO-BODY-ONLY-20261015")
        assert base.error_code == "TOKEN_NOT_FOUND_AT_MAIN"

    def test_yaml_front_matter_in_an_oct_md_file_is_not_a_record(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(
            tmp_path, {f".hestai/decisions/{TOPIC_TOKEN}.oct.md": TOPIC_RECORD}
        )
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code == "TOKEN_NOT_FOUND_AT_MAIN"

    def test_md_without_the_yaml_header_is_ignored(self, tmp_path: Path) -> None:
        readme = f'# Notes\n\ntoken: "{TOPIC_TOKEN}"\nTOKEN::{TOPIC_TOKEN}\n'
        repo, _ = init_topic_repo(
            tmp_path, {TOPIC_PATH: TOPIC_RECORD, ".hestai/decisions/README.md": readme}
        )
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code is None and base.path == TOPIC_PATH

    def test_token_declared_twice_is_ambiguous(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(
            tmp_path,
            {TOPIC_PATH: TOPIC_RECORD, ".hestai/decisions/copy.md": TOPIC_RECORD},
        )
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code == "TOKEN_AMBIGUOUS_AT_MAIN"
        assert TOPIC_PATH in (base.error or "")

    def test_octave_and_plain_records_are_located_for_the_renderer_to_refuse(
        self, tmp_path: Path
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        assert read_append_base(repo, OCTAVE_TOKEN).path == OCTAVE_PATH
        assert read_append_base(repo, PLAIN_TOKEN).path == PLAIN_PATH


class TestRefReadsAreCounted:
    """The #173 slice-1 lesson: resolve the ref ONCE; everything after uses the OID."""

    def test_origin_main_is_read_by_name_exactly_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        recorder = _GitRecorder(monkeypatch)
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code is None
        assert base.main_oid is not None
        assert recorder.naming("origin/main") == [["rev-parse", "--verify", "origin/main^{commit}"]]
        assert recorder.by("fetch") == [["fetch", "origin", "--prune"]]
        assert recorder.by("rev-parse") == [["rev-parse", "--verify", "origin/main^{commit}"]]
        # ls-tree names the OID, never a ref.
        assert recorder.by("ls-tree") == [
            ["ls-tree", "-r", "-z", base.main_oid, "--", ".hestai/decisions"]
        ]
        # cat-file reads blobs by blob OID only: no ref name, no <rev>:<path> through stdin.
        assert recorder.by("cat-file") == [["cat-file", "--batch"]]
        (argv, stdin), *rest = recorder.stdins
        assert argv == ["cat-file", "--batch"] and rest == []
        lines = stdin.decode("ascii").splitlines()
        assert lines and all(re.fullmatch(r"[0-9a-f]{40}", line) for line in lines), lines
        assert base.main_oid not in lines
        assert {c[0] for c in recorder.calls} == {"fetch", "rev-parse", "ls-tree", "cat-file"}


def _fail_on(monkeypatch: pytest.MonkeyPatch, subcommand: str, code: int) -> None:
    """Make every git call whose argv[0] == ``subcommand`` exit ``code``, empty stderr."""
    real_text = linker._run_git
    real_bytes = linker._run_git_bytes

    def text_runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
        if args and args[0] == subcommand:
            return code, "", ""
        return real_text(args, cwd)

    def bytes_runner(
        args: list[str], cwd: Path, stdin: bytes | None = None
    ) -> tuple[int, bytes, str]:
        if args and args[0] == subcommand:
            return code, b"", ""
        return real_bytes(args, cwd, stdin)

    monkeypatch.setattr(linker, "_run_git", text_runner)
    monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)


class TestExitZeroContract:
    @pytest.mark.parametrize("subcommand", ["fetch", "rev-parse", "ls-tree", "cat-file"])
    @pytest.mark.parametrize("code", [1, 128, 137])
    def test_any_non_zero_exit_is_undetermined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subcommand: str, code: int
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        _fail_on(monkeypatch, subcommand, code)
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code == "BASE_UNDETERMINED"
        assert base.data is None
        assert base.from_record_hash is None
        assert subcommand in (base.error or "")

    def test_missing_object_in_batch_output_is_undetermined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        real_bytes = linker._run_git_bytes

        def bytes_runner(
            args: list[str], cwd: Path, stdin: bytes | None = None
        ) -> tuple[int, bytes, str]:
            if args and args[0] == "cat-file" and stdin:
                first = stdin.split(b"\n", 1)[0]
                return 0, first + b" missing\n", ""
            return real_bytes(args, cwd, stdin)

        monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code == "BASE_UNDETERMINED"

    def test_truncated_batch_output_is_undetermined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        real_bytes = linker._run_git_bytes

        def bytes_runner(
            args: list[str], cwd: Path, stdin: bytes | None = None
        ) -> tuple[int, bytes, str]:
            code, out, err = real_bytes(args, cwd, stdin)
            if args and args[0] == "cat-file":
                return code, out[: len(out) // 2], err
            return code, out, err

        monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)
        base = read_append_base(repo, TOPIC_TOKEN)
        assert base.error_code == "BASE_UNDETERMINED"


# ---------------------------------------------------------------------------
# In-flight detection at the OID (reuses find_in_flight_branches' classifier)
# ---------------------------------------------------------------------------


class TestInFlightAtOid:
    def test_unmerged_append_branch_is_in_flight(self, tmp_path: Path) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s", f"governance/20261016-{_SLUG}-r4")
        git(["fetch", "origin"], repo)
        oid = git(["rev-parse", "origin/main"], repo)
        branches, err = find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert err is None
        assert branches == [f"governance/20261016-{_SLUG}-r4"]

    def test_unmerged_creation_branch_is_in_flight(self, tmp_path: Path) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s", f"governance/20261015-{_SLUG}")
        git(["fetch", "origin"], repo)
        oid = git(["rev-parse", "origin/main"], repo)
        branches, err = find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert err is None and branches == [f"governance/20261015-{_SLUG}"]

    def test_merged_append_branch_is_not_in_flight(self, tmp_path: Path) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s", f"governance/20261016-{_SLUG}-r4", merge=True)
        git(["fetch", "origin"], repo)
        oid = git(["rev-parse", "origin/main"], repo)
        branches, err = find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert err is None and branches == []

    def test_other_slugs_do_not_match(self, tmp_path: Path) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s1", f"governance/20261016-x{_SLUG}-r4")
        push_branch(bare, tmp_path / "s2", f"governance/20261016-{_SLUG}-rx")
        git(["fetch", "origin"], repo)
        oid = git(["rev-parse", "origin/main"], repo)
        branches, err = find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert err is None and branches == []

    def test_does_not_fetch_or_read_origin_main_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s", f"governance/20261016-{_SLUG}-r4")
        git(["fetch", "origin"], repo)
        oid = git(["rev-parse", "origin/main"], repo)
        recorder = _GitRecorder(monkeypatch)
        find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert not [c for c in recorder.calls if c[0] == "fetch"]
        assert not recorder.naming("origin/main")

    def test_non_zero_exit_is_undetermined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = git(["rev-parse", "origin/main"], repo)
        _fail_on(monkeypatch, "for-each-ref", 1)
        branches, err = find_in_flight_branches_at_oid(repo, TOPIC_TOKEN, TOPIC_PATH, oid)
        assert branches == []
        assert err is not None and err.startswith("IN_FLIGHT_UNDETERMINED: ")


# ---------------------------------------------------------------------------
# Branch name, PR body, append linker
# ---------------------------------------------------------------------------


def test_append_branch_name_shape() -> None:
    today = datetime.now(UTC).strftime("%Y%m%d")
    assert compute_append_branch_name(TOPIC_TOKEN, 4) == f"governance/{today}-{_SLUG}-r4"
    assert re.fullmatch(r"governance/\d{8}-.+-r12", compute_append_branch_name(TOPIC_TOKEN, 12))


def test_pr_body_quotes_each_verbatim_line() -> None:
    body = build_append_pr_body(
        token=TOPIC_TOKEN,
        pairs=[
            {"id": "R4", "rule": "Rule four.", "verbatim": 'first line\nsecond "quoted"'},
            {"id": "R5", "rule": "Rule five.", "verbatim": "five"},
        ],
        replaced_ids=["R2"],
        from_record_hash="sha256:" + "a" * 64,
        to_record_hash="sha256:" + "b" * 64,
        base_oid="c" * 40,
    )
    assert '> first line\n> second "quoted"' in body
    assert "> five" in body
    assert "Rule four." in body and "Rule five." in body
    assert "R2" in body
    assert "sha256:" + "a" * 64 in body and "sha256:" + "b" * 64 in body
    assert "c" * 40 in body
    assert "OCTAVE" not in body
    assert "YAML" in body


class _PrStub:
    def __init__(self, url: str | None = "https://github.com/o/r/pull/9", err: str | None = None):
        self.url, self.err = url, err
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, working_dir: Path, title: str, body: str, gh_token: str | None
    ) -> tuple[str | None, str | None]:
        self.calls.append({"cwd": working_dir, "title": title, "body": body})
        return self.url, self.err


_RENDERED = TOPIC_RECORD.replace(
    "---\n\n# Release notes",
    '  R4:\n    rule: "New."\n    verbatim: "new"\n    ruled: "x"\n---\n\n# Release notes',
)


def _run(
    repo: Path,
    oid: str,
    monkeypatch: pytest.MonkeyPatch,
    stub: _PrStub,
    record_text: str = _RENDERED,
) -> dict[str, Any]:
    monkeypatch.setattr(linker, "_open_append_pr", stub)
    return run_append_linker(
        repo,
        token=TOPIC_TOKEN,
        target_path=TOPIC_PATH,
        main_oid=oid,
        record_text=record_text,
        branch_name=f"governance/20261017-{_SLUG}-r4",
        appended_ids=["R4"],
        pr_body="body",
    )


class TestRunAppendLinker:
    def test_branch_is_cut_from_the_oid_not_the_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, bare = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        # origin/main moves AFTER the base was read; the branch must not follow it.
        push_main_change(bare, tmp_path / "o", "README.md", "moved\n", "move main")
        git(["fetch", "origin"], repo)
        out = _run(repo, oid, monkeypatch, _PrStub())
        assert out["error"] is None, out["error"]
        branch = f"governance/20261017-{_SLUG}-r4"
        assert git(["rev-parse", f"origin/{branch}^"], repo) == oid

    def test_commit_touches_only_the_record_and_uses_the_append_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        out = _run(repo, oid, monkeypatch, _PrStub())
        branch = out["branch"]
        assert branch == f"governance/20261017-{_SLUG}-r4"
        names = git(["show", "--name-only", "--format=", f"origin/{branch}"], repo).splitlines()
        assert names == [TOPIC_PATH]
        subject = git(["log", "-1", "--format=%s", f"origin/{branch}"], repo)
        assert subject == f"chore(governance): append ruling(s) R4 to {TOPIC_TOKEN}"
        assert blob_bytes(repo, f"origin/{branch}", TOPIC_PATH) == _RENDERED.encode("utf-8")
        assert out["head_sha"] == git(["rev-parse", f"origin/{branch}"], repo)

    def test_opens_one_pr_with_the_append_title(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        stub = _PrStub()
        out = _run(repo, oid, monkeypatch, stub)
        assert out["pr_url"] == "https://github.com/o/r/pull/9"
        assert len(stub.calls) == 1
        assert stub.calls[0]["title"] == f"feat(governance): append ruling(s) to {TOPIC_TOKEN}"
        assert stub.calls[0]["body"] == "body"

    def test_operator_tree_and_head_are_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        head_before = git(["rev-parse", "HEAD"], repo)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        _run(repo, oid, monkeypatch, _PrStub())
        assert git(["rev-parse", "HEAD"], repo) == head_before
        assert git(["status", "--porcelain"], repo) == ""
        assert (repo / TOPIC_PATH).read_bytes() == TOPIC_RECORD.encode("utf-8")
        assert len(git(["worktree", "list"], repo).splitlines()) == 1

    def test_read_back_rejection_aborts_before_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        pushed: list[str] = []
        monkeypatch.setattr(linker, "_push_branch", lambda wd, b: pushed.append(b))
        stub = _PrStub()
        bad = _RENDERED.replace('tier: "OPERATIONAL"', "tier: OPERATIONAL")
        out = _run(repo, oid, monkeypatch, stub, record_text=bad)
        assert out["error"] and "read-back" in out["error"] and "unquoted_value" in out["error"]
        assert pushed == [] and stub.calls == []
        assert out["branch"] is None
        assert git(["branch", "--list", f"governance/20261017-{_SLUG}-r4"], repo) == ""

    def test_failed_head_resolve_after_commit_refuses_before_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = git(["rev-parse", "origin/main"], repo)
        real = linker._run_git

        def runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            if args == ["rev-parse", "--verify", "HEAD^{commit}"]:
                return 128, "", ""
            return real(args, cwd)

        monkeypatch.setattr(linker, "_run_git", runner)
        pushed: list[str] = []
        monkeypatch.setattr(linker, "_push_branch", lambda wd, b: pushed.append(b))
        stub = _PrStub()
        out = _run(repo, oid, monkeypatch, stub)
        assert out["error"] is not None
        assert out["error"].startswith("LINKER_FAILED: ")
        assert "rev-parse HEAD" in out["error"]
        assert pushed == [] and stub.calls == []
        assert out["branch"] is None and out["pr_url"] is None and out["head_sha"] is None
        assert git(["branch", "--list", f"governance/20261017-{_SLUG}-r4"], repo) == ""

    def test_push_failure_rolls_back_the_local_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        monkeypatch.setattr(linker, "_push_branch", lambda wd, b: "Failed to push: nope")
        stub = _PrStub()
        out = _run(repo, oid, monkeypatch, stub)
        assert out["error"] and "Failed to push" in out["error"]
        assert out["branch"] is None and out["pr_url"] is None
        assert stub.calls == []
        assert git(["branch", "--list", f"governance/20261017-{_SLUG}-r4"], repo) == ""

    def test_pr_failure_is_reported_and_branch_kept_on_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = read_append_base(repo, TOPIC_TOKEN).main_oid
        assert oid is not None
        out = _run(repo, oid, monkeypatch, _PrStub(url=None, err="gh pr create failed: x"))
        assert out["error"] == "gh pr create failed: x"
        assert out["branch"] == f"governance/20261017-{_SLUG}-r4"

    def test_target_path_outside_repo_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        oid = git(["rev-parse", "origin/main"], repo)
        monkeypatch.setattr(linker, "_open_append_pr", _PrStub())
        out = run_append_linker(
            repo,
            token=TOPIC_TOKEN,
            target_path="../escape.md",
            main_oid=oid,
            record_text="x",
            branch_name="governance/20261017-x-r1",
            appended_ids=["R1"],
            pr_body="b",
        )
        assert out["error"] and "path traversal" in out["error"]


def test_open_append_pr_passes_title_body_and_pinned_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(argv, 0, "https://github.com/o/r/pull/3\n", "")

    monkeypatch.setattr(linker.subprocess, "run", fake_run)
    url, err = linker._open_append_pr(tmp_path, "T", "B", "tok")
    assert (url, err) == ("https://github.com/o/r/pull/3", None)
    assert seen["argv"] == ["gh", "pr", "create", "--title", "T", "--body", "B", "--base", "main"]
    assert seen["env"]["GH_TOKEN"] == "tok"


def test_push_branch_fixture_fails_fast_on_a_missing_edit_path(tmp_path: Path) -> None:
    """A typo in ``edit`` must not silently push a branch that edits nothing."""
    _, bare = init_topic_repo(tmp_path)
    with pytest.raises(FileNotFoundError, match="no-such-record.md"):
        push_branch(
            bare, tmp_path / "s", "governance/20261016-x-r1", edit=".hestai/no-such-record.md"
        )
