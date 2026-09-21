"""
Contract tests for content-aware review-depth escalation via bitemporal set-union.

Feature (GitHub issue #412): a change can declare "this needs deeper review than
the diff-shape suggests" in a way the org-shared gate honours. Declarations are
extracted from FOUR sources and unioned (escalation-only):

    Required_Roles = Diff_Roles ∪ Base_Roles ∪ Head_Roles ∪ PR_Body_Roles

then intersected with ALLOWED_ESCALATION_ROLES before enforcement.

Schema (LOCKED — do not invent syntax):
- Canonical field: REQUIRED_REVIEWERS (OCTAVE block field + HTML-comment markers).
- HTML-comment markers (plain .md + PR body):
    <!-- review-requirements: [TMG, CRS, CE, CIV, SR] -->
    <!-- review-tier: TIER_3_CRITICAL: reason -->
- Whitelist: ALLOWED_ESCALATION_ROLES = VALID_ROLES - {IL, HO}
            = {TMG, CRS, CE, CIV, PE, SR}

Source of truth: issue #412 test corpus + comments 4569263110 / 4569387061.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _f(path: str, added: int = 1, deleted: int = 0, status: str = "M") -> dict:
    """Build a changed-file dict matching get_changed_files() output."""
    return {
        "path": path,
        "added": added,
        "deleted": deleted,
        "total_changed": added + deleted,
        "status": status,
    }


# ---------------------------------------------------------------------------
# 0. ALLOWED_ESCALATION_ROLES is derived, not hardcoded
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestAllowedEscalationRoles:
    """The whitelist must be derived from review_formats.VALID_ROLES - {IL, HO}."""

    def test_whitelist_value(self) -> None:
        assert {
            "TMG",
            "CRS",
            "CE",
            "CIV",
            "PE",
            "SR",
        } == validate_review.ALLOWED_ESCALATION_ROLES

    def test_whitelist_excludes_self_review_roles(self) -> None:
        assert "IL" not in validate_review.ALLOWED_ESCALATION_ROLES
        assert "HO" not in validate_review.ALLOWED_ESCALATION_ROLES

    def test_whitelist_derived_from_valid_roles(self) -> None:
        """Must equal VALID_ROLES - {IL, HO}, not a hardcoded literal."""
        derived = set(validate_review._VALID_ROLES) - {"IL", "HO"}
        assert derived == validate_review.ALLOWED_ESCALATION_ROLES


# ---------------------------------------------------------------------------
# 1. The single extractor: _parse_review_declaration
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestParseReviewDeclaration:
    """_parse_review_declaration(text) -> {tier?, roles?, reason?, source}."""

    def test_html_comment_review_requirements(self) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-requirements: [TMG, CRS, CE, CIV, SR] -->"
        )
        assert decl["roles"] == {"TMG", "CRS", "CE", "CIV", "SR"}

    def test_html_comment_review_tier(self) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITICAL: governance ADR -->"
        )
        assert decl["tier"] == "TIER_3_CRITICAL"
        # TIER_3_CRITICAL maps through tier->role table to a set including CIV
        assert "CIV" in decl["roles"]
        assert decl["reason"] == "governance ADR"

    def test_octave_required_reviewers_block_field(self) -> None:
        """OCTAVE REQUIRED_REVIEWERS::"{CE, CRS, SR}" override field."""
        text = "===ADR===\n" "META:\n" "  TYPE::RULE\n" 'REQUIRED_REVIEWERS::"{CE, CRS, SR}"\n'
        decl = validate_review._parse_review_declaration(text)
        assert decl["roles"] == {"CE", "CRS", "SR"}

    def test_frontmatter_review_requirements(self) -> None:
        """YAML-frontmatter declaration per the issue's _parse_review_declaration spec."""
        text = "---\n" "review-requirements: [CE, CRS]\n" "---\n" "# Some doc\n"
        decl = validate_review._parse_review_declaration(text)
        assert decl["roles"] == {"CE", "CRS"}

    def test_no_declaration_returns_empty_roles(self) -> None:
        decl = validate_review._parse_review_declaration("Just some prose, no markers.")
        assert not decl.get("roles")

    def test_malformed_declaration_does_not_crash(self) -> None:
        """Malformed markers must not raise — return empty/partial, never crash."""
        decl = validate_review._parse_review_declaration("<!-- review-requirements: [TMG, , -->")
        # No exception; whatever parsed is a set (possibly empty)
        assert isinstance(decl.get("roles", set()), set)


