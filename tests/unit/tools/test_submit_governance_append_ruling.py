"""RED suite: submit_governance ``append_ruling`` on merged YAML topic records (#203 S2).

End-to-end over hermetic real git (bare origin + clone, global/system config isolated);
only gh and the reviewer are stubbed. Covers the mode guard, the structured refusals,
CAS on the origin/main OID, dry_run, the one-PR live path, the single ref read across
the whole call, the Stage-5 RULE-vs-VERBATIM review, and the hard condition that
Gate A's ``existing_record`` is reachable only from this mode.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.tools.governance.linker as linker
import hestai_context_mcp.tools.submit_governance as sg
from hestai_context_mcp.core.agent_readable_governance_parser import (
    canonicalize_yaml_record,
    collect_topic_blocks,
)
from hestai_context_mcp.tools.governance.linker import _token_to_slug
from hestai_context_mcp.tools.submit_governance import submit_governance

from .governance._append_fixtures import (
    OCTAVE_TOKEN,
    PLAIN_PATH,
    PLAIN_RECORD,
    PLAIN_TOKEN,
    TOPIC_PATH,
    TOPIC_RECORD,
    TOPIC_TOKEN,
    blob_bytes,
    git,
    init_topic_repo,
    isolate_git_env,
    push_branch,
)

pytestmark = pytest.mark.integration

_PR_URL = "https://github.com/owner/name/pull/42"
_SLUG = _token_to_slug(TOPIC_TOKEN)
_VERBATIM = 'ship notes for hotfixes too, "even tiny ones"\nno exceptions \\ none\tok'


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_git_env(monkeypatch)


def _request(**overrides: Any) -> dict[str, Any]:
    req: dict[str, Any] = {
        "topic_token": TOPIC_TOKEN,
        "rulings": [
            {
                "rule": "Hotfix builds ship release notes too.",
                "verbatim": _VERBATIM,
                "ruled": "Fixture operator, 2026-10-31, fixture session, ceremony f00",
                "replaces": None,
            }
        ],
        "expected_record_hash": None,
    }
    req.update(overrides)
    return req


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _PrStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, working_dir: Path, title: str, body: str, gh_token: str | None
    ) -> tuple[str | None, str | None]:
        self.calls.append({"title": title, "body": body})
        return _PR_URL, None


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pr = _PrStub()
    reviews: list[Any] = []
    posts: list[dict[str, Any]] = []

    async def fake_fidelity(pairs: Any, **kwargs: Any) -> dict[str, Any]:
        reviews.append(list(pairs))
        return {
            "verdict": "APPROVED",
            "assessment": "Each rule states its verbatim faithfully.",
            "concerns": [],
            "reviewer_available": True,
            "metrics": {"tokens": 1, "cost": 0.0, "model": "m", "cost_is_estimate": True},
            "fidelity_pairs": [],
        }

    async def forbidden_review(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the whole-record reviewer must not run for appends")

    def fake_submit(**kwargs: Any) -> dict[str, Any]:
        posts.append(kwargs)
        return {"status": "ok", "comment_url": "https://github.com/owner/name/pull/42#c1"}

    monkeypatch.setattr(linker, "_open_append_pr", pr)
    monkeypatch.setattr(linker, "_resolve_github_token", lambda: None)
    monkeypatch.setattr(
        linker,
        "_resolve_open_pr_urls",
        lambda wd, branches, tok: (
            {b: f"https://github.com/o/r/pull/{i}" for i, b in enumerate(branches)},
            None,
        ),
    )
    monkeypatch.setattr(sg, "review_ruling_fidelity", fake_fidelity)
    monkeypatch.setattr(sg, "review_governance", forbidden_review)
    monkeypatch.setattr(sg, "submit_review", fake_submit)
    monkeypatch.setattr(sg, "_resolve_pr_head_sha", lambda repo, n: "d" * 40)
    return {"pr": pr, "reviews": reviews, "posts": posts}


# ---------------------------------------------------------------------------
# Mode guard and signature
# ---------------------------------------------------------------------------


def test_signature_has_append_ruling_and_no_existing_record_parameter() -> None:
    params = inspect.signature(submit_governance).parameters
    assert params["append_ruling"].default is None
    assert "existing_record" not in params


class TestModeGuard:
    @pytest.mark.parametrize(
        "other",
        [
            {"octave_content": "x"},
            {"prose_input": "x"},
            {"octave_content": "x", "prose_input": "y"},
        ],
    )
    async def test_append_is_mutually_exclusive(
        self, tmp_path: Path, other: dict[str, str]
    ) -> None:
        result = await submit_governance(str(tmp_path), append_ruling=_request(), **other)
        assert result["success"] is False
        assert any("append_ruling" in e for e in result["validation_errors"])

    @pytest.mark.parametrize(
        "extra",
        [
            {"octave_content": "x"},
            {"prose_input": "x"},
            {"write_adr": True},
        ],
    )
    async def test_early_refusals_use_the_append_result_shape(
        self, tmp_path: Path, extra: dict[str, Any]
    ) -> None:
        reference = await submit_governance(
            str(tmp_path), append_ruling=_request(topic_token="not-a-token")
        )
        assert reference["error_code"] == "APPEND_INPUT_INVALID"
        result = await submit_governance(str(tmp_path), append_ruling=_request(), **extra)
        assert set(result) == set(reference)
        assert result["success"] is False
        assert result["error_code"] == "APPEND_MODE_CONFLICT"
        assert result["token"] is None and result["appended_ids"] == []

    async def test_neither_mode_keeps_the_existing_message(self, tmp_path: Path) -> None:
        result = await submit_governance(str(tmp_path))
        assert result["validation_errors"] == [
            "Exactly one of 'octave_content' or 'prose_input' must be provided "
            "(received neither or both)."
        ]

    async def test_write_adr_is_refused_with_append(self, tmp_path: Path) -> None:
        result = await submit_governance(str(tmp_path), append_ruling=_request(), write_adr=True)
        assert result["success"] is False
        assert any("write_adr" in e for e in result["validation_errors"])

    async def test_invalid_input_is_refused_before_any_git(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("no git before input validation")

        monkeypatch.setattr(sg, "read_append_base", boom)
        bad = _request(rulings=[{"rule": "", "verbatim": "v", "ruled": "r", "replaces": None}])
        result = await submit_governance(str(tmp_path), append_ruling=bad)
        assert result["success"] is False
        assert result["error_code"] == "APPEND_INPUT_INVALID"

    async def test_rule_with_symbols_is_refused(self, tmp_path: Path) -> None:
        bad = _request()
        bad["rulings"][0]["rule"] = "Hotfixes → notes."
        result = await submit_governance(str(tmp_path), append_ruling=bad)
        assert result["error_code"] == "APPEND_INPUT_INVALID"
        assert any("plain words" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# existing_record is reachable ONLY from append_ruling (hard condition)
# ---------------------------------------------------------------------------


class TestExistingRecordReachability:
    async def test_content_mode_still_refuses_an_existing_yaml_token(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), octave_content=TOPIC_RECORD, dry_run=True)
        assert result["success"] is False
        assert any(TOPIC_TOKEN in e and "already exists" in e for e in result["validation_errors"])

    async def test_content_mode_refuses_an_existing_record_rewritten(self, tmp_path: Path) -> None:
        repo, _ = init_topic_repo(tmp_path)
        rewritten = TOPIC_RECORD.replace("no exceptions", "no exceptions, overwritten")
        result = await submit_governance(str(repo), octave_content=rewritten, review=False)
        assert result["success"] is False
        assert any("already exists" in e for e in result["validation_errors"])

    def test_existing_record_keyword_is_passed_only_from_the_append_path(self) -> None:
        """Every call in src/ that passes ``existing_record`` (any value), with the
        innermost function enclosing it: the append path, plus the ONE pass-through
        inside ``validate_record_content``. Module-level calls count too."""
        src = Path(sg.__file__).resolve().parents[1]
        found: list[tuple[str, str]] = []

        class _Calls(ast.NodeVisitor):
            def __init__(self, rel: str) -> None:
                self.rel, self.stack = rel, ["<module>"]

            def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._function(node)

            def visit_Call(self, node: ast.Call) -> None:
                if any(kw.arg == "existing_record" for kw in node.keywords):
                    found.append((self.rel, self.stack[-1]))
                self.generic_visit(node)

        for path in sorted(src.rglob("*.py")):
            rel = path.relative_to(src).as_posix()
            _Calls(rel).visit(ast.parse(path.read_text(encoding="utf-8")))
        assert sorted(found) == [
            ("tools/governance/type_checker.py", "validate_record_content"),
            ("tools/submit_governance.py", "_submit_append_ruling"),
        ]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    async def test_token_not_found_at_main(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(
            str(repo), append_ruling=_request(topic_token="TOPIC-ABSENT-20261015")
        )
        assert result["success"] is False
        assert result["error_code"] == "TOKEN_NOT_FOUND_AT_MAIN"
        assert stubs["pr"].calls == []

    async def test_record_only_in_local_tree_is_not_found(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path, {"README2.md": "x\n"})
        local = repo / TOPIC_PATH
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(TOPIC_RECORD)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["error_code"] == "TOKEN_NOT_FOUND_AT_MAIN"

    async def test_octave_topic_record_is_refused(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(
            str(repo), append_ruling=_request(topic_token=OCTAVE_TOKEN)
        )
        assert result["success"] is False
        assert result["error_code"] == "NOT_YAML_TOPIC_RECORD"
        assert any(
            "append_ruling writes YAML topic records only" in e for e in result["validation_errors"]
        )
        assert stubs["pr"].calls == []

    async def test_non_topic_record_cannot_be_overwritten(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request(topic_token=PLAIN_TOKEN))
        assert result["success"] is False
        assert result["error_code"] == "NOT_A_TOPIC_RECORD"
        assert result["rendered_record"] is None
        assert stubs["pr"].calls == []
        dry = await submit_governance(
            str(repo), append_ruling=_request(topic_token=PLAIN_TOKEN), dry_run=True
        )
        assert dry["error_code"] == "NOT_A_TOPIC_RECORD"
        assert blob_bytes(repo, "origin/main", PLAIN_PATH) == PLAIN_RECORD.encode("utf-8")
        assert git(["ls-remote", "--heads", "origin"], repo).count("refs/heads/") == 1

    async def test_unreadable_yaml_record_is_refused(self, tmp_path: Path, stubs) -> None:
        broken = TOPIC_RECORD.replace('tier: "OPERATIONAL"', "tier: OPERATIONAL")
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: broken})
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["error_code"] == "RECORD_UNREADABLE"

    async def test_expected_hash_mismatch_carries_both_hashes(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        stale = "sha256:" + "0" * 64
        result = await submit_governance(
            str(repo), append_ruling=_request(expected_record_hash=stale)
        )
        assert result["success"] is False
        assert result["error_code"] == "EXPECTED_HASH_MISMATCH"
        assert result["expected_record_hash"] == stale
        assert result["from_record_hash"] == _hash(TOPIC_RECORD.encode("utf-8"))
        assert any(
            stale in e and result["from_record_hash"] in e for e in result["validation_errors"]
        )
        assert stubs["pr"].calls == []

    async def test_stale_hash_wins_over_an_unknown_replaces_id(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        req = _request(expected_record_hash="sha256:" + "0" * 64)
        req["rulings"][0]["replaces"] = ["R9"]
        result = await submit_governance(str(repo), append_ruling=req)
        assert result["error_code"] == "EXPECTED_HASH_MISMATCH"

    async def test_in_flight_record_is_refused_naming_branches(self, tmp_path: Path, stubs) -> None:
        repo, bare = init_topic_repo(tmp_path)
        branch = f"governance/20261016-{_SLUG}-r4"
        push_branch(bare, tmp_path / "s", branch)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is False
        assert result["error_code"] == "TOPIC_RECORD_IN_FLIGHT"
        assert result["in_flight"] is True
        assert result["in_flight_branches"] == [branch]
        assert result["in_flight_pr_urls"] == {branch: "https://github.com/o/r/pull/0"}
        message = " ".join(result["validation_errors"])
        assert branch in message and "S3" in message
        assert stubs["pr"].calls == []

    async def test_replaces_unknown_id(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        req = _request()
        req["rulings"][0]["replaces"] = ["R1"]  # R1 was already replaced by R2
        result = await submit_governance(str(repo), append_ruling=req)
        assert result["error_code"] == "REPLACES_UNKNOWN_ID"

    async def test_validation_failure_on_the_rendered_record(self, tmp_path: Path, stubs) -> None:
        long_because = " ".join(["word"] * 41)
        broken = canonicalize_yaml_record(
            TOPIC_RECORD.replace(
                "One long-running record per topic keeps the current rules in one place.",
                long_because,
            )
        )
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: broken})
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["error_code"] == "VALIDATION_FAILED"
        assert any("BECAUSE" in e for e in result["validation_errors"])
        assert stubs["pr"].calls == []

    @pytest.mark.parametrize("subcommand", ["fetch", "rev-parse", "ls-tree", "cat-file"])
    async def test_undetermined_base_is_refused(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch, subcommand: str
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        real_text, real_bytes = linker._run_git, linker._run_git_bytes

        def runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            if args[:1] == [subcommand]:
                return 128, "", ""
            return real_text(args, cwd)

        def bytes_runner(
            args: list[str], cwd: Path, stdin: bytes | None = None
        ) -> tuple[int, bytes, str]:
            if args[:1] == [subcommand]:
                return 128, b"", ""
            return real_bytes(args, cwd, stdin)

        monkeypatch.setattr(linker, "_run_git", runner)
        monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["error_code"] == "BASE_UNDETERMINED"
        assert result["from_record_hash"] is None
        assert stubs["pr"].calls == []

    async def test_undetermined_in_flight_check_is_refused(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        real = linker._run_git

        def runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            if args[:1] == ["for-each-ref"]:
                return 1, "", ""
            return real(args, cwd)

        monkeypatch.setattr(linker, "_run_git", runner)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["error_code"] == "IN_FLIGHT_UNDETERMINED"
        assert result["in_flight"] is None
        assert stubs["pr"].calls == []


# ---------------------------------------------------------------------------
# TOKEN uniqueness at the pinned main OID (CE 6538573589)
# ---------------------------------------------------------------------------

_TWIN_NAMED = f".hestai/decisions/legacy/{TOPIC_TOKEN}.oct.md"
_CONCEPT_NAMED = f".hestai/context/concepts/{TOPIC_TOKEN}.oct.md"
_OCTAVE_TWIN = (
    "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
    f'  VERSION::"1.0"\n  TOKEN::{TOPIC_TOKEN}\n  STATUS::RATIFIED\n  TIER::OPERATIONAL\n'
    '  AUTHORED_AT::"2026-10-15T00:00:00Z"\n  DECISION::"d"\n  BECAUSE::"b"\n===END===\n'
)
_CITER_OCTAVE = (
    "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n  TOKEN::HO-CITES-THE-TOPIC-20261015\n  STATUS::RATIFIED\n'
    '  TIER::OPERATIONAL\n  AUTHORED_AT::"2026-10-15T00:00:00Z"\n'
    f'  DECISION::"Follows {TOPIC_TOKEN}."\n  BECAUSE::"b"\n'
    f"  AMENDS::[{TOPIC_TOKEN}]\n  RELATED_DECISIONS::[{TOPIC_TOKEN},HO-OTHER-20261015]\n"
    f'  AUTHORITY::"{TOPIC_TOKEN} (RATIFIED)"\n===END===\n'
)
_CITER_YAML = PLAIN_RECORD.replace(
    'ratified_by: "human:operator<fixture>"\n',
    f'ratified_by: "human:operator<fixture>"\nrelated_decisions: "{TOPIC_TOKEN}"\n',
).replace(PLAIN_TOKEN, "HO-CITES-IN-YAML-20261015") + (
    f'\nBody quoting the topic: token: "{TOPIC_TOKEN}"\nTOKEN::{TOPIC_TOKEN}\n'
)


def _stale_checkout(repo: Path) -> None:
    """Drop every record from the local checkout (an unpushed local commit): main keeps them."""
    git(["rm", "-r", "-q", ".hestai/decisions"], repo)
    if (repo / ".hestai" / "context").exists():
        git(["rm", "-r", "-q", ".hestai/context"], repo)
    git(["commit", "-q", "-m", "stale local checkout"], repo)


class TestUniquenessAtMain:
    async def _refused(self, repo: Path, stubs, *paths: str) -> None:
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is False, result
        assert result["error_code"] == "TOKEN_AMBIGUOUS_AT_MAIN"
        message = " ".join(result["validation_errors"])
        for path in (TOPIC_PATH, *paths):
            assert path in message, message
        assert stubs["pr"].calls == []
        assert git(["ls-remote", "--heads", "origin"], repo).count("refs/heads/") == 1

    async def test_a_stale_checkout_with_a_same_name_twin_at_main_is_refused(
        self, tmp_path: Path, stubs
    ) -> None:
        # (a) the twin is named for the TOKEN but is not a record (does not declare it).
        repo, _ = init_topic_repo(
            tmp_path, {TOPIC_PATH: TOPIC_RECORD, _TWIN_NAMED: "not a record at all\n"}
        )
        _stale_checkout(repo)
        await self._refused(repo, stubs, _TWIN_NAMED)

    async def test_a_stale_checkout_with_an_unpaired_declaring_twin_at_main_is_refused(
        self, tmp_path: Path, stubs
    ) -> None:
        # (a) an .oct.md holding YAML front matter that declares the TOKEN: not a record
        # under the readers' pairing, but its raw text declares the TOKEN.
        twin = ".hestai/decisions/legacy/odd-twin.oct.md"
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: TOPIC_RECORD, twin: TOPIC_RECORD})
        _stale_checkout(repo)
        await self._refused(repo, stubs, twin)

    async def test_a_same_name_file_under_concepts_at_main_is_refused(
        self, tmp_path: Path, stubs
    ) -> None:
        # (b)
        repo, _ = init_topic_repo(
            tmp_path, {TOPIC_PATH: TOPIC_RECORD, _CONCEPT_NAMED: "concept card text\n"}
        )
        await self._refused(repo, stubs, _CONCEPT_NAMED)

    async def test_a_concept_declaring_the_token_at_main_is_refused(
        self, tmp_path: Path, stubs
    ) -> None:
        # (b) by declaration rather than by name.
        concept = ".hestai/context/concepts/card.oct.md"
        repo, _ = init_topic_repo(
            tmp_path,
            {
                TOPIC_PATH: TOPIC_RECORD,
                concept: f"===CONCEPT_CARD===\nMETA:\n  ID::{TOPIC_TOKEN}\n",
            },
        )
        _stale_checkout(repo)
        await self._refused(repo, stubs, concept)

    async def test_a_well_formed_octave_twin_at_main_is_refused(
        self, tmp_path: Path, stubs
    ) -> None:
        # (c) pinned: the record locator already sees this twin.
        twin = f".hestai/decisions/{TOPIC_TOKEN}.oct.md"
        repo, _ = init_topic_repo(tmp_path, {TOPIC_PATH: TOPIC_RECORD, twin: _OCTAVE_TWIN})
        await self._refused(repo, stubs, twin)

    async def test_a_clean_append_from_a_stale_checkout_succeeds(
        self, tmp_path: Path, stubs
    ) -> None:
        # (d) zero local matches are accepted because main itself was checked.
        repo, _ = init_topic_repo(tmp_path)
        _stale_checkout(repo)
        result = await submit_governance(str(repo), append_ruling=_request(), review=False)
        assert result["success"] is True, result["validation_errors"]
        assert len(stubs["pr"].calls) == 1

    async def test_records_that_only_cite_the_token_do_not_block(
        self, tmp_path: Path, stubs
    ) -> None:
        # Positive control: citations (AMENDS, RELATED_DECISIONS, AUTHORITY, a YAML
        # related_decisions field, markdown body lines) are not declarations.
        repo, _ = init_topic_repo(
            tmp_path,
            {
                TOPIC_PATH: TOPIC_RECORD,
                ".hestai/decisions/HO-CITES-THE-TOPIC-20261015.oct.md": _CITER_OCTAVE,
                ".hestai/decisions/HO-CITES-IN-YAML-20261015.md": _CITER_YAML,
            },
        )
        _stale_checkout(repo)  # the citations exist only at main: the main-side matcher decides
        result = await submit_governance(str(repo), append_ruling=_request(), review=False)
        assert result["success"] is True, result["validation_errors"]
        assert len(stubs["pr"].calls) == 1


# ---------------------------------------------------------------------------
# CAS, dry_run, live path
# ---------------------------------------------------------------------------


class TestDryRun:
    async def test_returns_rendered_record_and_both_hashes_without_branch_or_pr(
        self, tmp_path: Path, stubs
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        branches_before = git(["branch", "--list"], repo)
        result = await submit_governance(str(repo), append_ruling=_request(), dry_run=True)
        assert result["success"] is True, result["validation_errors"]
        assert result["dry_run"] is True
        assert result["branch"] is None and result["pr_url"] is None
        rendered = result["rendered_record"]
        assert isinstance(rendered, str)
        assert result["from_record_hash"] == _hash(TOPIC_RECORD.encode("utf-8"))
        assert result["to_record_hash"] == _hash(rendered.encode("utf-8"))
        assert result["appended_ids"] == ["R4"]
        assert result["replaced_ids"] == []
        assert collect_topic_blocks(rendered)["rulings"][-1]["verbatim"] == _VERBATIM
        assert canonicalize_yaml_record(rendered.encode("utf-8")) == rendered
        assert git(["branch", "--list"], repo) == branches_before
        assert git(["ls-remote", "--heads", "origin"], repo).count("refs/heads/") == 1
        assert stubs["pr"].calls == [] and stubs["reviews"] == []
        assert "semantic_review" not in result

    async def test_matching_expected_hash_is_accepted(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        good = _hash(TOPIC_RECORD.encode("utf-8"))
        result = await submit_governance(
            str(repo), append_ruling=_request(expected_record_hash=good), dry_run=True
        )
        assert result["success"] is True
        assert result["from_record_hash"] == good


class TestLivePath:
    async def test_one_pr_with_hashes_and_ids(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        req = _request()
        req["rulings"].append(
            {
                "rule": "Notes link the issue and the PR.",
                "verbatim": "issue AND pr link",
                "ruled": "Fixture operator, 2026-10-31",
                "replaces": ["R3"],
            }
        )
        result = await submit_governance(str(repo), append_ruling=req, review=False)
        assert result["success"] is True, result["validation_errors"]
        assert result["pr_url"] == _PR_URL
        assert len(stubs["pr"].calls) == 1
        assert (
            stubs["pr"].calls[0]["title"] == f"feat(governance): append ruling(s) to {TOPIC_TOKEN}"
        )
        assert result["appended_ids"] == ["R4", "R5"]
        assert result["replaced_ids"] == ["R3"]
        assert result["token"] == TOPIC_TOKEN
        assert result["target_path"] == TOPIC_PATH
        branch = result["branch"]
        assert branch.endswith(f"-{_SLUG}-r4")
        on_branch = blob_bytes(repo, f"origin/{branch}", TOPIC_PATH)
        assert result["to_record_hash"] == _hash(on_branch)
        assert result["from_record_hash"] == _hash(TOPIC_RECORD.encode("utf-8"))
        assert result["base_oid"] == git(["rev-parse", "origin/main"], repo)
        assert collect_topic_blocks(on_branch.decode("utf-8"))["rulings"][-2]["verbatim"] == (
            _VERBATIM
        )
        body = stubs["pr"].calls[0]["body"]
        for line in _VERBATIM.splitlines():
            assert f"> {line}" in body
        assert "> issue AND pr link" in body
        # MANIFEST unchanged on the branch.
        assert blob_bytes(repo, f"origin/{branch}", ".hestai/MANIFEST.md") == blob_bytes(
            repo, "origin/main", ".hestai/MANIFEST.md"
        )
        assert "semantic_review" not in result

    async def test_failed_head_resolve_after_commit_is_linker_failed(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = init_topic_repo(tmp_path)
        real = linker._run_git

        def runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            if args == ["rev-parse", "--verify", "HEAD^{commit}"]:
                return 1, "", ""
            return real(args, cwd)

        monkeypatch.setattr(linker, "_run_git", runner)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is False
        assert result["error_code"] == "LINKER_FAILED"
        assert any("rev-parse HEAD" in e for e in result["validation_errors"])
        assert result["branch"] is None and result["pr_url"] is None
        assert stubs["pr"].calls == [] and stubs["reviews"] == []
        assert git(["ls-remote", "--heads", "origin"], repo).count("refs/heads/") == 1

    async def test_origin_main_is_read_by_name_once_across_the_whole_call(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, bare = init_topic_repo(tmp_path)
        push_branch(bare, tmp_path / "s", f"governance/20261016-{_SLUG}-r9", merge=True, edit=None)
        calls: list[list[str]] = []
        real_text, real_bytes = linker._run_git, linker._run_git_bytes

        def text_runner(args: list[str], cwd: Path) -> tuple[int, str, str]:
            calls.append(list(args))
            return real_text(args, cwd)

        def bytes_runner(
            args: list[str], cwd: Path, stdin: bytes | None = None
        ) -> tuple[int, bytes, str]:
            calls.append(list(args))
            return real_bytes(args, cwd, stdin)

        monkeypatch.setattr(linker, "_run_git", text_runner)
        monkeypatch.setattr(linker, "_run_git_bytes", bytes_runner)
        result = await submit_governance(str(repo), append_ruling=_request(), review=False)
        assert result["success"] is True, result["validation_errors"]
        named = [c for c in calls if any("origin/main" in a for a in c)]
        assert named == [["rev-parse", "--verify", "origin/main^{commit}"]]
        assert len([c for c in calls if c[0] == "fetch"]) == 1
        worktree_adds = [c for c in calls if c[:2] == ["worktree", "add"]]
        assert len(worktree_adds) == 1 and worktree_adds[0][-1] == result["base_oid"]

    async def test_operator_checkout_is_untouched(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        head = git(["rev-parse", "HEAD"], repo)
        await submit_governance(str(repo), append_ruling=_request(), review=False)
        assert git(["rev-parse", "HEAD"], repo) == head
        assert git(["status", "--porcelain"], repo) == ""


class TestStageFiveFidelity:
    async def test_review_sees_only_the_new_pairs_and_posts_sr(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is True
        assert stubs["reviews"] == [
            [{"id": "R4", "rule": "Hotfix builds ship release notes too.", "verbatim": _VERBATIM}]
        ]
        review = result["semantic_review"]
        assert review["posted"] is True
        assert review["review_kind"] == "ruling_fidelity"
        assert review["gate_verdict"] == "APPROVED"
        post = stubs["posts"][0]
        assert post["role"] == "SR" and post["verdict"] == "APPROVED"
        assert post["repo"] == "owner/name" and post["pr_number"] == 42
        assert post["commit_sha"] == "d" * 40

    async def test_concerns_map_to_blocked_and_name_the_pairs(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def concerns(pairs: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "verdict": "CONCERNS",
                "assessment": "R4 drifts from its verbatim.",
                "concerns": ["R4: adds 'builds'"],
                "reviewer_available": True,
                "metrics": {"tokens": 1, "cost": 0.0, "model": "m", "cost_is_estimate": True},
                "fidelity_pairs": ["R4"],
            }

        monkeypatch.setattr(sg, "review_ruling_fidelity", concerns)
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request())
        review = result["semantic_review"]
        assert review["gate_verdict"] == "BLOCKED"
        assert review["fidelity_pairs"] == ["R4"]
        assert "R4" in stubs["posts"][0]["assessment"]

    async def test_unavailable_reviewer_abstains(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unavailable(pairs: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "verdict": "BLOCKED",
                "assessment": "no client",
                "concerns": [],
                "reviewer_available": False,
                "metrics": {"tokens": 0, "cost": 0.0, "model": "m", "cost_is_estimate": False},
            }

        monkeypatch.setattr(sg, "review_ruling_fidelity", unavailable)
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["semantic_review"]["posted"] is False
        assert result["semantic_review"]["skipped"] is True
        assert stubs["posts"] == []

    async def test_review_exception_is_fail_soft(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def boom(pairs: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("kaput")

        monkeypatch.setattr(sg, "review_ruling_fidelity", boom)
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is True
        assert result["semantic_review"]["posted"] is False
        assert "kaput" in result["semantic_review"]["error"]

    async def test_posting_runs_off_the_event_loop_and_is_fail_soft(
        self, tmp_path: Path, stubs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        main_thread = threading.get_ident()
        seen: list[int] = []

        def raising_submit(**kwargs: Any) -> dict[str, Any]:
            seen.append(threading.get_ident())
            raise RuntimeError("gh down")

        monkeypatch.setattr(sg, "submit_review", raising_submit)
        repo, _ = init_topic_repo(tmp_path)
        result = await submit_governance(str(repo), append_ruling=_request())
        assert result["success"] is True
        assert result["semantic_review"]["posted"] is False
        assert "gh down" in result["semantic_review"]["error"]
        assert seen and seen[0] != main_thread

    async def test_dry_run_and_review_false_skip_stage_five(self, tmp_path: Path, stubs) -> None:
        repo, _ = init_topic_repo(tmp_path)
        dry = await submit_governance(str(repo), append_ruling=_request(), dry_run=True)
        assert "semantic_review" not in dry
        live = await submit_governance(str(repo), append_ruling=_request(), review=False)
        assert "semantic_review" not in live
        assert stubs["reviews"] == []
