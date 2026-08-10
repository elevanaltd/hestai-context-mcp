"""Submit-review tool: Submit structured review comments on GitHub PRs.

Posts structured review verdicts that clear CI review-gate checks.
Supports dry-run validation without posting. 8 reviewer roles
(CE, CIV, CRS, HO, IL, PE, SR, TMG), 4 verdicts (APPROVED, BLOCKED,
CONDITIONAL, REJECTED), commit SHA pinning for audit trail.

Harvested from hestai-mcp legacy with proven logic preserved.
Fail-closed: validates format before posting.
"""

import json
import subprocess
from typing import Any

from hestai_context_mcp.tools.shared.github_auth import (
    AUTH_ERROR_MESSAGE as _AUTH_ERROR_MESSAGE,
)
from hestai_context_mcp.tools.shared.github_auth import (
    resolve_github_token as _resolve_github_token,
)
from hestai_context_mcp.tools.shared.review_formats import (
    VALID_ROLES,
    VALID_VERDICTS,
    detect_header_verdict_conflict,
    format_review_comment,
    has_ce_approval,
    has_civ_approval,
    has_crs_approval,
    has_ho_review,
    has_pe_approval,
    has_self_review,
    has_sr_approval,
    has_tmg_approval,
)
from hestai_context_mcp.tools.shared.review_gate_retrigger import (
    retrigger_review_gate as _retrigger_review_gate,
)

# GitHub token resolution (three-tier lookup, shape guard, 5 s timeout) and the
# operator-facing auth error message now live in the shared single-source-of-
# truth helper ``tools.shared.github_auth``. They are re-exported here under
# their previous private names (``_resolve_github_token``, ``_AUTH_ERROR_MESSAGE``)
# so call sites resolve them as module globals (patchable in tests). This removed
# the CIV-flagged duplication that previously copied the same logic into
# governance.linker.


def _validate_inputs(
    repo: str,
    pr_number: int,
    role: str,
    verdict: str,
    assessment: str,
) -> str | None:
    """Validate submit_review inputs. Returns error message or None if valid."""
    if role not in VALID_ROLES:
        return f"Invalid role: '{role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}"

    if verdict not in VALID_VERDICTS:
        return f"Invalid verdict: '{verdict}'. Must be one of: {', '.join(sorted(VALID_VERDICTS))}"

    if not assessment or not assessment.strip():
        return "Assessment must not be empty"

    if pr_number < 1:
        return f"Invalid PR number: {pr_number}. Must be a positive integer"

    if not repo or "/" not in repo:
        return f"Invalid repo format: '{repo}'. Must be in owner/name format"

    # Header/verdict agreement (structural fix, verdict-vocabulary-agnostic):
    # if the assessment's own first line already opens with a recognised
    # "<role> <token>:" header for THIS role and that token disagrees with
    # the submitted verdict, the reviewer has stated two different verdicts
    # -- one structured, one in their own prose. The tool must not silently
    # pick one (by prepending over it, or by trusting the prose over the
    # structured verdict), so it refuses the call outright. Requires role
    # and verdict to already be validated above (detect_header_verdict_
    # conflict assumes a known-valid (role, verdict) pair).
    conflicting_token = detect_header_verdict_conflict(assessment, role, verdict)
    if conflicting_token is not None:
        return (
            f"Assessment already opens with a '{role} {conflicting_token}:' header, "
            f"but the submitted verdict is '{verdict}'. The header and the verdict "
            "must agree -- edit the assessment text or change the verdict so they "
            "match."
        )

    return None