# ---------------------------------------------------------------------------
# 2. Bitemporal collection: _collect_bitemporal_declarations
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestCollectBitemporalDeclarations:
    """Union declarations from PR body + base blob + head blob per changed file."""

    def test_pr_body_declaration(self, monkeypatch) -> None:
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)
        roles, prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/ADR.md")],
            pr_body="<!-- review-requirements: [SR] -->",
            base_sha="base",
            head_sha="head",
        )
        assert "SR" in roles
        assert "PR_BODY" in prov["SR"]

    def test_head_blob_declaration(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-requirements: [TMG] -->"
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        roles, prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/ADR.md")],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert "TMG" in roles
        assert "HEAD" in prov["TMG"]
        assert "BASE" not in prov.get("TMG", set())

    def test_base_only_declaration_retained(self, monkeypatch) -> None:
        """RATCHET core: role declared in BASE but absent from HEAD is retained."""

        def fake_show(sha, path):
            if sha == "base":
                return "<!-- review-requirements: [CRS] -->"
            return ""  # HEAD blob exists but has no declaration

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        roles, prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/ADR.md")],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert "CRS" in roles, "BASE-declared role must survive (set-union cannot subtract)"
        assert prov["CRS"] == {"BASE"}, "BASE-only role must show BASE provenance only"

    def test_missing_base_blob_no_crash(self, monkeypatch) -> None:
        """New file (no BASE blob): _git_show_file returns None — union uses HEAD only."""

        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-requirements: [CE] -->"
            return None  # base blob missing (new file)

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        roles, prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/NEW.md", status="A")],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert roles == {"CE"}
        assert prov["CE"] == {"HEAD"}

    def test_out_of_whitelist_role_dropped(self, monkeypatch) -> None:
        """[GOD_MODE] is outside ALLOWED_ESCALATION_ROLES -> dropped, non-fatal."""
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)
        roles, prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/ADR.md")],
            pr_body="<!-- review-requirements: [GOD_MODE, CRS] -->",
            base_sha="base",
            head_sha="head",
        )
        assert "GOD_MODE" not in roles
        assert "CRS" in roles

    def test_il_ho_dropped_as_self_review_roles(self, monkeypatch) -> None:
        """IL and HO are self-review roles, not escalation-declarable -> dropped."""
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)
        roles, _prov = validate_review._collect_bitemporal_declarations(
            files=[_f("docs/ADR.md")],
            pr_body="<!-- review-requirements: [IL, HO, SR] -->",
            base_sha="base",
            head_sha="head",
        )
        assert roles == {"SR"}


# ---------------------------------------------------------------------------
# 3. classify_pr_facets integration — the 10-test frozen corpus
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestClassifyPrFacetsEscalation:
    """classify_pr_facets must union declared roles BEFORE both early returns."""

    # --- Corpus #1: regression guard ---
    def test_diff_only_no_declaration_unchanged(self) -> None:
        """Diff-only PR, no declaration -> unchanged behaviour."""
        files = [_f("src/core.py", added=50, deleted=20)]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert roles == {"CE", "CRS", "TMG"}
        assert tier == "TIER_2_STANDARD"

    def test_diff_only_exempt_still_tier_0(self) -> None:
        """Pure .md with no declaration still TIER_0_EXEMPT (regression guard)."""
        files = [_f("docs/README.md", added=10, deleted=5)]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_0_EXEMPT"
        assert roles == set()

    # --- Corpus #3: .oct.md REQUIRED_REVIEWERS override escalates ---
    def test_octave_required_reviewers_escalates(self) -> None:
        """.oct.md declaring REQUIRED_REVIEWERS escalates to declared roles."""
        files = [_f("docs/governance/POLICY.oct.md", added=5, deleted=2)]
        facets, roles, tier, _ = validate_review.classify_pr_facets(
            files, declared_roles={"CIV", "CE", "CRS", "SR", "TMG"}
        )
        assert {"CIV", "CE", "CRS", "SR", "TMG"}.issubset(roles)
        assert tier == "TIER_3_CRITICAL"  # CIV present

    # --- Corpus #4: PR body declares roles ---
    def test_declared_roles_union_with_diff(self) -> None:
        """Declared roles union with diff-computed roles (escalation-only ADD)."""
        files = [_f("src/core.py", added=50, deleted=20)]  # diff -> {CE, CRS, TMG}
        facets, roles, tier, _ = validate_review.classify_pr_facets(
            files, declared_roles={"CIV", "SR"}
        )
        # union: diff {CE, CRS, TMG} ∪ declared {CIV, SR}
        assert roles == {"CE", "CRS", "TMG", "CIV", "SR"}
        assert tier == "TIER_3_CRITICAL"

    # --- Corpus #9 KEYSTONE: all-exempt-escalation ---
    def test_all_exempt_with_declaration_does_not_return_tier_0(self) -> None:
        """KEYSTONE (elevana-studio #868): docs-only PR carrying a declaration
        escalates to the declared role set and does NOT return TIER_0_EXEMPT.

        This proves the union runs BEFORE the `:301 if not facets` early return.
        """
        files = [_f("decisions/ADR-HO-AUTH.md", added=40, deleted=0, status="A")]
        facets, roles, tier, _ = validate_review.classify_pr_facets(
            files, declared_roles={"TMG", "CRS", "CE", "CIV", "SR"}
        )
        assert tier != "TIER_0_EXEMPT", "all-exempt PR with declaration must NOT be exempt"
        assert roles == {"TMG", "CRS", "CE", "CIV", "SR"}
        assert tier == "TIER_3_CRITICAL"

    # --- Corpus #10 KEYSTONE: declaration suppresses self-review ---
    def test_declaration_suppresses_tier_1_self(self) -> None:
        """KEYSTONE: a declaration on an otherwise TIER_1_SELF-eligible change
        suppresses self-review (does not short-circuit to TIER_1_SELF).

        Proves the union runs BEFORE the `:319 TIER_1_SELF` early return.
        """
        files = [_f("src/config.py", added=3, deleted=1)]  # would be TIER_1_SELF
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles={"CRS"})
        assert tier != "TIER_1_SELF", "declaration must suppress self-review short-circuit"
        assert "CRS" in roles

    def test_no_declaration_still_tier_1_self(self) -> None:
        """Without a declaration, the TIER_1_SELF short-circuit is preserved."""
        files = [_f("src/config.py", added=3, deleted=1)]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_1_SELF"

    # --- Escalation-only structural property ---
    def test_declaration_cannot_subtract_diff_roles(self) -> None:
        """Declaring a SMALLER set never removes diff-computed roles (escalation-only)."""
        files = [_f("src/core.py", added=50, deleted=20)]  # diff -> {CE, CRS, TMG}
        facets, roles, tier, _ = validate_review.classify_pr_facets(
            files, declared_roles={"SR"}  # declares only SR
        )
        # diff roles are retained; SR is added
        assert {"CE", "CRS", "TMG"}.issubset(roles)
        assert "SR" in roles


