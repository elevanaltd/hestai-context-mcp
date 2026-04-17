"""Submit-review tool: Submit structured review comments on GitHub PRs.

Posts structured review verdicts that clear CI review-gate checks.
Supports dry-run validation without posting. 8 reviewer roles
(CE, CIV, CRS, HO, IL, PE, SR, TMG), 3 verdicts (APPROVED, BLOCKED,
CONDITIONAL), commit SHA pinning for audit trail.

Harvested from hestai-mcp legacy with proven logic preserved.
Fail-closed: validates format before posting.
"""

import json
import os
import subprocess
from typing import Any

from hestai_context_mcp.tools.shared.review_formats import (
    VALID_ROLES,
    VALID_VERDICTS,
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

    return None


def _check_would_clear_gate(comment: str, role: str, verdict: str) -> bool:
    """Check if the formatted comment would clear the review gate.

    Only APPROVED verdicts can clear gates. BLOCKED and CONDITIONAL
    are valid review comments but do not clear the gate.
    """
    if verdict != "APPROVED":
        return False

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
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {
            "success": False,
            "error": "GITHUB_TOKEN or GH_TOKEN environment variable not set",
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

    Args:
        repo: Repository in owner/name format (e.g., 'elevanaltd/HestAI-MCP').
        pr_number: PR number to comment on.
        role: Reviewer role (CE, CIV, CRS, HO, IL, PE, SR, TMG).
        verdict: Review verdict (APPROVED, BLOCKED, CONDITIONAL).
        assessment: Review assessment content.
        model_annotation: Optional model name (e.g., 'Gemini') for annotation.
        commit_sha: Optional PR head SHA the reviewer verified.
        dry_run: If True, validate format without posting.

    Returns:
        Dict with status, comment_url, validation, and dry_run fields.
        Error responses include validation.error for diagnosis.
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

    # Step 3: Self-validate against gate patterns
    would_clear = _check_would_clear_gate(formatted_comment, role, verdict)

    # For APPROVED verdicts, the formatted comment MUST clear the gate
    if verdict == "APPROVED" and not would_clear:
        return {
            "status": "error",
            "comment_url": None,
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
            "validation": validation,
            "dry_run": True,
        }

    # Step 5: Post via GitHub API
    post_result = _post_comment(repo, pr_number, formatted_comment)

    if not post_result["success"]:
        return {
            "status": "error",
            "comment_url": None,
            "validation": {
                **validation,
                "error": post_result["error"],
                "error_type": post_result["error_type"],
            },
            "dry_run": False,
        }

    return {
        "status": "ok",
        "comment_url": post_result["comment_url"],
        "validation": validation,
        "dry_run": False,
    }
