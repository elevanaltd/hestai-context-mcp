"""Tests for the clock_in MCP tool handler.

Tests the full return shape per interface contract.
"""

from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.clock_in import clock_in


class TestClockInReturnShape:
    """Verify the clock_in return matches the interface contract."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_returns_all_required_fields(self, mock_branch, tmp_path):
        """Return dict has all fields from interface contract."""
        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
            focus="test-focus",
        )

        # Top-level fields
        assert "session_id" in result
        assert "role" in result
        assert "focus" in result
        assert "focus_source" in result
        assert "branch" in result
        assert "working_dir" in result
        assert "context_paths" in result
        assert "context" in result

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_context_object_structure(self, mock_branch, tmp_path):
        """Context object has the required nested structure."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )

        ctx = result["context"]
        assert "product_north_star" in ctx
        assert "project_context" in ctx
        assert "phase_constraints" in ctx
        assert "git_state" in ctx
        assert "active_sessions" in ctx

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_git_state_structure(self, mock_branch, tmp_path):
        """git_state has branch, ahead, behind, modified_files."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )

        git_state = result["context"]["git_state"]
        assert "branch" in git_state
        assert "ahead" in git_state
        assert "behind" in git_state
        assert "modified_files" in git_state

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_role_propagated(self, mock_branch, tmp_path):
        """Role is propagated to return value."""
        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
        )
        assert result["role"] == "implementation-lead"

    @patch(
        "hestai_context_mcp.tools.clock_in.get_current_branch",
        return_value="feat/my-feature",
    )
    def test_focus_resolution_from_branch(self, mock_branch, tmp_path):
        """Focus is resolved from branch when not explicitly provided."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["focus"] == "feat: my-feature"
        assert result["focus_source"] == "branch"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_explicit_focus_takes_priority(self, mock_branch, tmp_path):
        """Explicit focus overrides branch inference."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
            focus="my-explicit-focus",
        )
        assert result["focus"] == "my-explicit-focus"
        assert result["focus_source"] == "explicit"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_creates_session_directory(self, mock_branch, tmp_path):
        """Clock-in creates the session directory in active/."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        session_dir = tmp_path / ".hestai" / "state" / "sessions" / "active" / result["session_id"]
        assert session_dir.exists()

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_context_paths_is_list(self, mock_branch, tmp_path):
        """context_paths is a list of strings."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert isinstance(result["context_paths"], list)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_active_sessions_is_list(self, mock_branch, tmp_path):
        """active_sessions is a list of strings."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert isinstance(result["context"]["active_sessions"], list)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_reads_north_star_contents(self, mock_branch, tmp_path):
        """Returns North Star file contents when available."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        ns_content = "===NORTH_STAR===\ntest content\n===END==="
        (ns_dir / "000-TEST-NORTH-STAR.oct.md").write_text(ns_content)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["context"]["product_north_star"] == ns_content

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_reads_project_context_contents(self, mock_branch, tmp_path):
        """Returns PROJECT-CONTEXT.oct.md contents when available."""
        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        ctx_content = "===PROJECT_CONTEXT===\ntest\n===END==="
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text(ctx_content)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["context"]["project_context"] == ctx_content

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_always_present_as_structured_dict(self, mock_branch, tmp_path):
        """ai_synthesis is ALWAYS in the response (PROD::I4 structured shape).

        Issue #4: ai_synthesis must never be absent. With no provider wired,
        the fallback dict must still be returned with {source, synthesis}.
        """
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert "ai_synthesis" in result
        ai_syn = result["ai_synthesis"]
        assert isinstance(ai_syn, dict)
        assert set(ai_syn.keys()) == {"source", "synthesis"}
        assert ai_syn["source"] == "fallback"
        assert isinstance(ai_syn["synthesis"], str)
        assert len(ai_syn["synthesis"]) > 0

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_fallback_synthesis_is_octave_template(self, mock_branch, tmp_path):
        """Fallback synthesis string follows the OCTAVE template shape."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
            focus="explicit-focus",
        )
        synthesis_str = result["ai_synthesis"]["synthesis"]
        # OCTAVE template contract: contains key::value lines per legacy reference
        assert "FOCUS::" in synthesis_str
        assert "PHASE::" in synthesis_str
        assert "CONTEXT_FILES::" in synthesis_str

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_ai_seam_returns_source_ai(self, mock_branch, tmp_path, monkeypatch):
        """When the AI seam returns a synthesis dict, response carries source:'ai'.

        Issue #4: AI-success path is wired in #5; this test proves the seam exists
        and is honoured. No provider SDK is imported here — we monkeypatch the seam
        function directly.
        """
        from hestai_context_mcp.core import synthesis as synthesis_mod

        def fake_ai_synthesis(**_kwargs):
            return {"source": "ai", "synthesis": "PHASE::B1_FOUNDATION_COMPLETE\nFOCUS::mocked"}

        monkeypatch.setattr(synthesis_mod, "synthesize_ai_context", fake_ai_synthesis)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["ai_synthesis"]["source"] == "ai"
        assert "mocked" in result["ai_synthesis"]["synthesis"]

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_phase_string_is_full_form_not_abbreviated(self, mock_branch, tmp_path):
        """Phase string returned is the full declared form (e.g. B1_FOUNDATION_COMPLETE).

        Issue #4 acceptance criterion 2: legacy returns full phase strings, new
        server must too. The bare 'B1' form would break the Payload Compiler
        shape-parity gate.
        """
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text(
            "===NORTH_STAR===\nPHASE::B1_FOUNDATION_COMPLETE\n===END==="
        )

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["phase"] == "B1_FOUNDATION_COMPLETE"
        # Must NOT be the bare abbreviation
        assert result["phase"] != "B1"