# ---------------------------------------------------------------------------
# 4. End-to-end through the bitemporal collector (corpus #2, #5, #6, #7, #8)
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestEndToEndEscalation:
    """Full path: collector -> classify, exercising the locked HTML-comment markers."""

    # --- Corpus #2: markdown-only PR with review-tier marker escalates ---
    def test_markdown_only_review_tier_escalates(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-tier: TIER_3_CRITICAL: governance ADR -->"
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("docs/ADR.md", added=40, deleted=0, status="A")]
        declared, _prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles=declared)
        assert tier != "TIER_0_EXEMPT"
        assert "CIV" in roles  # TIER_3 maps to a CIV-bearing set
        assert tier == "TIER_3_CRITICAL"

    # --- Corpus #5 KEYSTONE: ratchet ---
    def test_ratchet_base_declaration_removed_in_head_retained(self, monkeypatch) -> None:
        """KEYSTONE: declaration in BASE, removed in HEAD -> role RETAINED.

        Proves escalation-only is a structural property of set-union, not a rule.
        """

        def fake_show(sha, path):
            if sha == "base":
                return "<!-- review-requirements: [CE, CRS, TMG, CIV, SR] -->"
            return ""  # HEAD: declaration deleted

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("decisions/ADR.md", added=2, deleted=8)]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == {"CE", "CRS", "TMG", "CIV", "SR"}
        for role in declared:
            assert prov[role] == {"BASE"}, f"{role} attempted-reduction must show BASE only"
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles=declared)
        assert tier == "TIER_3_CRITICAL"

    # --- Corpus #6: malformed declaration falls back, no crash ---
    def test_malformed_declaration_falls_back_to_diff_floor(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-requirements: [ -->"  # malformed
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("src/core.py", added=50, deleted=20)]
        declared, _prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        # malformed -> no extra roles; declared is empty (no crash)
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles=declared)
        # falls back to diff-computed floor for a .py file
        assert roles == {"CE", "CRS", "TMG"}

    # --- Corpus #7: out-of-whitelist role dropped, gate computes without it ---
    def test_god_mode_dropped_gate_computes_without_it(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-requirements: [GOD_MODE] -->"
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("docs/ADR.md", added=10, deleted=0)]
        declared, _prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == set()
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles=declared)
        # docs-only + no valid declared roles -> still exempt (GOD_MODE dropped non-fatally)
        assert tier == "TIER_0_EXEMPT"

    # --- Corpus #8: new file, no BASE blob, union on HEAD only ---
    def test_new_file_no_base_blob_union_head_only(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-requirements: [SR] -->"
            return None  # no base blob

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("docs/NEW-ADR.md", added=30, deleted=0, status="A")]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == {"SR"}
        assert prov["SR"] == {"HEAD"}


# ---------------------------------------------------------------------------
# 5. Provenance emitted in JSON output
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestProvenanceInJsonOutput:
    """_emit_json_summary must include a per-role provenance source map."""

    def test_emit_json_includes_provenance(self, capsys) -> None:
        import json

        validate_review._emit_json_summary(
            tier="TIER_3_CRITICAL",
            reason="escalated",
            reviewers=["CRS", "TMG"],
            status="fail",
            required_count=2,
            found_count=0,
            sha="abc1234",
            provenance={"CRS": ["HEAD", "BASE"], "TMG": ["DIFF"]},
        )
        out = capsys.readouterr().out
        marker = "<!-- REVIEW_GATE_JSON:"
        assert marker in out
        payload = out.split(marker, 1)[1].split(" -->", 1)[0]
        data = json.loads(payload)
        assert data["provenance"]["CRS"] == ["HEAD", "BASE"]
        assert data["provenance"]["TMG"] == ["DIFF"]

    def test_emit_json_provenance_optional(self, capsys) -> None:
        """Backward compat: omitting provenance must not crash; defaults to empty."""
        validate_review._emit_json_summary(
            tier="TIER_2_STANDARD",
            reason="r",
            reviewers=["CE"],
            status="pass",
            required_count=1,
            found_count=1,
            sha="abc1234",
        )
        out = capsys.readouterr().out
        assert "<!-- REVIEW_GATE_JSON:" in out