def _matches_role_gate(comment: str, role: str) -> bool:
    """Run the role's REAL gate matcher over ``comment``, independent of verdict.

    This is the verdict-independent predicate the symmetric safety check is
    built on (rework #3): it asks "would this text clear role's gate?" using
    the SAME matchers the CI gate itself uses (has_ce_approval, etc.), not a
    model of them (e.g. header shape). detect_header_verdict_conflict() (see
    review_formats.py) is NOT a substitute for this -- it only inspects the
    assessment's leading header, so it missed approving text anywhere else
    in the body: a leading GO/APPROVES header (tokens the gate accepts but
    that were absent from the header-shape allowlist), approval text on a
    later line, a lowercased header, or approval prose with no header shape
    at all. Because this predicate calls the real matcher, none of those
    shapes -- nor any future one -- can evade it; there is no shape-specific
    denylist to maintain. detect_header_verdict_conflict() still earns its
    place for the precise, actionable error on the common contradictory-
    header case and for driving defect-B's dedup -- but it is NOT the safety
    boundary. This function, used symmetrically for BOTH directions in
    submit_review(), is.
    """
    if role == "CRS":
        return has_crs_approval([comment])
    elif role == "CE":
        return has_ce_approval([comment])
    elif role == "TMG":
        return has_tmg_approval([comment])
    elif role == "CIV":
        return has_civ_approval([comment])
    elif role == "PE":
        return has_pe_approval([comment])
    elif role == "SR":
        return has_sr_approval([comment])
    elif role == "IL":
        return has_self_review([comment])
    elif role == "HO":
        return has_ho_review([comment])

    return False


def _check_would_clear_gate(comment: str, role: str, verdict: str) -> bool:
    """Check if the formatted comment would clear the review gate.

    Only APPROVED verdicts can clear gates. BLOCKED, CONDITIONAL, and
    REJECTED are valid review comments but do not clear the gate -- enforced
    by submit_review()'s symmetric check calling _matches_role_gate()
    directly for the non-APPROVED direction; see that function's docstring.
    """
    if verdict != "APPROVED":
        return False

    return _matches_role_gate(comment, role)


def _get_tier_requirements(role: str) -> str:
    """Get human-readable tier requirement description for a role."""
    requirements = {
        "TMG": "TIER_2+: TMG APPROVED/GO required (test methodology review)",
        "CRS": "TIER_2+: CRS APPROVED/GO required",
        "CE": "TIER_2+: CE APPROVED/GO required",
        "CIV": "TIER_3+: CIV APPROVED/GO required (implementation validation)",
        "PE": "TIER_4: PE APPROVED/GO required (strategic review)",
        "SR": "T-STD: SR APPROVED/GO required (standards documentation review)",
        "IL": "TIER_1_SELF: {your-role} SELF-REVIEWED comment required",
        "HO": "TIER_1_SELF: HO REVIEWED comment required (supervisory review)",
    }
    return requirements.get(role, "Unknown tier requirement")


def _parse_http_response(raw_output: str) -> tuple[int, dict[str, str], str]:
    """Parse HTTP response from gh api --include output.

    Args:
        raw_output: Raw HTTP response from gh api --include.

    Returns:
        Tuple of (status_code, headers_dict, body_string).
        Header keys are lowercased for consistent access.
    """
    if "\r\n\r\n" in raw_output:
        parts = raw_output.split("\r\n\r\n", 1)
        line_separator = "\r\n"
    elif "\n\n" in raw_output:
        parts = raw_output.split("\n\n", 1)
        line_separator = "\n"
    else:
        return 0, {}, raw_output

    if len(parts) != 2:
        return 0, {}, raw_output

    header_section, body = parts
    lines = header_section.split(line_separator)

    status_line = lines[0]
    status_parts = status_line.split()
    if len(status_parts) < 2:
        return 0, {}, raw_output

    try:
        status_code = int(status_parts[1])
    except (ValueError, IndexError):
        return 0, {}, raw_output

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key.lower()] = value

    return status_code, headers, body


def _map_status_to_error_type(status: int, headers: dict[str, str]) -> str:
    """Map HTTP status code to error_type for intelligent retry strategies."""
    if status == 429:
        return "rate_limit"
    if status == 403 and headers.get("x-ratelimit-remaining") == "0":
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    if 500 <= status < 600:
        return "network"
    return "validation"


