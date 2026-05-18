# ADR-RFC-ARCH-002 — Information-Architecture Contract, CI Gate Specification, and MCP-Tool Fail-Fast Requirement

- **Status**: PROPOSED (awaiting CIV + SR review)
- **Date**: 2026-05-18
- **Scope**: hestai-context-mcp repository; LOCAL repo-relative paths in full; cross-repo authoritative references defined here for the first time
- **Sequence**: PR-B (this ADR)
- **Supersedes**: ADR-RFC-ARCH-001 (PR-α, the placement invariant) — see §6
- **Related**: ADR-RFC-ARCH-001, `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md`, `.hestai/context/concepts/hestai-context-mcp/CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME.oct.md`, RFC #38 (Facet ABI), RFC #40 (Agent-Readable Governance Records)
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; operator-ratified convergent L0-L5 architecture (debate-hall 2026-05-16); three Principal Engineer amendments folded in verbatim (see §0.2)
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT), PROD::I4 (STRUCTURED_RETURN_SHAPES), PROD::I5 (READ_ONLY_CONTEXT_QUERY), PROD::I6 (LEGACY_INDEPENDENCE) interpreted as scope-boundary discipline, SYS::I1 (CONTEXT_INTEGRITY), SYS::I6 (scope boundary)
- **Implementation owners (deferred)**: PR-F (MCP-tool fail-fast) — implementation-lead; PR-G (CI gate) — implementation-lead; PR-D (RFC #40 decision-record format) — separate ADR; PR-E (ledger schema) — separate ADR

## 0. Reading guide

This ADR contains **three governance artefacts in one document**, sequenced so each builds on the prior:

- **§1 — IA Contract** defines what placements exist, what is authoritative, how references resolve, and how queries route between the stable/structural and temporal/historic layers. This supersedes ADR-RFC-ARCH-001.
- **§2 — CI Gate Specification** specifies the review-time backstop: what it scans, what it rejects, what is out of scope, and its severity model. **This is a specification only; implementation is PR-G.**
- **§3 — MCP-Tool Fail-Fast Requirement** specifies the primary defense at the tool boundary: which tools must reject which writes, the precise definition of "governance-class", and the PROD::I4-conformant error shape. **This is a specification only; implementation is PR-F.**

§4 closes the invariant chain, §5 specifies the verification process for this ADR itself, §6 records the supersession of ADR-RFC-ARCH-001, §7 enumerates explicit non-goals, and §8 names downstream owners.

### 0.1 Defense-in-depth ordering

By Principal Engineer ruling (PE amendment 3, §0.2), the MCP-tool fail-fast contract in §3 is the **primary** defense; the CI gate in §2 is the **backstop**. The ordering reflects mechanism: a tool that fails closed at write time prevents the violation; a CI gate at review time depends on a human running review. Implementations must respect this ordering — PR-F **must not** be deferred behind PR-G.

### 0.2 Principal Engineer amendments (immutable in PR-B scope)

The following three amendments were ruled by the Principal Engineer prior to PR-B drafting and are immutable here. Any subsequent ADR that wishes to alter them must cite this ADR and treat the change as supersession.

1. **CI gate scoped to LOCAL repo-relative paths only.** The gate **must not** flag URIs, opaque tokens, content-addressed identifiers, or cross-repo references. False positives on these classes were ruled an unacceptable regression. The cross-repo reference rules live in §1.4 (IA Contract), enforced at the tool boundary (§3) and by human review, not by the CI gate.
2. **IA Contract must include explicit query-routing rules.** The contract must say, in normative form, when a query routes to RFC #38 (`lookup_concept`, stable/structural) versus RFC #40 (`lookup_decision`, temporal/historic). The stable-vs-temporal boundary must be explicit. See §1.5.
3. **MCP-tool fail-fast enforcement is the primary defense.** Tools that perform governance-class writes (currently `clock_out` for committed artefact emission and `octave_write` for OCTAVE-grammar artefacts) **must** reject writes that violate the IA Contract at the tool boundary. The CI gate is the secondary, review-time backstop. See §3.

## 1. IA Contract

### 1.1 Layered topology (carry-forward of the convergent L0–L5 architecture)

The convergent architecture ratified by debate-hall on 2026-05-16 (and recorded in `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` for the RFC #38 sub-architecture) is binding here as the topology that this IA Contract regulates. The five layers in force:

| Layer | Substance | Authority | Git status |
|---|---|---|---|
| **L0** Canonical | DECISIONS, North Stars, ADRs (this document is L0) | Authoritative; never gitignored | committed |
| **L1** Phase governance | BUILD-PLANs, arbitration records, phase handoffs, completion ledgers | Authoritative; never gitignored | committed |
| **L1S** Facet ABI | Concept / Frame / Cluster / Phase cards (RFC #38 substrate) | Authoritative; never gitignored | committed |
| **L2** Acceleration | Content-hash-keyed retrieval cache | **Never authoritative**; rebuildable | gitignored |
| **L3** Retrieval | Pure read-only MCP tools (`get_context`, RFC #38 `lookup_concept`, RFC #40 `lookup_decision`) | Not artefact-bearing; queries only | n/a |
| **L4** Session-local | `session.json`, FAST-tier session state, in-flight ledgers | **Never authoritative** as committed governance; per-session scratch | gitignored |
| **L5** (none assigned) | Reserved | — | — |

**No artefact may be authoritative at L2 or L4.** Authoritative governance lives at L0/L1/L1S. L2 is an optional performance layer; L4 is per-session scratch. This is the unifying constraint the IA Contract enforces.

### 1.2 Placement categories (refinement of ADR-RFC-ARCH-001)

ADR-RFC-ARCH-001 (PR-α) defined four placement categories for LOCAL paths. This ADR **carries those categories forward verbatim** and refines two aspects: (a) the mapping to the L0–L5 topology above is made explicit, and (b) the `committed_governance` root admits ADR sub-grouping by RFC family (e.g. `.hestai/decisions/rfc-arch/…`) without altering the invariant.

| Category | Path root | Layer | Git status | Purpose |
|---|---|---|---|---|
| `committed_governance` | `.hestai/decisions/` | L0 (ADRs, North Stars) ∪ L1 (BUILD-PLANs, arbitrations, handoffs) | committed | Authoritative governance artefacts |
| `committed_context_cards` | `.hestai/context/` | L1S | committed | Facet ABI cards under RFC #38 |
| `ephemeral_session_state` | `.hestai/state/sessions/` | L4 | gitignored | Per-session scratch; never authoritative |
| `optional_cache` | `.hestai/state/cache/` | L2 | gitignored | Content-hash-keyed retrieval cache; never authoritative |

The PR-α invariant remains in force exactly as written:

> Any artifact referenced by an open issue, ADR, RFC, PR body, or committed facet card as authoritative MUST resolve to a committed repo-relative path OR be explicitly marked ephemeral/non-authoritative at the reference site.

This ADR retains the explicit `EPHEMERAL` / `NON_AUTHORITATIVE` marker convention from PR-α §2: a reference that points into `ephemeral_session_state` or `optional_cache` is a violation unless the marker is adjacent to the reference site.

### 1.3 Authoritativeness, distilled

A path is **authoritative** when it satisfies all of:

1. Its category in §1.2 is `committed_governance` or `committed_context_cards`.
2. Its layer is L0, L1, or L1S.
3. It resolves under the repository root at the commit currently being reviewed.
4. It is referenced as authoritative from at least one of: an open issue, an ADR, an RFC body, a PR body, or a committed facet card.

A path is **non-authoritative** when (any of):

- Its layer is L2 (optional cache) or L4 (session-local), regardless of how often it is referenced.
- The reference site explicitly carries the marker `EPHEMERAL` or `NON_AUTHORITATIVE`.
- It is an external URI, a cross-repo reference (see §1.4), an opaque token, or a content-addressed identifier (see §1.4.2).

### 1.4 Cross-repo authoritative references (new in PR-B)

PR-α scoped the placement invariant to LOCAL repo-relative paths only. PR-B extends the contract to cross-repo references, **without** extending the CI gate to them (PE amendment 1).

#### 1.4.1 Resolution rule

A cross-repo authoritative reference resolves via **exactly one of** the following two mechanisms, in this preference order:

1. **Committed path in the other repository**, expressed as `repo:<repo-id>:<repo-relative-path>` at a stable revision (branch name `main` is acceptable; a commit SHA is preferred for historical correctness). Example: `repo:elevanaltd/hestai-workbench:.hestai/decisions/2026-05-01-oq1-workbench-hestai-context-wiring.oct.md@main`.
2. **Explicit external pin**, a pinned URL with the form `pin:<url>@<rev-or-tag-or-content-hash>`, where the pin target is itself authoritative under the conventions of the receiving repository. Example: `pin:https://github.com/elevanaltd/hestai-workbench/blob/<sha>/path/to/decision.md@<sha>`.

Bare URLs without a pin are **not** authoritative references for the purpose of this contract. They are advisory pointers and must be marked `NON_AUTHORITATIVE` at the reference site if they appear in a governance artefact.

#### 1.4.2 What is explicitly out of scope of cross-repo authoritativeness

The following classes of identifier **never** participate in the placement invariant and **never** trigger any gate or fail-fast check:

- Opaque tokens (e.g. HO-token-style identifiers such as `HO-CONTEXT-MCP-OWNS-AGR-STANDARD-20260513`).
- Content-addressed identifiers (e.g. cache content hashes, git object hashes used as identifiers).
- URI schemes that are not `repo:` or `pin:` (e.g. `mailto:`, `urn:`, `tag:`).
- Cross-repo references that the receiving repository's own IA Contract has not declared authoritative.

This list is exhaustive for PR-B. Future ADRs may extend it.

#### 1.4.3 Cross-repo reference reciprocity (advisory)

A cross-repo authoritative reference is only as strong as the receiving repository's own IA Contract. When this repository points authoritatively into another repository, the reference is binding here. Whether the *other* repository treats the same target as authoritative is governed by *that* repository's contract. This ADR does not impose IA Contract obligations on other repositories.

### 1.5 Query-routing rules between RFC #38 and RFC #40 (PE amendment 2)

This sub-section is normative. It says when a query routes to RFC #38 (`lookup_concept`, stable/structural) versus RFC #40 (`lookup_decision`, temporal/historic).

#### 1.5.1 The stable-vs-temporal boundary

A piece of governance is **stable/structural** when its content describes how the system is organised, what types of things exist, and how they relate. Examples: ADRs once ratified, facet cards (RFC #38 substrate), North Stars, layer definitions. Stable content can be superseded, but its meaning at the commit at which it was written does not change.

A piece of governance is **temporal/historic** when its content records a decision, a state transition, or an event tied to a specific moment. Examples: arbitration records, phase completion ledgers, decision records (RFC #40 substrate), handoffs, RD-class entries. Temporal content accumulates; old entries do not become wrong, they become history.

The boundary is **not** drawn by file extension or directory. It is drawn by the question being asked.

#### 1.5.2 Routing rules

| Query intent | Routes to | Tool |
|---|---|---|
| "What kind of thing is X?" / "How does X relate to Y?" / "What is the canonical structure of X?" | RFC #38 | `lookup_concept` |
| "What did we decide about X, and when?" / "Why did we choose X over Y?" / "What is the history of X?" | RFC #40 | `lookup_decision` |
| "What is the authoritative current state of X?" | Compose: `lookup_concept` for structure ∪ `lookup_decision` for the most recent non-superseded decision | both, joined client-side at L3 |
| "Where do I find the artefact at path P?" | Direct resolution against the IA Contract (this ADR) | neither — read the file |

`get_context` is **not** a routing target; it is the existing read-only context-synthesis tool (PROD::I5) and is exempt from any routing change in this ADR. RFC #38 and RFC #40 tools are additive to `get_context`.

#### 1.5.3 Routing under cross-repo references

A query whose answer requires reading a cross-repo authoritative reference (per §1.4) routes the same way internally; cross-repo dereferencing happens at the read step, not the routing step. The receiving repository's IA Contract decides what is authoritative there; the routing logic here decides which question is being asked.

### 1.6 Closure of the SKILL provenance loop

PR-α §6 recorded the verbatim `ho-control-room` SKILL §3 amendment that closed the proximate cause of the Mac B#1 governance leak (the SKILL previously directed phase artefacts to gitignored paths). That amendment has landed upstream and the SKILL now cites ADR-RFC-ARCH-001 in its `DIRECT_WRITE_ALLOWED` REFS (see PR-α §3).

PR-B (this ADR) does not re-amend the SKILL. It carries the SKILL's current state forward as the operational vocabulary for HO sessions: `.hestai/decisions/` is the write destination for committed governance; `.hestai/state/sessions/` is ephemeral. The SKILL's compliance with this ADR is observed, not legislated here.

If future PR-Bn revisions introduce new placement categories or rename existing ones, the SKILL amendment in lockstep is a release requirement, not optional. The cross-cutting binding finding recorded in `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` documents the cost of failing this requirement and remains the binding precedent.

## 2. CI Gate Specification (PR-G implementation deferred)

This section specifies the CI gate. **The CI gate is a review-time backstop, not the primary defense** (PE amendment 3, §0.1). Its purpose is to flag IA Contract violations that survived the tool-boundary defense (§3) so a human reviewer is forced to look. Implementation lands in PR-G.

### 2.1 Scope: what the gate scans

The gate scans the textual diff of every pull request for **authoritative-style references** that point into **LOCAL repo-relative paths** that fall in `ephemeral_session_state` (L4) or `optional_cache` (L2), where the reference site does **not** carry an `EPHEMERAL` or `NON_AUTHORITATIVE` marker.

"Authoritative-style reference" is defined operationally as one of:

- A markdown link whose target resolves to a LOCAL repo-relative path: `[…](.hestai/state/sessions/…)` or `[…](./.hestai/state/cache/…)`.
- A bare LOCAL repo-relative path of the form `.hestai/state/sessions/…` or `.hestai/state/cache/…` appearing in a governance artefact (`.hestai/decisions/**`, `.hestai/context/**`, ADR/RFC/PR bodies).
- An OCTAVE atom of the form `PATH::".hestai/state/sessions/…"` or `PATH::".hestai/state/cache/…"` in a committed facet card or governance OCTAVE document.

### 2.2 Out of scope (PE amendment 1 — strict)

The gate **must not** scan and **must not** flag:

- URIs of any scheme (`http://`, `https://`, `mailto:`, `urn:`, etc.).
- Cross-repo references in either form defined in §1.4.1 (`repo:…` or `pin:…`).
- Opaque tokens (HO-token-style identifiers; any string matching `^[A-Z][A-Z0-9_-]{8,}$` in a context that is not a path).
- Content-addressed identifiers (git SHAs, cache content hashes used as identifiers).
- Files in the repository that are not part of governance: source code (`src/**`), tests (`tests/**`), build infrastructure, generated artefacts, configuration. Comments and docstrings in source code that mention `.hestai/state/sessions/` for instructive purposes do not trigger the gate.

A false positive in this gate is a worse outcome than a false negative, because false positives erode trust in the rule and create pressure to disable the gate. The fail-fast contract in §3 catches what the gate must let through.

### 2.3 Repo-relative path recognition (precise)

The gate recognises a LOCAL repo-relative path by **all** of the following holding:

1. The string is not enclosed in a URI scheme.
2. The string starts with `.hestai/state/sessions/` or `.hestai/state/cache/` (with optional leading `./`).
3. The string contains no `:` outside the `.hestai/` segment (rejects URIs that happen to contain `.hestai/state/...`).
4. The string is not part of a longer token (preceded and followed by whitespace, punctuation in `[](){}.,;:` or end-of-line).

The path itself does not need to exist on disk for the gate to fire; the gate is text-based by design (PE amendment 1).

### 2.4 Marker convention

A reference is **exempted** from the gate when one of the following markers appears within the same paragraph (markdown) or within the same OCTAVE atom block (facet card):

- The literal token `EPHEMERAL` (uppercase).
- The literal token `NON_AUTHORITATIVE` (uppercase).
- An OCTAVE comment of the form `# ephemeral` immediately preceding the atom.

Inline markers like `<!-- ephemeral -->` are **not** sufficient; the marker must be readable in rendered governance prose so reviewers see it.

### 2.5 Severity model

The gate operates with three severities. Each severity declares what the CI job does and what a reviewer is allowed to do.

| Severity | Trigger | CI job behaviour | Reviewer action |
|---|---|---|---|
| **blocking** | Authoritative-style reference into L2/L4 path, no marker, in a governance artefact (`.hestai/decisions/**`, `.hestai/context/**`) | CI job fails; PR cannot merge | Must add marker, fix path to L0/L1/L1S, or remove reference |
| **advisory** | Authoritative-style reference into L2/L4 path, no marker, in a non-governance file (e.g. README, CLAUDE.md, source comment) | CI job warns; PR can merge | Reviewer judges whether to fix; no automatic block |
| **exempt** | Reference carries marker; reference is via URI or cross-repo form; reference appears in test fixtures or example files explicitly marked as fixtures | No CI signal | No action |

The blocking class is intentionally narrow. The intent is to keep the CI gate's false-positive rate near zero so that a blocking signal is taken seriously. Advisory warnings let the gate carry diagnostic value without weight-of-merge pressure.

### 2.6 Exemption mechanisms (escape hatches)

Two mechanisms exempt a specific PR or file from the gate:

1. **In-file exemption.** A governance artefact may declare `<!-- ia-gate: exempt reason="…" -->` at the top. The reason field is **mandatory**; PR-G implementation must reject empty reasons. Exemption logs in the CI artefact for audit.
2. **Allowlist file.** PR-G will introduce a single allowlist file (`.hestai/decisions/rfc-arch/ia-gate-allowlist.txt`) listing paths exempt from gating. Adding to this file requires CIV review. The intent is not routine exemption; it is a documented release valve for cases this ADR did not anticipate.

The CI gate may **not** be disabled globally without amending this ADR.

### 2.7 Gate dependency on the IA Contract

The CI gate enforces §1 of this ADR. If §1 is amended in a future ADR, PR-G implementation must update the gate definitions in lockstep. The gate does not enforce §3 — that is the tool-boundary defense and is implemented by PR-F.

### 2.8 What this section does not specify

This section specifies **what** the gate enforces, **when** it blocks, and **what** it must not flag. It does **not** specify:

- The programming language, framework, or runtime of the gate implementation. PR-G chooses.
- Where in CI it runs (per-job, per-workflow, pre-commit hook). PR-G chooses, with the constraint that it must run on every pull request before merge.
- The exact diagnostic message text. PR-G drafts and proposes for review.

Implementation owner: implementation-lead, scoped to PR-G.

## 3. MCP-Tool Fail-Fast Requirement (PR-F implementation deferred)

This section specifies the primary defense (PE amendment 3): governance-class writes that would violate the IA Contract are rejected at the MCP tool boundary, before the write reaches disk. Implementation lands in PR-F.

### 3.1 Tools in scope

This requirement applies to MCP tools that produce committed governance artefacts:

- **`clock_out`** — when its archival path lands inside `.hestai/decisions/**` or `.hestai/context/**`, or when it surfaces a candidate path for promotion into either of those subtrees.
- **`octave_write`** — when its target path is in `.hestai/decisions/**` or `.hestai/context/**`, or whenever the document META declares `TYPE::FRAME_CARD`, `TYPE::CONCEPT_CARD`, `TYPE::CLUSTER_CARD`, `TYPE::PHASE_CARD`, `TYPE::ADR`, `TYPE::BUILD_PLAN`, `TYPE::ARBITRATION_RECORD`, `TYPE::HANDOFF`, `TYPE::DECISION_RECORD`, or any other type that PR-D / future ADRs declare governance-class.

Tools **not** in scope:

- **`get_context`** — exempt by PROD::I5 (READ_ONLY_CONTEXT_QUERY). `get_context` performs no writes and cannot violate the IA Contract.
- **`clock_in`** — does not produce governance artefacts; produces session bootstrap state.
- **`submit_review`** — produces structured review verdicts; if PR-F implementation determines that any of its outputs land at governance-class paths, the scope extends; otherwise it is exempt.

The list above is current as of PR-B drafting. When new MCP tools that emit governance-class artefacts are introduced, they inherit this requirement automatically by their TYPE declaration (see §3.2.2).

### 3.2 "Governance-class" — defined by IA category, not filename heuristic

Per PE amendment 3, the rejection rule must not be a filename-heuristic. A write is **governance-class** when **either** of the following holds:

#### 3.2.1 By path category

The target path resolves under `.hestai/decisions/` (`committed_governance`) or `.hestai/context/` (`committed_context_cards`) per §1.2.

#### 3.2.2 By document META TYPE

The document being written carries an OCTAVE `META.TYPE` atom whose value is in the governance-class TYPE set declared in §3.1 (`FRAME_CARD`, `CONCEPT_CARD`, `CLUSTER_CARD`, `PHASE_CARD`, `ADR`, `BUILD_PLAN`, `ARBITRATION_RECORD`, `HANDOFF`, `DECISION_RECORD`, …). This catches the case where the path is in flux (e.g. a draft path under `.hestai/state/sessions/`) but the document's self-declared type is authoritative governance.

A write satisfies one rule and not the other → governance-class.
A write satisfies neither → not governance-class; not subject to fail-fast.

### 3.3 Rejection rule

A governance-class write **must be rejected at the tool boundary** when:

1. The target path is LOCAL repo-relative, and
2. The target path resolves into `ephemeral_session_state` (`.hestai/state/sessions/`) or `optional_cache` (`.hestai/state/cache/`), and
3. The write payload does not carry an explicit `EPHEMERAL` or `NON_AUTHORITATIVE` marker in the document body.

Rejection is at the **tool boundary**: the tool must not write the file, must not partial-write, must not retry, must not emit a warning-only return. It returns the structured error described in §3.4.

Cross-repo writes (writes whose target path resolves outside the repository) are out of scope for the tool boundary defense. Cross-repo placement obligations are enforced by the receiving repository's contract; PR-F is not responsible for them.

### 3.4 Error shape (PROD::I4-conformant)

The rejection error is a structured dictionary, conforming to PROD::I4 (STRUCTURED_RETURN_SHAPES). The minimum schema is:

```
{
  "ok": false,
  "error": {
    "code": "IA_CONTRACT_VIOLATION",
    "category": "governance_class_write_to_ephemeral_path",
    "path": "<repo-relative-path-attempted>",
    "ia_category": "<one of: ephemeral_session_state | optional_cache>",
    "detected_governance_signal": "<one of: path_category | document_type | both>",
    "document_type": "<META.TYPE value if detected by §3.2.2, else null>",
    "suggested_marker": "<EPHEMERAL or NON_AUTHORITATIVE>",
    "remediation": "<one-line human-readable suggestion>",
    "contract_ref": "ADR-RFC-ARCH-002 §1.2 §3.3"
  }
}
```

Implementations **may** add fields (e.g. session_id, tool_version, timing) but **must not** remove or rename the required fields. PR-F selects the exact field types and validation rules; the shape above is the contract.

The error is **terminal** for the write call. The caller (workbench, octave-secretary, or any other consumer) is expected to surface this structured error to the operator or upstream agent, not silently retry.

### 3.5 What this section does not specify

This section specifies the **contract**: which tools, which writes, which paths, which document types, what error shape. It does **not** specify:

- Where in the tool's code path the check fires (parser layer, write layer, post-validation hook). PR-F chooses, subject to the constraint that no governance-class write reaches disk on the failing path.
- The exact wording of `remediation`. PR-F drafts; reviewers comment.
- How the redaction engine, IdentityResolver, or other existing components interact with the check. PR-F integration design.

Implementation owner: implementation-lead, scoped to PR-F.

### 3.6 Why fail-fast precedes CI

The CI gate (§2) and the tool-boundary defense (§3) cover overlapping but distinct failure surfaces. The tool defense catches writes by automated agents (HO sessions, octave-secretary, dispatched specialists) before disk; the CI gate catches references in human-authored prose and any tool writes that slipped through (for example, in a tool that PR-F has not yet covered).

If only one of the two existed, the CI gate would let bad writes land on disk and be caught only at review (Mac B#1 cost). The tool defense would let human-authored prose carry phantom references into governance documents without catching them. Both together make the IA Contract operationally enforced; either alone makes it advisory.

PR-F is therefore not "implementation of an idea also covered by PR-G". The defense in depth is intentional.

## 4. Invariant chain

This ADR is an instantiation of the following invariants from the System Standard and Product North Star:

- **SYS::I1 CONTEXT_INTEGRITY** — "Agent MUST declare ROLE and PHASE before action" generalises at the artefact layer to: an artefact must resolve to a committed path before it is treated as authoritative.
- **SYS::I6** (scope boundary discipline) — PR-B regulates artefact placement and tool-write contracts within hestai-context-mcp and does not encroach on Vault (agent definitions, skills), Workbench (UI, dispatch), DebateHall (deliberation records), or octave-mcp (OCTAVE grammar) lanes.
- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — a session whose governance artefacts vanish to gitignored paths does not have clean archival. The IA Contract makes archival mechanically verifiable; the tool-boundary defense makes archival violations unconstructible.
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT** — authoritative reference resolution must be identical across providers. Stable committed paths and the cross-repo resolution rule in §1.4.1 guarantee this; opaque tokens and bare URLs do not.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — the fail-fast error in §3.4 conforms; an opaque-blob rejection would itself violate PROD::I4.
- **PROD::I5 READ_ONLY_CONTEXT_QUERY** — `get_context` is exempt from §3 by this invariant. The exemption is explicit, not incidental.
- **PROD::I6 LEGACY_INDEPENDENCE** (interpreted as scope-boundary discipline per North Star §4) — the IA Contract does not define agent identity, dispatch infrastructure, deliberation records, or OCTAVE grammar; those belong to Vault, Workbench, DebateHall, and octave-mcp respectively.

## 5. Verification of this ADR

This ADR is governance specification with no code attached. Verification is review-only:

- **Tier**: TIER_3
- **Facets**: GOVERNANCE, MCP, CI
- **Gate**: CIV + SR per `/review` skill
- **Debate-hall escalation**: discretionary, recommended if reviewers find §1.4 (cross-repo) or §1.5 (routing rules) ambiguous in practice

Enforcement of the IA Contract itself begins on this ADR's merge:

- **By review discipline** until PR-F and PR-G land — any PR introducing an authoritative-style reference into L2/L4 paths without a marker is rejected on §1.2 grounds, citing this ADR.
- **By tool boundary** once PR-F lands — `clock_out` and `octave_write` enforce §3 mechanically.
- **By CI gate** once PR-G lands — review-time backstop scans diffs per §2.

The ADR remains binding in all three regimes; PR-F and PR-G implement the ADR, they do not amend it.

## 6. Supersession of ADR-RFC-ARCH-001

ADR-RFC-ARCH-001 (PR-α, the placement invariant) is **superseded by this ADR**.

Supersession is **substantive** but **non-disruptive**:

- The four placement categories (§1.2) are carried forward **verbatim** from PR-α §2, with the additional layer-mapping refinement noted in §1.2.
- The PR-α invariant statement is carried forward verbatim and quoted in §1.2.
- The explicit `EPHEMERAL` / `NON_AUTHORITATIVE` marker convention from PR-α §2 is carried forward verbatim.
- The verbatim `ho-control-room` SKILL amendment recorded in PR-α §6 is acknowledged as already landed upstream and is not re-amended here. PR-α §6 remains the historical ratified record; this ADR does not republish that verbatim text.
- The `committed_governance` root retains its prior contents; no existing files require move or rename.

The supersession is therefore **expansive**: PR-B preserves PR-α's semantics and extends scope (cross-repo references, query-routing rules, tool fail-fast contract, CI gate spec).

References in flight that cite ADR-RFC-ARCH-001 remain valid; they may be updated to cite ADR-RFC-ARCH-002 §1 at the authors' discretion. There is no requirement to retroactively re-cite.

## 7. Out of scope (do not infer from PR-B)

PR-B does **not** define, decide, or constrain:

- **CI gate implementation.** PR-G. §2 is specification only.
- **MCP-tool fail-fast implementation.** PR-F. §3 is specification only.
- **Decision-record format for RFC #40.** PR-D. §1.5 references `lookup_decision` as the routing target but does not specify the record schema or storage format.
- **Ledger schema v1.4 vs v2.0 resolution.** PR-E. The Mac B#1 raw ledger remains under PR-E pending.
- **Agent definitions, skill definitions, standards documents.** Vault lane. SKILL amendments are surfaced upstream; see PR-α §6 for the historical ratified record.
- **UI, dispatch, payload compiler design.** Workbench lane. Workbench is a consumer of this contract via `get_context` (PROD::I5) at KVAEPH Position 3; it is not a co-author of the contract.
- **Deliberation records or debate-hall artefact format.** DebateHall lane.
- **OCTAVE grammar additions or changes.** octave-mcp lane. This ADR uses OCTAVE atoms by reference (`META.TYPE`, etc.); it does not extend the grammar.
- **Umbrella-vs-peers architecture revisitation.** Settled by debate-hall on 2026-05-16; PE-immutable in PR-B scope.
- **Mac B#1 raw ledger promotion.** Deferred to PR-E per Principal Engineer ruling (carry-forward §"Why this exists").
- **Cross-repo IA contracts in other repositories.** Reciprocity is advisory per §1.4.3.

## 8. Downstream owners and follow-up sequence

| ID | Artefact | Owner | Depends on |
|---|---|---|---|
| PR-α | ADR-RFC-ARCH-001 (placement invariant) | HOLISTIC_ORCHESTRATOR | merged 2026-05-16 via PR #46 |
| **PR-B** | **ADR-RFC-ARCH-002 (this ADR)** | **HOLISTIC_ORCHESTRATOR** | **PR-α merged; convergent L0–L5 ratified** |
| PR-D | ADR for RFC #40 decision-record format | HOLISTIC_ORCHESTRATOR or designated drafter | PR-B §1.5 routing rules |
| PR-E | ADR for ledger schema v1.4 → v2.0 resolution | HOLISTIC_ORCHESTRATOR or designated drafter | PR-B §1.2 (ephemeral_session_state semantics) |
| PR-F | Implementation: MCP-tool fail-fast at `clock_out` / `octave_write` | implementation-lead | PR-B §3 |
| PR-G | Implementation: CI gate scanner | implementation-lead | PR-B §2 |

No follow-up named here is blocked by another at the contract level — PR-D, PR-E, PR-F, PR-G may proceed in parallel once PR-B lands. Sequencing is at the operator's discretion.

## 9. Open questions for the operator

None at drafting time. All three Principal Engineer amendments were folded in verbatim; the convergent L0–L5 architecture was carried forward without re-debate; PR-α's placement categories were carried forward verbatim. If reviewers surface ambiguity in §1.4 (cross-repo resolution) or §1.5 (routing rules), debate-hall escalation is the recommended path.