class TestClockInNorthStarConstraints:
    """Issue #6: structured North Star constraint extraction alongside raw blob.

    The raw `context.product_north_star` field MUST remain unchanged (backward
    compat). A new sibling key `context.product_north_star_constraints` carries
    the structured {scope_boundaries, immutables} dict for the Payload Compiler.
    """

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_constraints_key_always_present(self, mock_branch, tmp_path):
        """The structured key is always in the response (PROD::I4), even when
        no North Star file exists — value is an empty structured result.
        """
        result = clock_in(role="test-role", working_dir=str(tmp_path))
        ctx = result["context"]
        assert "product_north_star_constraints" in ctx
        constraints = ctx["product_north_star_constraints"]
        assert isinstance(constraints, dict)
        assert set(constraints.keys()) == {"scope_boundaries", "immutables"}
        assert constraints["scope_boundaries"] == {}
        assert constraints["immutables"] == []

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_constraints_extracted_from_real_ns_format(self, mock_branch, tmp_path):
        """When an OCTAVE North Star summary exists, structured fields parse.

        Uses the same §2 IMMUTABLES / §4 SCOPE_BOUNDARIES shape as the real repo
        North Star summary file.
        """
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR.oct.md").write_text(
            "===NORTH_STAR_SUMMARY===\n"
            "§2::IMMUTABLES\n"
            'I1::"FOO<PRINCIPLE::a,WHY::b,STATUS::IMPLEMENTED>"\n'
            'I2::"BAR<PRINCIPLE::c,WHY::d,STATUS::IMPLEMENTED>"\n'
            "§4::SCOPE_BOUNDARIES\n"
            "IS::[\n"
            '  "thing one",\n'
            '  "thing two"\n'
            "]\n"
            "IS_NOT::[\n"
            '  "not this",\n'
            '  "not that"\n'
            "]\n"
            "===END===\n"
        )

        result = clock_in(role="test-role", working_dir=str(tmp_path))
        constraints = result["context"]["product_north_star_constraints"]
        assert "is" in constraints["scope_boundaries"]
        assert "is_not" in constraints["scope_boundaries"]
        assert any("thing one" in item for item in constraints["scope_boundaries"]["is"])
        assert any("not this" in item for item in constraints["scope_boundaries"]["is_not"])
        assert len(constraints["immutables"]) == 2
        assert constraints["immutables"][0].startswith("I1::")
        assert constraints["immutables"][1].startswith("I2::")

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_raw_north_star_field_unchanged_when_constraints_added(self, mock_branch, tmp_path):
        """Backward compat: raw product_north_star still carries full file text."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        ns_text = (
            "===NORTH_STAR===\n"
            "§2::IMMUTABLES\n"
            'I1::"X<PRINCIPLE::a,WHY::b,STATUS::IMPLEMENTED>"\n'
            "===END===\n"
        )
        (ns_dir / "000-TEST-NORTH-STAR.oct.md").write_text(ns_text)

        result = clock_in(role="test-role", working_dir=str(tmp_path))
        ctx = result["context"]
        # Raw blob — exact bytes-on-disk
        assert ctx["product_north_star"] == ns_text
        # Structured sibling present and populated
        assert ctx["product_north_star_constraints"]["immutables"][0].startswith("I1::")


class TestClockInConflictsField:
    """Issue #7: surface distinct `conflicts` field from detect_focus_conflicts().

    The response MUST include a `context.conflicts` list of STRUCTURED entries
    (PROD::I4 STRUCTURED_RETURN_SHAPES) so the Payload Compiler can read
    conflicting-session identity directly without deriving it from
    `active_sessions`. `active_sessions` remains unchanged (backward compat).
    """

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_key_always_present(self, mock_branch, tmp_path):
        """`context.conflicts` MUST always be in the response, never null/absent."""
        result = clock_in(role="test-role", working_dir=str(tmp_path))
        ctx = result["context"]
        assert "conflicts" in ctx
        assert isinstance(ctx["conflicts"], list)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_empty_when_no_conflict(self, mock_branch, tmp_path):
        """Empty list when no other session shares the focus — never null."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
            focus="unique-focus",
        )
        assert result["context"]["conflicts"] == []

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_two_same_focus_sessions_surface_first_in_seconds_conflicts(
        self, mock_branch, tmp_path
    ):
        """Behavioural: two sessions with the same focus → second sees the first
        in `conflicts` with STRUCTURED fields (session_id + role, not just focus).

        This is the acceptance criterion from issue #7 and proves the value
        is not merely derivable from `active_sessions` (which only has focus
        strings).
        """
        first = clock_in(
            role="role-a",
            working_dir=str(tmp_path),
            focus="shared-focus",
        )
        second = clock_in(
            role="role-b",
            working_dir=str(tmp_path),
            focus="shared-focus",
        )

        conflicts = second["context"]["conflicts"]
        assert len(conflicts) == 1
        entry = conflicts[0]
        # Structured shape (PROD::I4) — dict, not string
        assert isinstance(entry, dict)
        assert entry["session_id"] == first["session_id"]
        assert entry["role"] == "role-a"
        assert entry["focus"] == "shared-focus"
        # Identity fields the caller cannot get from active_sessions
        # (active_sessions is just a list of focus strings)
        assert second["context"]["active_sessions"].count("shared-focus") >= 1
        # The structured conflicts entry carries session_id which is NOT
        # available in active_sessions — proves the field adds value.
        assert "session_id" in entry

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_active_sessions_shape_unchanged_with_conflicts(self, mock_branch, tmp_path):
        """Backward compat: `active_sessions` remains a list of focus strings."""
        clock_in(role="role-a", working_dir=str(tmp_path), focus="shared-focus")
        second = clock_in(role="role-b", working_dir=str(tmp_path), focus="shared-focus")
        active = second["context"]["active_sessions"]
        assert isinstance(active, list)
        # All entries are strings, not dicts
        assert all(isinstance(x, str) for x in active)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_excludes_own_session(self, mock_branch, tmp_path):
        """A session must not appear as its own conflict."""
        result = clock_in(
            role="solo-role",
            working_dir=str(tmp_path),
            focus="solo-focus",
        )
        # The session just created exists in active/, but should not appear in its own conflicts.
        own_id = result["session_id"]
        for entry in result["context"]["conflicts"]:
            assert entry["session_id"] != own_id

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_surfaces_with_missing_started_at_field(self, mock_branch, tmp_path):
        """Adversarial: pre-existing session.json without `started_at` must not
        break conflict surfacing. Legacy sessions may predate any future field
        additions — loader must use .get(), not [] indexing.
        """
        import json as _json

        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        existing = active_dir / "legacy-session-id"
        existing.mkdir(parents=True)
        (existing / "session.json").write_text(
            _json.dumps(
                {
                    "session_id": "legacy-session-id",
                    "role": "legacy-role",
                    "focus": "shared-focus",
                    "branch": "main",
                    # No started_at
                }
            )
        )

        result = clock_in(role="role-b", working_dir=str(tmp_path), focus="shared-focus")
        conflicts = result["context"]["conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["session_id"] == "legacy-session-id"
        # started_at is optional — allowed to be missing or None
        assert conflicts[0].get("started_at") in (None, "") or "started_at" not in conflicts[0]

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_surfaces_with_missing_branch_field(self, mock_branch, tmp_path):
        """Adversarial: pre-existing session.json without `branch` must not
        break conflict surfacing.
        """
        import json as _json

        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        existing = active_dir / "old-session-id"
        existing.mkdir(parents=True)
        (existing / "session.json").write_text(
            _json.dumps(
                {
                    "session_id": "old-session-id",
                    "role": "old-role",
                    "focus": "shared-focus",
                    "started_at": "2026-04-21T00:00:00+00:00",
                    # No branch
                }
            )
        )

        result = clock_in(role="role-b", working_dir=str(tmp_path), focus="shared-focus")
        conflicts = result["context"]["conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["session_id"] == "old-session-id"
        assert conflicts[0].get("branch") in (None, "") or "branch" not in conflicts[0]

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_conflicts_and_active_sessions_coexist_in_same_response(self, mock_branch, tmp_path):
        """Both `conflicts` and `active_sessions` keys are present simultaneously.

        Backward-compat guarantee: adding `conflicts` MUST NOT remove or alter
        `active_sessions` in the response object.
        """
        result = clock_in(role="solo-role", working_dir=str(tmp_path), focus="solo-focus")
        ctx = result["context"]
        assert "conflicts" in ctx
        assert "active_sessions" in ctx
        assert ctx["conflicts"] == []
        assert isinstance(ctx["active_sessions"], list)


class TestClockInValidation:
    """Test input validation."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_rejects_empty_role(self, mock_branch, tmp_path):
        """Rejects empty role string."""
        with pytest.raises(ValueError, match="[Rr]ole"):
            clock_in(role="", working_dir=str(tmp_path))

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_rejects_path_traversal_in_role(self, mock_branch, tmp_path):
        """Rejects role with path traversal characters."""
        with pytest.raises(ValueError):
            clock_in(role="../evil", working_dir=str(tmp_path))

    def test_rejects_nonexistent_working_dir(self):
        """Rejects working directory that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            clock_in(role="test-role", working_dir="/nonexistent/path/TESTONLY_xyz")