def _post_comment(repo: str, pr_number: int, comment: str) -> dict[str, Any]:
    """Post a comment on a GitHub PR using gh CLI.

    Args:
        repo: Repository in owner/name format.
        pr_number: PR number to comment on.
        comment: Comment body to post.

    Returns:
        Dict with success status and comment URL or error info.
    """
    if _resolve_github_token() is None:
        return {
            "success": False,
            "error": _AUTH_ERROR_MESSAGE,
            "error_type": "auth",
        }

    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--include",
                f"repos/{repo}/issues/{pr_number}/comments",
                "-f",
                f"body={comment}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            error_lower = error_msg.lower()

            if "rate limit" in error_lower or "429" in error_msg:
                error_type = "rate_limit"
            elif "authentication" in error_lower or "401" in error_msg or "403" in error_msg:
                error_type = "auth"
            elif any(
                term in error_lower for term in ["timeout", "connection", "network", "unreachable"]
            ):
                error_type = "network"
            else:
                error_type = "network"

            return {
                "success": False,
                "error": f"GitHub CLI error: {error_msg}",
                "error_type": error_type,
            }

        status, headers, body = _parse_http_response(result.stdout)

        if 200 <= status < 300:
            try:
                response_data = json.loads(body)
                return {
                    "success": True,
                    "comment_url": response_data.get("html_url", ""),
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "comment_url": "",
                }

        error_type = _map_status_to_error_type(status, headers)
        return {
            "success": False,
            "error": f"GitHub API error: HTTP {status}",
            "error_type": error_type,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "GitHub API request timed out (30s)",
            "error_type": "network",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
            "error_type": "network",
        }