# ---------------------------------------------------------------------------
# 6. git-show + PR-body helpers (safe on missing blobs / missing context)
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestGitShowAndPrBodyHelpers:
    """_git_show_file and _get_pr_body must degrade gracefully, never crash."""

    def test_git_show_returns_content_on_success(self, monkeypatch) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        monkeypatch.setattr(
            sp,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout="hello body"),
        )
        assert validate_review._git_show_file("sha", "path") == "hello body"

    def test_git_show_missing_blob_returns_none(self, monkeypatch) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        monkeypatch.setattr(
            sp,
            "run",
            lambda *a, **k: MagicMock(returncode=128, stdout=""),
        )
        assert validate_review._git_show_file("sha", "path") is None

    def test_git_show_empty_sha_returns_none(self) -> None:
        assert validate_review._git_show_file("", "path") is None

    def test_git_show_oserror_returns_none(self, monkeypatch) -> None:
        import subprocess as sp

        def boom(*a, **k):
            raise OSError("no git")

        monkeypatch.setattr(sp, "run", boom)
        assert validate_review._git_show_file("sha", "path") is None

    def test_git_show_binary_blob_does_not_crash(self, tmp_path) -> None:
        """P2 (cubic 8): a binary/non-UTF-8 blob must NOT raise UnicodeDecodeError.

        Exercises the REAL subprocess.run decode path against a git blob whose
        bytes are not valid UTF-8 (e.g. a PNG). The gate runs org-wide on every
        PR; a single binary file in a PR must not crash it (I2).
        """
        import os
        import subprocess as sp

        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.t",
        }
        # Use a non-"main"/non-"master" branch so the commit never collides
        # with main-branch protection hooks (global core.hooksPath) present in
        # some environments — keeps the test portable. -b overrides whatever
        # init.defaultBranch is configured.
        sp.run(["git", "init", "-q", "-b", "testwork"], cwd=repo, check=True, env=env)
        # Invalid UTF-8 bytes (0xFF 0xFE ... 0x80) — a PNG-like binary blob.
        binary = b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x80\x81\x82binarydata\xc3\x28"
        (repo / "image.png").write_bytes(binary)
        sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        sp.run(["git", "commit", "-qm", "add binary"], cwd=repo, check=True, env=env)
        sha = sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

        # Run _git_show_file from within the repo (it shells out to `git show`).
        cwd0 = os.getcwd()
        try:
            os.chdir(repo)
            # MUST NOT raise UnicodeDecodeError; returns a (replacement-decoded) str.
            result = validate_review._git_show_file(sha, "image.png")
        finally:
            os.chdir(cwd0)
        assert result is not None
        assert isinstance(result, str)

    def test_collect_with_binary_file_does_not_crash(self, tmp_path) -> None:
        """End-to-end: a PR changing a binary file must not crash collection.

        The collector reads BASE/HEAD blobs for every changed file; a binary
        blob must degrade to "no declaration" rather than raising.
        """
        import os
        import subprocess as sp

        repo = tmp_path / "repo2"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.t",
        }
        # Non-"main"/non-"master" branch for portability under main-branch
        # protection hooks (see test_git_show_binary_blob_does_not_crash).
        sp.run(["git", "init", "-q", "-b", "testwork"], cwd=repo, check=True, env=env)
        (repo / "logo.png").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x80\x81")
        sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        sp.run(["git", "commit", "-qm", "binary"], cwd=repo, check=True, env=env)
        sha = sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

        cwd0 = os.getcwd()
        try:
            os.chdir(repo)
            roles, prov = validate_review._collect_bitemporal_declarations(
                files=[_f("logo.png", status="M")],
                pr_body="",
                base_sha=sha,
                head_sha=sha,
            )
        finally:
            os.chdir(cwd0)
        # Binary blob carries no declaration; collection must succeed (no crash).
        assert roles == set()
        assert prov == {}

    def test_get_pr_body_empty_outside_ci(self, monkeypatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        assert validate_review._get_pr_body() == ""

    def test_get_pr_body_empty_without_pr_number(self, monkeypatch) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("PR_NUMBER", raising=False)
        assert validate_review._get_pr_body() == ""

    def test_get_pr_body_returns_body_in_ci(self, monkeypatch) -> None:
        import json as _json
        import subprocess as sp
        from unittest.mock import MagicMock

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "412")
        monkeypatch.setattr(
            sp,
            "run",
            lambda *a, **k: MagicMock(
                returncode=0, stdout=_json.dumps({"body": "<!-- review-requirements: [SR] -->"})
            ),
        )
        assert "review-requirements" in validate_review._get_pr_body()


# ---------------------------------------------------------------------------
# 7. main() end-to-end — the originating elevana-studio #868 scenario
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestMainEndToEndEscalation:
    """main() must escalate an all-exempt PR carrying a declaration, in CI."""

    @pytest.fixture(autouse=True)
    def ci_env(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "868")
        monkeypatch.delenv("CACHED_GATE_DATA", raising=False)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(validate_review, "_get_head_sha", lambda: "headsha")
        monkeypatch.setattr(validate_review, "_get_base_ref_sha", lambda: "basesha")

    def test_all_exempt_markdown_adr_escalates_and_blocks(self, monkeypatch, capsys) -> None:
        """#868: markdown ADR mandating a T3 chain must NOT be reported mergeable.

        All-exempt diff + a HEAD declaration -> gate escalates to the declared
        chain, finds no approvals, and BLOCKS (exit 1). Provenance is emitted.
        """
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [_f("decisions/ADR-HO-AUTH.md", added=40, deleted=0, status="A")],
        )
        monkeypatch.setattr(validate_review, "_get_pr_body", lambda: "")

        def fake_show(sha, path):
            if sha == "headsha":
                return "<!-- review-requirements: [TMG, CRS, CE, CIV, SR] -->"
            return None  # new file: no base blob

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        # No approvals present
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *a, **k: (False, "Missing reviews", ["TMG", "CRS", "CE", "CIV", "SR"]),
        )

        exit_code = validate_review.main()
        assert exit_code == 1, "all-exempt ADR with T3 declaration must block, not pass"

        out = capsys.readouterr().out
        assert "TIER_0_EXEMPT" not in out.split("REVIEW_GATE_JSON")[0] or "TIER_3" in out
        import json as _json

        payload = out.split("<!-- REVIEW_GATE_JSON:", 1)[1].split(" -->", 1)[0]
        data = _json.loads(payload)
        assert data["tier"] == "TIER_3_CRITICAL"
        assert set(data["reviewers"]) == {"TMG", "CRS", "CE", "CIV", "SR"}
        # Each declared role is attributed to the HEAD blob.
        for role in {"TMG", "CRS", "CE", "CIV", "SR"}:
            assert "HEAD" in data["provenance"][role]

    def test_diff_only_no_declaration_still_exempt_in_main(self, monkeypatch, capsys) -> None:
        """Regression: a pure-docs PR with no declaration still exits 0 (exempt)."""
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [_f("docs/README.md", added=5, deleted=2)],
        )
        monkeypatch.setattr(validate_review, "_get_pr_body", lambda: "")
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)

        exit_code = validate_review.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "TIER_0_EXEMPT" in out


