"""Submit-governance tool: Symbiotic Intake Engine.

Net-new MCP tool implementing GitHub issue #53 (ratified RFC). Transduces
freeform prose authored by an operator into governance artefacts (AGR
records per ADR-RFC-ARCH-004; L1S facet cards per ADR-RFC-ARCH-002) by
wrapping octave-secretary via ``pal_clink(goose)``, then emits a PR via
the ``gh`` CLI.

Defense-in-depth posture (fail-closed in order):

  1. ``RedactionEngine`` runs on ``prose_input`` BEFORE any dispatch into
     the goose subprocess or any git artifact (PROD I2 CREDENTIAL_SAFETY).
     If redaction itself errors, the call REFUSES to dispatch.
  2. Deterministic ``lookup_token_deterministic`` verifies any
     ``SUPERSEDES`` token named by octave-secretary actually exists on
     disk. Pure-Python + filesystem; no LLM call.
  3. In-box schema validators (``validate_agr_record``,
     ``validate_l1s_facet_card``) run BEFORE any PR is emitted.
  4. Only if all gates pass does ``_emit_pr_via_gh`` run.

The goose dispatcher is hidden behind a thin :class:`GooseDispatcher`
Protocol seam (PROD I3 PROVIDER_AGNOSTIC_CONTEXT) so that future
providers can swap in without coupling the tool to goose internals.

Scope (per orchestrator brief and issue #53 §"IL Domain"):
  This tool implements the IL Domain only. It does NOT touch
  ``get_context.py`` (PROD I5 READ_ONLY_CONTEXT_QUERY), does NOT implement
  ``query_context`` / ``lookup_concept`` / G1-G10 gates (explicitly
  deferred), and does NOT modify the rfc-arch ADRs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from hestai_context_mcp.core.redaction import RedactionEngine

# ---------------------------------------------------------------------------
# Provider-adapter seam for the goose dispatch (PROD I3)
# ---------------------------------------------------------------------------


class GooseDispatcher(Protocol):
    """Thin seam over the goose CLI invocation.

    The default implementation shells out via ``pal_clink``. Tests
    inject stubs. Future providers (e.g. Codex, Claude, Gemini) can
    implement this same interface without touching the tool body.
    """

    def dispatch(self, prompt: str) -> list[dict[str, Any]]:
        """Return a list of raw artefact tuples produced by octave-secretary."""
        ...


class PalClinkGooseDispatcher:
    """Default dispatcher: invokes goose via the ``pal_clink`` CLI.

    Output contract: the dispatcher MUST return a list of dicts of the form
    ``{"artifact_kind": "agr"|"facet", "record": {...}}``. The goose-side
    prompt is responsible for emitting this shape; the dispatcher only
    parses the JSON envelope.
    """

    _DEFAULT_TIMEOUT_SECONDS: int = 90

    def __init__(
        self,
        timeout_seconds: int | None = None,
        executable: str = "pal_clink",
    ) -> None:
        self._timeout = timeout_seconds or self._DEFAULT_TIMEOUT_SECONDS
        self._executable = executable

    def dispatch(self, prompt: str) -> list[dict[str, Any]]:
        if shutil.which(self._executable) is None:
            raise RuntimeError(f"goose dispatcher executable not found: {self._executable!r}")
        # No shell=True; argv list with the prompt passed via stdin so it is
        # never shell-interpreted. Keeps redacted prose isolated from argv.
        result = subprocess.run(
            [self._executable, "--cli", "goose", "--role", "octave-secretary"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"goose dispatcher exited {result.returncode}: {result.stderr.strip()}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"goose dispatcher returned non-JSON output: {exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("goose dispatcher must return a JSON list")
        return payload


# ---------------------------------------------------------------------------
# Component C: deterministic SUPERSEDES lookup (~20 LOC, no LLM)
# ---------------------------------------------------------------------------

_DECISIONS_GLOB = "**/*.oct.md"
_FACETS_GLOB = "**/*.oct.md"


def lookup_token_deterministic(working_dir: str | Path, token: str) -> bool:
    """Return True iff ``token`` resolves to an existing artefact on disk.

    Looks under ``.hestai/decisions/`` (AGR records — TOKEN matches the
    filename stem) and ``.hestai/context/concepts/`` (L1S facet cards —
    ID matches the filename stem). Pure-Python + filesystem; this MUST
    NOT call any LLM.
    """
    root = Path(working_dir)
    if not token:
        return False

    def _canonical_stem(path: Path) -> str:
        # `Path("X.oct.md").stem` returns "X.oct" — strip the double suffix.
        name = path.name
        if name.endswith(".oct.md"):
            return name[: -len(".oct.md")]
        return path.stem

    decisions = root / ".hestai" / "decisions"
    if decisions.is_dir():
        for path in decisions.glob(_DECISIONS_GLOB):
            if _canonical_stem(path) == token:
                return True
    contexts = root / ".hestai" / "context" / "concepts"
    if contexts.is_dir():
        for path in contexts.glob(_FACETS_GLOB):
            if _canonical_stem(path) == token:
                return True
    return False


# ---------------------------------------------------------------------------
# Component D: schema validators (ADR-RFC-ARCH-004 AGR; ADR-RFC-ARCH-002 L1S)
# ---------------------------------------------------------------------------

_AGR_REQUIRED_FIELDS: tuple[str, ...] = (
    "type",
    "version",
    "token",
    "status",
    "tier",
    "decision",
    "because",
    "authored_at",
)
_AGR_STATUS_ENUM: frozenset[str] = frozenset({"PROPOSED", "RATIFIED", "SUPERSEDED", "VOID"})
_AGR_TIER_ENUM: frozenset[str] = frozenset({"STRATEGIC", "TACTICAL", "OPERATIONAL"})
_AGR_RESERVED_FIELDS: frozenset[str] = frozenset({"DEPENDS_ON", "CONFLICTS_WITH", "ARCHIVED_AT"})
# Per ADR-RFC-ARCH-004 §1.3, with a 3-char minimum prefix length to align
# with the spec's "3-128 chars" wording. The trailing YYYYMMDD suffix is
# checked separately against AUTHORED_AT.
_AGR_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-(\d{8})$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def validate_agr_record(record: dict[str, Any]) -> list[str]:
    """Validate an AGR record dict against ADR-RFC-ARCH-004 §1.2 / §4.1.

    Returns a (possibly empty) list of human-readable error strings. An
    empty list means the record is well-formed.
    """
    errors: list[str] = []

    for field in _AGR_REQUIRED_FIELDS:
        if field not in record or record[field] in (None, ""):
            errors.append(f"missing required field: {field}")

    if record.get("type") not in (None, "DECISION_RECORD"):
        errors.append("type must be DECISION_RECORD")

    status = record.get("status")
    if status is not None and status not in _AGR_STATUS_ENUM:
        errors.append(f"status {status!r} not in {sorted(_AGR_STATUS_ENUM)}")

    tier = record.get("tier")
    if tier is not None and tier not in _AGR_TIER_ENUM:
        errors.append(f"tier {tier!r} not in {sorted(_AGR_TIER_ENUM)}")

    token = record.get("token")
    token_date_suffix: str | None = None
    if isinstance(token, str):
        match = _AGR_TOKEN_RE.match(token)
        if not match:
            errors.append(f"token {token!r} does not match AGR TOKEN regex")
        else:
            token_date_suffix = match.group(1)

    authored = record.get("authored_at")
    if isinstance(authored, str) and token_date_suffix is not None:
        date_match = _ISO_DATE_RE.match(authored)
        if date_match is not None:
            iso_date = f"{date_match.group(1)}{date_match.group(2)}{date_match.group(3)}"
            if iso_date != token_date_suffix:
                errors.append(
                    "token date suffix does not match authored_at date "
                    f"({token_date_suffix} vs {iso_date})"
                )

    for reserved in _AGR_RESERVED_FIELDS:
        if reserved in record:
            errors.append(f"reserved field present (forbidden in v1.x): {reserved}")

    if status == "SUPERSEDED" and not record.get("superseded_by"):
        errors.append("status=SUPERSEDED requires non-empty superseded_by")

    return errors


_FACET_KIND_ENUM: frozenset[str] = frozenset(
    {"CONCEPT_CARD", "FRAME_CARD", "CLUSTER_CARD", "PHASE_CARD"}
)
_FACET_REQUIRED_FIELDS: tuple[str, ...] = ("kind", "id", "status", "summary")


def validate_l1s_facet_card(card: dict[str, Any]) -> list[str]:
    """Validate an L1S facet ABI card against ADR-RFC-ARCH-002 §1.2 envelope."""
    errors: list[str] = []
    for field in _FACET_REQUIRED_FIELDS:
        if field not in card or card[field] in (None, ""):
            errors.append(f"missing required facet field: {field}")
    kind = card.get("kind")
    if kind is not None and kind not in _FACET_KIND_ENUM:
        errors.append(f"kind {kind!r} not in {sorted(_FACET_KIND_ENUM)}")
    return errors


# ---------------------------------------------------------------------------
# Prompt construction (provider-agnostic shape)
# ---------------------------------------------------------------------------

_PROMPT_HEADER = (
    "You are octave-secretary. Convert the operator's prose into one or more "
    "governance artefacts. Output a JSON array; each element is an object of the "
    'form {"artifact_kind": "agr"|"facet", "record": {...}}. AGR records '
    "conform to ADR-RFC-ARCH-004 §1.2; facet cards conform to ADR-RFC-ARCH-002 "
    "§1.2. Do NOT invent SUPERSEDES targets — only reference tokens you can "
    "verify exist in the corpus below.\n"
)


def _load_few_shot_corpus(working_dir: Path) -> str:
    """Load the L1S facet card corpus + any merged AGRs as few-shot context.

    Read-only filesystem traversal. Failures are non-fatal — corpus
    absence simply yields an empty examples block.
    """
    parts: list[str] = []
    concepts = working_dir / ".hestai" / "context" / "concepts"
    if concepts.is_dir():
        for path in sorted(concepts.glob("**/*.oct.md")):
            try:
                parts.append(f"--- FACET CARD {path.stem} ---\n{path.read_text()}")
            except OSError:
                continue
    decisions = working_dir / ".hestai" / "decisions"
    if decisions.is_dir():
        for path in sorted(decisions.glob("**/*.oct.md")):
            try:
                parts.append(f"--- AGR {path.stem} ---\n{path.read_text()}")
            except OSError:
                continue
    return "\n\n".join(parts)


def _build_goose_prompt(redacted_prose: str, corpus: str) -> str:
    """Compose the provider-agnostic prompt sent to the dispatcher."""
    return (
        f"{_PROMPT_HEADER}\n"
        "=== CORPUS (few-shot exemplars) ===\n"
        f"{corpus}\n"
        "=== OPERATOR PROSE (redacted) ===\n"
        f"{redacted_prose}\n"
        "=== END ===\n"
    )


# ---------------------------------------------------------------------------
# Component E: gh-CLI PR emission (gated on validation success)
# ---------------------------------------------------------------------------


def _slug(token_or_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", token_or_id).strip("-") or "submission"


def _emit_pr_via_gh(
    working_dir: Path,
    artifacts: list[dict[str, Any]],
    pr_title: str,
    pr_body: str,
) -> dict[str, str]:
    """Branch + commit artefacts + open PR via the gh CLI.

    Pure side-effect surface. Called only after every artefact has passed
    schema validation AND every SUPERSEDES reference resolves on disk.
    No ``shell=True``; argv list only. File paths are quoted via argv.
    """
    if not artifacts:
        raise RuntimeError("refusing to open PR with no artefacts")

    first = artifacts[0]
    ident = first["record"].get("token") or first["record"].get("id") or "submission"
    branch = f"governance/{_slug(ident)}"

    # Create + check out branch from current HEAD.
    subprocess.run(
        ["git", "-C", str(working_dir), "checkout", "-b", branch],
        check=True,
        capture_output=True,
        text=True,
    )

    for art in artifacts:
        kind = art["artifact_kind"]
        record = art["record"]
        if kind == "agr":
            dest = working_dir / ".hestai" / "decisions" / f"{record['token']}.oct.md"
        else:
            dest = (
                working_dir
                / ".hestai"
                / "context"
                / "concepts"
                / "hestai-context-mcp"
                / f"{record['id']}.oct.md"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(record, indent=2))
        subprocess.run(
            ["git", "-C", str(working_dir), "add", str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "-C", str(working_dir), "commit", "-m", pr_title],
        check=True,
        capture_output=True,
        text=True,
    )

    pr_result = subprocess.run(
        ["gh", "pr", "create", "--title", pr_title, "--body", pr_body],
        cwd=str(working_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    return {"branch": branch, "pr_url": pr_result.stdout.strip()}


# ---------------------------------------------------------------------------
# Component A: top-level entry point
# ---------------------------------------------------------------------------


def _mcp_response(
    success: bool,
    branch: str | None,
    pr_url: str | None,
    validation_errors: list[str],
    facet_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """PROD I4-conformant structured response."""
    return {
        "success": success,
        "branch": branch,
        "pr_url": pr_url,
        "validation_errors": validation_errors,
        "facet_artifacts": facet_artifacts,
    }


def submit_governance(
    prose_input: str,
    working_dir: str | None = None,
    dry_run: bool = False,
    dispatcher: Any = None,
) -> dict[str, Any]:
    """Transduce operator prose into governance artefacts and open a PR.

    Pipeline (fail-closed at every step):

      1. Validate prose_input is non-empty.
      2. Redact credentials (PROD I2). Engine errors REFUSE dispatch.
      3. Build the few-shot corpus + provider-agnostic prompt.
      4. Dispatch to goose via the injected ``dispatcher`` seam.
      5. For each artefact: schema-validate (AGR or facet); for any
         SUPERSEDES, run ``lookup_token_deterministic``.
      6. On any validation failure: return ``success=False`` with
         ``validation_errors`` populated; emit NOTHING externally.
      7. On all-pass and not ``dry_run``: emit PR via ``gh``.

    Args:
        prose_input: Freeform operator-authored prose. May contain secrets;
            redaction runs before any external exposure.
        working_dir: Repository root. Defaults to the current process cwd.
        dry_run: If True, validators run but the PR step is skipped.
        dispatcher: Optional injection seam (must satisfy
            :class:`GooseDispatcher`). Typed ``Any`` so the FastMCP /
            pydantic introspection layer accepts the tool registration;
            the runtime contract is still the Protocol. Defaults to the
            ``pal_clink(goose)`` implementation. Tests inject stubs.

    Returns:
        MCPResponse dict with keys: ``success``, ``branch``, ``pr_url``,
        ``validation_errors``, ``facet_artifacts``. Per PROD I4
        STRUCTURED_RETURN_SHAPES; never a free-text blob.
    """
    if not prose_input or not prose_input.strip():
        return _mcp_response(
            success=False,
            branch=None,
            pr_url=None,
            validation_errors=["prose_input is empty"],
            facet_artifacts=[],
        )

    root = Path(working_dir) if working_dir else Path.cwd()

    # Step 2 — fail-closed redaction (PROD I2).
    try:
        redaction = RedactionEngine().redact(prose_input)
    except Exception as exc:  # noqa: BLE001 — fail-closed by design
        return _mcp_response(
            success=False,
            branch=None,
            pr_url=None,
            validation_errors=[f"redaction_failed: {exc}"],
            facet_artifacts=[],
        )

    # Step 3 — corpus + prompt.
    corpus = _load_few_shot_corpus(root)
    prompt = _build_goose_prompt(redaction.redacted_text, corpus)

    # Step 4 — dispatch (injected for tests; defaults to pal_clink).
    if dispatcher is None:
        dispatcher = PalClinkGooseDispatcher()
    try:
        raw_artifacts = dispatcher.dispatch(prompt)
    except Exception as exc:  # noqa: BLE001 — surface dispatch failures structurally
        return _mcp_response(
            success=False,
            branch=None,
            pr_url=None,
            validation_errors=[f"dispatch_failed: {exc}"],
            facet_artifacts=[],
        )

    # Step 5 — validate every artefact + SUPERSEDES targets.
    validation_errors: list[str] = []
    for idx, art in enumerate(raw_artifacts):
        if not isinstance(art, dict):
            validation_errors.append(f"artifact[{idx}] is not an object")
            continue
        kind = art.get("artifact_kind")
        record = art.get("record")
        if kind not in {"agr", "facet"} or not isinstance(record, dict):
            validation_errors.append(f"artifact[{idx}] missing artifact_kind/record")
            continue
        if kind == "agr":
            errors = validate_agr_record(record)
            supersedes = record.get("supersedes") or record.get("superseded_by")
            if supersedes and not lookup_token_deterministic(root, supersedes):
                errors.append(f"supersedes target not found in corpus: {supersedes}")
        else:
            errors = validate_l1s_facet_card(record)
        validation_errors.extend(f"artifact[{idx}]: {e}" for e in errors)

    if validation_errors:
        return _mcp_response(
            success=False,
            branch=None,
            pr_url=None,
            validation_errors=validation_errors,
            facet_artifacts=list(raw_artifacts),
        )

    if dry_run:
        return _mcp_response(
            success=True,
            branch=None,
            pr_url=None,
            validation_errors=[],
            facet_artifacts=list(raw_artifacts),
        )

    # Step 7 — emit PR. Side effects gated behind every validator above.
    first_ident = (
        raw_artifacts[0]["record"].get("token")
        or raw_artifacts[0]["record"].get("id")
        or "submission"
    )
    try:
        emission = _emit_pr_via_gh(
            working_dir=root,
            artifacts=list(raw_artifacts),
            pr_title=f"governance: {first_ident}",
            pr_body=(
                "Auto-generated by submit_governance (Symbiotic Intake Engine). "
                "All artefacts passed in-box schema validation and SUPERSEDES "
                "lookup before this PR was opened."
            ),
        )
    except Exception as exc:  # noqa: BLE001 — surface gh failures structurally
        return _mcp_response(
            success=False,
            branch=None,
            pr_url=None,
            validation_errors=[f"pr_emission_failed: {exc}"],
            facet_artifacts=list(raw_artifacts),
        )

    return _mcp_response(
        success=True,
        branch=emission["branch"],
        pr_url=emission["pr_url"],
        validation_errors=[],
        facet_artifacts=list(raw_artifacts),
    )