def submit_review(
    repo: str,
    pr_number: int,
    role: str,
    verdict: str,
    assessment: str,
    model_annotation: str = "",
    commit_sha: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit a structured review comment on a GitHub PR.

    Formats the comment to clear the review-gate CI check.
    Supports dry-run validation without posting.

    Fail-closed: if format validation fails, the comment is NOT posted.

    Authentication (issue #34):
        When posting (``dry_run=False``), the tool resolves a GitHub token
        via three-tier lookup, in order:

          1. ``GITHUB_TOKEN`` environment variable.
          2. ``GH_TOKEN`` environment variable.
          3. ``gh auth token`` subprocess (5 s timeout) — uses the
             operator's authenticated ``gh`` CLI keyring.

        The MCP server runs as a stdio subprocess and does NOT inherit
        the operator's ``gh`` keyring, so tier 3 is what makes the tool
        usable for agents that have not exported a token into the launch
        environment. The resolved token is opaque to the caller — it is
        never logged, returned, or embedded in error messages. If all
        three tiers fail, the call returns an ``auth`` error whose
        message names all three lookup paths so the operator can
        diagnose which tier needs configuring.

    Args:
        repo: Repository in owner/name format (e.g., 'elevanaltd/HestAI-MCP').
        pr_number: PR number to comment on.
        role: Reviewer role (CE, CIV, CRS, HO, IL, PE, SR, TMG).
        verdict: Review verdict (APPROVED, BLOCKED, CONDITIONAL, REJECTED).
        assessment: Review assessment content.
        model_annotation: Optional model name (e.g., 'Gemini') for annotation.
        commit_sha: Optional PR head SHA the reviewer verified.
        dry_run: If True, validate format without posting.

    Returns:
        Dict with the following top-level fields:

        * ``status`` — ``"ok"`` or ``"error"``.
        * ``comment_url`` — posted comment URL, or ``None`` when not applicable.
        * ``commit_sha`` — echo of the input ``commit_sha`` (or ``None`` when
          not provided). Present on BOTH success and error paths so the
          workbench DISPATCH RETRY-STRATEGY layer can correlate verdicts with
          the commit they were recorded against without traversing the
          response. (Issue #30)
        * ``error_type`` — present ONLY on the error path. One of
          ``"validation"``, ``"auth"``, ``"rate_limit"``, ``"network"``.
          Lifted from the nested ``validation`` block to the top level so
          retry strategies can branch on a deterministic field path.
          (Issue #30)
        * ``validation`` — diagnostic block. ``validation.error`` is present
          on all error responses. ``validation.error_type`` is RETAINED
          additively on the post-API failure branch for backwards
          compatibility; values agree with the top-level ``error_type``.
          Removal is deferred until either hestai-mcp issue #399 reliability
          fix lands OR a future Phase 3 sub-scope on a workbench-team signal
          — DO NOT remove without that coordinated signal.
        * ``dry_run`` — echo of the ``dry_run`` input.
        * ``retrigger`` — present ONLY on the successful, non-dry-run post
          path (issue #145). Best-effort outcome of re-running the most
          recent ``pull_request``-attached Review Gate workflow run for the
          PR's actual head SHA (resolved independently of ``commit_sha``),
          so a verdict posted between pushes updates the required check
          instead of reading as a missing review. A dict with:

            * ``status`` — ``"re-triggered"`` or ``"skipped"``.
            * ``reason`` — ``None`` when re-triggered; a human-readable
              diagnostic string when skipped (no token, no matching run,
              or an Actions API failure).
            * ``run_id`` — the located workflow run id, or ``None``.
            * ``head_sha`` — the resolved PR head SHA, or ``None``.

          Strictly additive and best-effort per
          HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724: a
          re-trigger failure NEVER fails the post (``status`` stays
          ``"ok"``) and NEVER fabricates a gate outcome that was not
          observed.
    """
    # Normalize empty strings to None for internal processing
    annotation = model_annotation if model_annotation else None
    sha = commit_sha if commit_sha else None

    # Step 1: Validate inputs
    error = _validate_inputs(repo, pr_number, role, verdict, assessment)
    if error:
        return {
            "status": "error",
            "comment_url": None,
            "commit_sha": sha,
            "error_type": "validation",
            "validation": {"error": error},
            "dry_run": dry_run,
        }

    # Step 2: Format the comment
    formatted_comment = format_review_comment(
        role=role,
        verdict=verdict,
        assessment=assessment,
        model_annotation=annotation,
        commit_sha=sha,
    )

    # Step 2b: Symmetric fail-open guard (rework #3). The invariant is:
    # a non-approving verdict must NEVER emit a comment that satisfies the
    # role's real gate matcher. detect_header_verdict_conflict() (Step 1)
    # only catches the common contradictory-LEADING-HEADER shape; it cannot
    # see approval text anywhere else in the body -- a leading GO/APPROVES
    # header (gate-clearing tokens absent from the header-shape allowlist),
    # approval text on a later line, a lowercased header, or approval prose
    # with no header shape at all all evade it. This check consults the
    # SAME matcher the CI gate uses (via _matches_role_gate()) on the
    # FINISHED artifact rather than inferring the answer from header shape,
    # so it closes all of those evasions -- and any future one -- at once.
    # Symmetric with the APPROVED-must-clear check below: this is the
    # non-APPROVED-must-NOT-clear direction of the same invariant.
    if verdict != "APPROVED" and _matches_role_gate(formatted_comment, role):
        return {
            "status": "error",
            "comment_url": None,
            "commit_sha": sha,
            "error_type": "validation",
            "validation": {
                "error": (
                    f"Format validation failed: '{verdict}' comment for role "
                    f"'{role}' matches the {role} approval pattern and would "
                    f"incorrectly clear the gate. Offending text: "
                    f"{formatted_comment.split(chr(10), 1)[0]!r}. Reword the "
                    f"assessment so it does not read as an approval for the "
                    f"{role} role."
                ),
                "would_clear_gate": True,
                "tier_requirements": _get_tier_requirements(role),
            },
            "dry_run": dry_run,
        }

    # Step 3: Self-validate against gate patterns
    would_clear = _check_would_clear_gate(formatted_comment, role, verdict)

    # For APPROVED verdicts, the formatted comment MUST clear the gate
    if verdict == "APPROVED" and not would_clear:
        return {
            "status": "error",
            "comment_url": None,
            "commit_sha": sha,
            "error_type": "validation",
            "validation": {
                "error": "Format validation failed: APPROVED comment does not match gate pattern",
                "would_clear_gate": False,
                "tier_requirements": _get_tier_requirements(role),
                "formatted_comment": formatted_comment,
            },
            "dry_run": dry_run,
        }

    validation: dict[str, Any] = {
        "would_clear_gate": would_clear,
        "tier_requirements": _get_tier_requirements(role),
        "formatted_comment": formatted_comment,
    }

    # Step 4: If dry_run, return without posting
    if dry_run:
        return {
            "status": "ok",
            "comment_url": None,
            "commit_sha": sha,
            "validation": validation,
            "dry_run": True,
        }

    # Step 5: Post via GitHub API
    post_result = _post_comment(repo, pr_number, formatted_comment)

    if not post_result["success"]:
        return {
            "status": "error",
            "comment_url": None,
            "commit_sha": sha,
            "error_type": post_result["error_type"],
            "validation": {
                **validation,
                "error": post_result["error"],
                # Nested form RETAINED for backwards compatibility (issue #30
                # AC2 ADDITIVE). Mirrors top-level error_type. Removal
                # deferred — see docstring.
                "error_type": post_result["error_type"],
            },
            "dry_run": False,
        }

    # Step 6: Best-effort Review Gate re-trigger (issue #145). The org-wide
    # ruleset required-workflow feature only enforces pull_request /
    # pull_request_target / merge_group -- it silently drops the
    # issue_comment trigger that would otherwise re-run the gate when this
    # verdict comment lands. Re-running the most recent pull_request-
    # attached run for the PR's head SHA makes the required check re-read
    # the comment we just posted.
    #
    # Gated on `would_clear` (rework #1, PR #148 finding 3) -- the SAME
    # value already computed at Step 3, NOT a fresh `verdict == "APPROVED"`
    # comparison. The gate counts approvals; a non-approving verdict cannot
    # change the outcome, so re-triggering for one would only burn Actions
    # minutes and MCP response latency (retry sleeps + subprocess calls) on
    # every post for no possible effect. Using would_clear rather than a
    # literal verdict check also keeps this correct for the IL/HO
    # SELF-REVIEWED/REVIEWED substitutions without re-deriving that logic
    # here.
    if not would_clear:
        retrigger = {
            "status": "skipped",
            "reason": (
                f"verdict '{verdict}' for role '{role}' does not clear the "
                "gate, so re-triggering it cannot change the outcome"
            ),
            "run_id": None,
            "head_sha": None,
        }
    else:
        # Strictly additive and best-effort per
        # HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724: the post
        # above already succeeded and MUST be reported as such regardless
        # of what happens here. _retrigger_review_gate() is itself designed
        # to never raise, but the call is wrapped defensively anyway so
        # that no failure mode of this step -- expected or not -- can turn
        # a successful post into an error response.
        try:
            retrigger = _retrigger_review_gate(repo, pr_number)
        except Exception as exc:  # noqa: BLE001 -- defense in depth, see comment above
            retrigger = {
                "status": "skipped",
                "reason": f"unexpected error during Review Gate re-trigger: {exc}",
                "run_id": None,
                "head_sha": None,
            }

    return {
        "status": "ok",
        "comment_url": post_result["comment_url"],
        "commit_sha": sha,
        "validation": validation,
        "dry_run": False,
        "retrigger": retrigger,
    }