# ---------------------------------------------------------------------------
# 8. Copilot bot-resolution: exclude rules-schema file from declaration scan
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestRulesSchemaFileExcludedFromDeclarationScan:
    """The gate's own rules-schema doc uses REQUIRED_REVIEWERS:: DESCRIPTIVELY
    (to define per-facet reviewers). Those lines are config, NOT a PR-level
    declaration, and must not be picked up by the bitemporal collector.

    Match by basename so BOTH the bundled-hub source and the .hestai-sys runtime
    copy are skipped as declaration SOURCES.
    """

    # The rules-schema doc's own content trips the extractor: a descriptive
    # OCTAVE REQUIRED_REVIEWERS:: line AND the §8 documentation that quotes the
    # HTML-comment marker example. This fixture reproduces content the extractor
    # genuinely matches today, so the test is RED (picks up roles) before the
    # basename-exclusion fix.
    _SCHEMA_BLOB = (
        "===REVIEW_REQUIREMENTS===\n"
        "META:\n"
        "  TYPE::RULE\n"
        '  REQUIRED_REVIEWERS::"{CIV, CE, CRS, SR, TMG}"\n'
        "// §8 documents the marker, which the extractor also matches:\n"
        "// <!-- review-requirements: [CIV, CE, CRS, SR, TMG] -->\n"
    )

    def test_bundled_hub_schema_path_not_scanned(self, monkeypatch) -> None:
        """A PR editing the bundled-hub rules-schema must NOT union its
        descriptive REQUIRED_REVIEWERS lines as a declaration."""

        def fake_show(sha, path):
            return self._SCHEMA_BLOB  # both base & head return the schema body

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("src/hestai_mcp/_bundled_hub/standards/rules/review-requirements.oct.md")]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == set(), f"schema file must not declare roles, got {declared}"
        assert prov == {}

    def test_runtime_copy_schema_path_not_scanned(self, monkeypatch) -> None:
        """The .hestai-sys runtime copy is also excluded (matched by basename)."""

        def fake_show(sha, path):
            return self._SCHEMA_BLOB

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f(".hestai-sys/standards/rules/review-requirements.oct.md")]
        declared, _prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == set()

    def test_pr_body_marker_still_scanned_when_schema_changed(self, monkeypatch) -> None:
        """Excluding the schema file must NOT disable the PR-body marker path."""

        def fake_show(sha, path):
            return self._SCHEMA_BLOB

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("src/hestai_mcp/_bundled_hub/standards/rules/review-requirements.oct.md")]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files,
            pr_body="<!-- review-requirements: [CIV, CE, CRS, SR, TMG] -->",
            base_sha="base",
            head_sha="head",
        )
        # Roles come from the PR body ONLY (not the schema's descriptive lines).
        assert declared == {"CIV", "CE", "CRS", "SR", "TMG"}
        for role in declared:
            assert prov[role] == {"PR_BODY"}, f"{role} must be PR_BODY-sourced, got {prov[role]}"

    def test_non_schema_oct_md_still_scanned(self, monkeypatch) -> None:
        """A DIFFERENT .oct.md (not the rules schema) is still a valid source."""

        def fake_show(sha, path):
            if sha == "head":
                return 'REQUIRED_REVIEWERS::"{SR}"\n'
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("docs/governance/SOME-ADR.oct.md")]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == {"SR"}
        assert prov["SR"] == {"HEAD"}

    def test_this_pr_still_escalates_via_facet_not_schema_lines(self, monkeypatch) -> None:
        """THIS PR (edits validate_review.py + the rules schema) must STILL
        escalate to {CE, CIV, CRS, SR, TMG} at TIER_3_CRITICAL — sourced from the
        META_CONTROL_PLANE FACET + PR body, NOT the schema's descriptive lines."""

        def fake_show(sha, path):
            # Only the schema doc carries the descriptive markers; the .py code
            # file has no declaration content (realistic blob contents).
            if "review-requirements.oct.md" in path:
                return self._SCHEMA_BLOB
            return ""

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [
            _f("scripts/validate_review.py", added=50, deleted=10),  # META_CONTROL_PLANE facet
            _f("src/hestai_mcp/_bundled_hub/standards/rules/review-requirements.oct.md"),
        ]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files,
            pr_body="<!-- review-requirements: [CIV, CE, CRS, SR, TMG] -->",
            base_sha="base",
            head_sha="head",
        )
        # Declared roles come from PR body only (schema lines excluded).
        assert declared == {"CIV", "CE", "CRS", "SR", "TMG"}
        for role in declared:
            assert prov[role] == {"PR_BODY"}, (
                f"{role} must be PR_BODY-only; schema/code lines must not be a "
                f"source, got {prov[role]}"
            )
        facets, roles, tier, _ = validate_review.classify_pr_facets(files, declared_roles=declared)
        assert tier == "TIER_3_CRITICAL"
        assert {"CE", "CIV", "CRS", "SR", "TMG"}.issubset(roles)
        assert "META_CONTROL_PLANE" in facets, "facet (real routing input) drives escalation"


# ---------------------------------------------------------------------------
# 9. Copilot bot-resolution: warn (non-fatal) on unrecognized review-tier
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestUnrecognizedReviewTierWarns:
    """A review-tier marker whose value is not in the tier->role map must emit a
    non-fatal warning (so the author gets a signal) and contribute no roles —
    never a silent no-op, never a crash."""

    def test_unknown_tier_warns_and_contributes_no_roles(self, capsys) -> None:
        decl = validate_review._parse_review_declaration("<!-- review-tier: TIER_0_EXEMPT -->")
        # tier is recorded, but no roles contributed
        assert decl.get("tier") == "TIER_0_EXEMPT"
        assert not decl.get("roles")
        err = capsys.readouterr().err
        assert "TIER_0_EXEMPT" in err
        assert "review-tier" in err.lower() or "tier" in err.lower()

    def test_misspelled_tier_warns(self, capsys) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITCAL: typo here -->"
        )
        assert decl.get("tier") == "TIER_3_CRITCAL"
        assert not decl.get("roles")
        err = capsys.readouterr().err
        assert "TIER_3_CRITCAL" in err

    def test_recognized_tier_does_not_warn(self, capsys) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITICAL: ok -->"
        )
        assert "CIV" in decl["roles"]
        err = capsys.readouterr().err
        assert "TIER_3_CRITICAL" not in err  # no warning for a mapped tier

    def test_unknown_tier_does_not_crash_collector(self, monkeypatch) -> None:
        def fake_show(sha, path):
            if sha == "head":
                return "<!-- review-tier: TIER_9_BOGUS -->"
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)
        files = [_f("docs/ADR.md")]
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=files, pr_body="", base_sha="base", head_sha="head"
        )
        assert declared == set()
        assert prov == {}


# ---------------------------------------------------------------------------
# 10. Cached-provenance re-read branch in main() (comment-event fast path)
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestCachedProvenanceReRead:
    """On the comment-event fast path, main() reuses the cached provenance map
    (diff unchanged) instead of re-reading BASE/HEAD blobs, and re-emits it."""

    def test_cached_provenance_reused_and_emitted(self, monkeypatch, capsys) -> None:
        import json as _json

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "414")
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        # Fast-path SHA guards: cached head/base must match the resolved SHAs.
        monkeypatch.setattr(validate_review, "_get_head_sha", lambda: "headsha")
        monkeypatch.setattr(validate_review, "_get_base_ref_sha", lambda: "basesha")
        # Approvals satisfied so main() reaches the success emit (status="pass").
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *a, **k: (True, "all approvals present", []),
        )

        cached = {
            "tier": "TIER_3_CRITICAL",
            "reason": "cached",
            "roles": ["CE", "CIV", "CRS", "SR", "TMG"],
            "sha": "headsha",
            "base_sha": "basesha",
            "provenance": {
                "CE": ["DIFF"],
                "CIV": ["HEAD"],
                "CRS": ["BASE"],
                "SR": ["PR_BODY"],
                "TMG": ["HEAD", "PR_BODY"],
            },
        }
        monkeypatch.setenv("CACHED_GATE_DATA", _json.dumps(cached))

        exit_code = validate_review.main()
        assert exit_code == 0

        out = capsys.readouterr().out
        payload = out.split("<!-- REVIEW_GATE_JSON:", 1)[1].split(" -->", 1)[0]
        data = _json.loads(payload)
        # Provenance is re-read from cache and re-emitted unchanged.
        assert data["provenance"]["CRS"] == ["BASE"]
        assert data["provenance"]["TMG"] == ["HEAD", "PR_BODY"]
        assert data["tier"] == "TIER_3_CRITICAL"


# ---------------------------------------------------------------------------
# 11. CRS F1 — review-tier reason preserves an embedded '>' character
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestReviewTierReasonEmbeddedGt:
    """The review-tier reason is display/log-only but must not truncate at '>'."""

    def test_reason_with_embedded_gt_preserved(self) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITICAL: foo > bar -->"
        )
        assert decl["tier"] == "TIER_3_CRITICAL"
        assert decl["reason"] == "foo > bar"
        # tier still maps to roles correctly
        assert "CIV" in decl["roles"]

    def test_reason_without_gt_still_works(self) -> None:
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITICAL: plain reason -->"
        )
        assert decl["reason"] == "plain reason"

    def test_reason_does_not_overcapture_past_terminator(self) -> None:
        """The reason must stop at the comment terminator, not swallow trailing text."""
        decl = validate_review._parse_review_declaration(
            "<!-- review-tier: TIER_3_CRITICAL: r --> trailing text"
        )
        assert decl["reason"] == "r"


# ---------------------------------------------------------------------------
# 12. CRS F2 — provenance shows ALL sources for a declared+diff role
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestProvenanceMultiSourceAttribution:
    """A role both declared (HEAD/BASE/PR_BODY) AND diff/facet-required must show
    BOTH sources in provenance — including DIFF — not just one."""

    @pytest.fixture(autouse=True)
    def ci_env(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "414")
        monkeypatch.delenv("CACHED_GATE_DATA", raising=False)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(validate_review, "_get_head_sha", lambda: "headsha")
        monkeypatch.setattr(validate_review, "_get_base_ref_sha", lambda: "basesha")
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *a, **k: (True, "approvals present", []),
        )

    def test_declared_and_diff_role_shows_both_sources(self, monkeypatch, capsys) -> None:
        """CRS, TMG, CE come from the .py DIFF facet (ROUTINE_CODE); the PR body
        ALSO declares CRS. CRS provenance must be {DIFF, PR_BODY}; CE/TMG stay
        DIFF-only; SR (PR_BODY only, not diff) stays PR_BODY-only."""
        import json as _json

        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [_f("src/core.py", added=50, deleted=20)],  # ROUTINE_CODE -> CE,CRS,TMG
        )
        # PR body declares CRS (overlaps diff) + SR (new). No blob declarations.
        monkeypatch.setattr(
            validate_review,
            "_get_pr_body",
            lambda: "<!-- review-requirements: [CRS, SR] -->",
        )
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)

        exit_code = validate_review.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        payload = out.split("<!-- REVIEW_GATE_JSON:", 1)[1].split(" -->", 1)[0]
        data = _json.loads(payload)
        prov = data["provenance"]
        # CRS: declared (PR_BODY) AND diff-required (ROUTINE_CODE) -> BOTH.
        assert set(prov["CRS"]) == {"DIFF", "PR_BODY"}, prov["CRS"]
        # CE, TMG: diff-only.
        assert prov["CE"] == ["DIFF"], prov["CE"]
        assert prov["TMG"] == ["DIFF"], prov["TMG"]
        # SR: declared only (not in the diff floor) -> PR_BODY only.
        assert prov["SR"] == ["PR_BODY"], prov["SR"]

    def test_pure_declared_role_stays_single_source(self, monkeypatch, capsys) -> None:
        """Regression guard: an all-exempt PR with a PR_BODY-only declaration keeps
        single-source provenance (no spurious DIFF added)."""
        import json as _json

        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [_f("docs/ADR.md", added=10, deleted=0)],  # exempt -> no diff roles
        )
        monkeypatch.setattr(
            validate_review,
            "_get_pr_body",
            lambda: "<!-- review-requirements: [CIV, CRS] -->",
        )
        monkeypatch.setattr(validate_review, "_git_show_file", lambda sha, path: None)

        exit_code = validate_review.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        payload = out.split("<!-- REVIEW_GATE_JSON:", 1)[1].split(" -->", 1)[0]
        data = _json.loads(payload)
        prov = data["provenance"]
        assert prov["CIV"] == ["PR_BODY"], prov["CIV"]
        assert prov["CRS"] == ["PR_BODY"], prov["CRS"]


# ---------------------------------------------------------------------------
# 13. Rename-aware BASE declaration read (issue #417)
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.behavior
class TestRenameAwareBaseDeclaration:
    """_collect_bitemporal_declarations must use previous_path for BASE blob lookup
    when a file has been renamed, so the escalation-only ratchet holds across
    file renames (issue #417).

    Two defects fixed together:
    1. get_changed_files() must detect R-status renames and populate previous_path.
    2. _collect_bitemporal_declarations() must use previous_path for BASE blob.
    """

    def test_rename_ratchet_keystone(self, monkeypatch) -> None:
        """RENAME-RATCHET (KEYSTONE): renamed file whose BASE blob (OLD path)
        declared REQUIRED_REVIEWERS, where the declaration is absent in HEAD
        (new path) — the role MUST be retained.

        Proves escalation-only set-union holds across a file rename.
        Without the fix: _git_show_file(base_sha, new_path) returns None
        (wrong path) -> BASE contribution silently missed -> ratchet bypassed.
        With the fix: _git_show_file(base_sha, old_path) returns the BASE blob
        -> role retained.
        """
        old_path = "governance/OLD-ADR.oct.md"
        new_path = "governance/NEW-ADR.oct.md"

        def fake_show(sha: str, path: str) -> str | None:
            if sha == "base" and path == old_path:
                # BASE blob at OLD path has a declaration
                return "<!-- review-requirements: [CIV, SR] -->"
            if sha == "head" and path == new_path:
                # HEAD blob at NEW path has no declaration (removed)
                return ""
            # Any wrong-path call returns None — simulates blob-not-found
            return None

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)

        # File dict with previous_path populated (as get_changed_files() will
        # produce after the fix)
        renamed_file = {
            "path": new_path,
            "previous_path": old_path,
            "added": 2,
            "deleted": 8,
            "total_changed": 10,
            "status": "renamed",
        }

        declared, prov = validate_review._collect_bitemporal_declarations(
            files=[renamed_file],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert "CIV" in declared, (
            "CIV declared in BASE blob at old path must be retained across rename "
            "(escalation-only ratchet must hold)"
        )
        assert (
            "SR" in declared
        ), "SR declared in BASE blob at old path must be retained across rename"
        assert "BASE" in prov.get("CIV", set()), "CIV must be attributed to BASE source"
        assert "BASE" in prov.get("SR", set()), "SR must be attributed to BASE source"

    def test_rename_no_previous_path_no_crash(self, monkeypatch) -> None:
        """RENAME-NO-PREVIOUS: a new file (no previous_path key) is treated as
        HEAD-only — no crash, no KeyError."""

        def fake_show(sha: str, path: str) -> str | None:
            if sha == "head":
                return "<!-- review-requirements: [TMG] -->"
            return None  # no base blob for new file

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)

        # File dict WITHOUT previous_path (new file, added status)
        new_file = {
            "path": "governance/BRAND-NEW.oct.md",
            "added": 30,
            "deleted": 0,
            "total_changed": 30,
            "status": "A",
        }

        # Must not crash; must pick up HEAD declaration
        declared, prov = validate_review._collect_bitemporal_declarations(
            files=[new_file],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert "TMG" in declared, "HEAD declaration on new file must be collected"
        assert prov.get("TMG") == {"HEAD"}, "TMG must be attributed to HEAD only"

    def test_rename_same_path_regression_guard(self, monkeypatch) -> None:
        """RENAME-SAME-PATH: a modified (non-renamed) file with no previous_path
        still works correctly — regression guard for the fix."""

        def fake_show(sha: str, path: str) -> str | None:
            if sha == "base" and path == "src/hestai_mcp/core.py":
                return "<!-- review-requirements: [CE] -->"
            return ""

        monkeypatch.setattr(validate_review, "_git_show_file", fake_show)

        modified_file = {
            "path": "src/hestai_mcp/core.py",
            "added": 10,
            "deleted": 5,
            "total_changed": 15,
            "status": "M",
        }

        declared, prov = validate_review._collect_bitemporal_declarations(
            files=[modified_file],
            pr_body="",
            base_sha="base",
            head_sha="head",
        )
        assert "CE" in declared, "BASE declaration on modified file must still be collected"
        assert "BASE" in prov.get("CE", set()), "CE must be attributed to BASE source"

    def _make_rename_mock(self, monkeypatch, numstat_output: str, name_status_output: str):
        """Helper: wire subprocess.run mocks for get_changed_files() rename tests."""
        import subprocess as sp
        from unittest.mock import MagicMock

        def mock_run(cmd, **kwargs):
            if "--numstat" in cmd:
                return MagicMock(returncode=0, stdout=numstat_output)
            if "--name-status" in cmd:
                return MagicMock(returncode=0, stdout=name_status_output)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(sp, "run", mock_run)
        monkeypatch.delenv("CI", raising=False)

    def test_get_changed_files_rename_parsing_plain_arrow(self, monkeypatch) -> None:
        """Plain arrow: real git --numstat 3-field format for cross-directory rename.

        Real git output:  3\\t1\\told/governance/OLD-NAME.oct.md => new/governance/NEW-NAME.oct.md
        (single tab-separated 3-field line; ' => ' is inside the filename field)
        """
        numstat_output = "3\t1\told/governance/OLD-NAME.oct.md => new/governance/NEW-NAME.oct.md\n"
        name_status_output = (
            "R100\told/governance/OLD-NAME.oct.md\tnew/governance/NEW-NAME.oct.md\n"
        )
        self._make_rename_mock(monkeypatch, numstat_output, name_status_output)

        files = validate_review.get_changed_files()

        assert len(files) == 1, f"Expected 1 file, got {len(files)}: {files}"
        f = files[0]
        assert (
            f["path"] == "new/governance/NEW-NAME.oct.md"
        ), f"path must be new path only, got: {f['path']!r}"
        assert (
            f.get("previous_path") == "old/governance/OLD-NAME.oct.md"
        ), f"previous_path must be old path, got: {f.get('previous_path')!r}"
        assert f.get("status") in (
            "renamed",
            "R",
        ), f"status must indicate rename, got: {f.get('status')!r}"

    def test_get_changed_files_rename_parsing_same_dir_brace(self, monkeypatch) -> None:
        """Same-directory brace notation: git abbreviates same-dir renames with braces.

        Real git output:  3\\t1\\tgovernance/rules/{OLD-NAME.oct.md => NEW-NAME.oct.md}
        """
        numstat_output = "3\t1\tgovernance/rules/{OLD-NAME.oct.md => NEW-NAME.oct.md}\n"
        name_status_output = (
            "R100\tgovernance/rules/OLD-NAME.oct.md\tgovernance/rules/NEW-NAME.oct.md\n"
        )
        self._make_rename_mock(monkeypatch, numstat_output, name_status_output)

        files = validate_review.get_changed_files()

        assert len(files) == 1, f"Expected 1 file, got {len(files)}: {files}"
        f = files[0]
        assert (
            f["path"] == "governance/rules/NEW-NAME.oct.md"
        ), f"path must be new path only, got: {f['path']!r}"
        assert (
            f.get("previous_path") == "governance/rules/OLD-NAME.oct.md"
        ), f"previous_path must be old path, got: {f.get('previous_path')!r}"
        assert f.get("status") in (
            "renamed",
            "R",
        ), f"status must indicate rename, got: {f.get('status')!r}"

    def test_get_changed_files_rename_parsing_cross_dir_brace(self, monkeypatch) -> None:
        """Cross-directory brace notation: git abbreviates dir-level renames with braces.

        Real git output:  3\\t1\\t{old/governance => new/governance}/rule.oct.md
        """
        numstat_output = "3\t1\t{old/governance => new/governance}/rule.oct.md\n"
        name_status_output = "R100\told/governance/rule.oct.md\tnew/governance/rule.oct.md\n"
        self._make_rename_mock(monkeypatch, numstat_output, name_status_output)

        files = validate_review.get_changed_files()

        assert len(files) == 1, f"Expected 1 file, got {len(files)}: {files}"
        f = files[0]
        assert (
            f["path"] == "new/governance/rule.oct.md"
        ), f"path must be new path only, got: {f['path']!r}"
        assert (
            f.get("previous_path") == "old/governance/rule.oct.md"
        ), f"previous_path must be old path, got: {f.get('previous_path')!r}"
        assert f.get("status") in (
            "renamed",
            "R",
        ), f"status must indicate rename, got: {f.get('status')!r}"
