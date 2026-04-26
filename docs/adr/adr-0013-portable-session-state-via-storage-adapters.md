# ADR-0013: Portable Session State via Storage Adapters

## Status

ACCEPTED

- **ADR Number**: ADR-0013
- **Title**: Portable Session State via Storage Adapters
- **Type**: ADR
- **Author**: requirements-steward (codex, via control-room session)
- **Created**: 2026-04-25
- **Updated**: 2026-04-26
- **Ratified**: 2026-04-26 (human authority via control-room session)
- **Phase**: D2 design
- **GitHub Issue**: [#13](https://github.com/elevanaltd/hestai-context-mcp/issues/13)
- **Implements**: Portable Session State (PSS) design for hestai-context-mcp
- **Deviates From**: none
- **Supersedes**: none
- **Superseded-By**: none

Alignment verdict: [ALIGNED]. Evidence: hestai-context-mcp North Star defines this service as the Memory and Environment service, with binding requirements for session lifecycle integrity (PROD I1), fail-closed credential safety (PROD I2), provider-agnostic context synthesis (PROD I3), zero-side-effect `get_context` (PROD I5), no mandatory remote runtime dependency (PROD I6), and stdio JSON-RPC as the immutable transport with additional transports negotiable. Reasoning: PSS extends the storage plane only. It does not turn `.hestai/state/` into synced raw state, does not introduce a mandatory remote service, does not alter provider-neutral return semantics, and does not change stdio JSON-RPC transport.

## Context

`.hestai/state/` is per-project mutable state: sessions, context, checklist, and fast-layer working material. It is gitignored and per-machine. This is deliberate. HestAI-MCP commit `70b63d06d11edede2e57f81986f601c4931bb441` moved working state from `.hestai/` to `.hestai/state/` as Tier 3 state, gitignored and symlinked across worktrees. The current multi-machine failure mode is that a fresh machine can clone or open the project and have no `.hestai/state/` at all, so it cannot see accumulated session, context, or checklist memory.

The requirement is not to sync the raw folder. Raw `.hestai/state/` remains Local State. The requirement is to make redacted, derived, portable session memory available through optional carriers so any computer logged into HestAI can restore shared memory without violating the product immutables. This ADR calls the architecture **Portable Session State (PSS)**.

The design inputs converged on Class A: a pluggable storage adapter model. Class T, a transport proxy, was rejected because it would turn context access into a remote runtime dependency and breach PROD I6. Class S, raw sync, was rejected because it would move unclassified local state and risk credential persistence, breaching PROD I2. PSS preserves LocalFilesystem as the default and complete offline path, so all core behavior remains available without remote services (PROD I6).

This ADR stays inside the hestai-context-mcp ownership boundary confirmed by HestAI-MCP commit `9071a2a8c3b76ed61dae8f244b17dbbb8b60705e`. It does not expand into Phase 1.5 integration gaps such as AI synthesis, phase normalization, North Star extraction, or conflict response beyond the state portability surface.

Vocabulary adopted by this ADR:

- **Local State**: the raw `.hestai/state/` folder and local-only mutable files.
- **Portable Memory Artifact**: a redacted, versioned, cloud-safe artifact eligible for optional carriers.
- **Context Projection**: a rebuilt read model produced from Local State plus Portable Memory Artifacts.
- **StorageAdapter**: the storage interface PSS uses for LocalFilesystem and future optional carriers.
- **Publish Portable State**: redaction-gated publication of Portable Memory Artifacts.
- **Restore Portable State**: adapter-backed restoration before a session snapshot is bound.

## Decision

We decide on PSS as the design contract: LocalFilesystem remains the default StorageAdapter, remote-capable carriers are optional, and `.hestai/state/` itself never goes to cloud. Only Portable Memory Artifacts can cross carrier boundaries, and redaction provenance is the publication gate. This preserves PROD I1, PROD I2, PROD I3, PROD I5, PROD I6, and immutable stdio JSON-RPC transport.

### R1: State classification

| Tier | Sync eligibility | Examples | North Star preservation |
|------|------------------|----------|--------------------------|
| `LOCAL_MUTABLE` | Never synced as a folder or raw file set | `.hestai/state/sessions/active/{session_id}/session.json`, `.hestai/state/sessions/archive/*-redacted.jsonl`, `.hestai/state/learnings-index.jsonl`, `.hestai/state/sessions/control-room-ledger.oct.md`, `.hestai/state/context/state/*` | Keeps raw working state local, preserving PROD I2 and PROD I6. |
| `PORTABLE_MEMORY` | Eligible for optional carriers only after redaction and provenance validation | `.hestai/state/portable/outbox/{artifact_id}.json`, abstract carrier path `pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/artifacts/{artifact_id}`, redacted session summaries, extracted decisions, extracted blockers, checklist deltas, tombstones | Shares memory without syncing raw state, preserving PROD I2 and provider-neutral context semantics under PROD I3. |
| `DERIVED_PROJECTION` | Never synced; rebuilt on hydrate or local reads | `.hestai/state/portable/snapshots/{session_id}/context-projection.json`, materialized `.hestai/state/context/PROJECT-CONTEXT.oct.md` when derived from portable memory, fast-layer read models | Makes `get_context` a pure local read and protects PROD I5. |

Classification is mandatory. Unknown state is treated as `LOCAL_MUTABLE` until explicitly classified. That fail-closed default protects PROD I2.

### R2: StorageAdapter protocol contract and carrier capability matrix

`StorageAdapter` is a storage boundary, not a transport change. MCP still runs over stdio JSON-RPC; adapters are invoked by hestai-context-mcp internals during `clock_in`, `clock_out`, and explicit publish or restore actions. `get_context` must not call adapters (PROD I5).

```python
class StorageAdapter(Protocol):
    capabilities: StorageCapabilities

    def list_artifacts(namespace: PortableNamespace, after_id: str | None = None) -> list[ArtifactRef]: ...
    def read_artifact(ref: ArtifactRef) -> PortableMemoryArtifact: ...
    def write_artifact(ref: ArtifactRef, artifact: PortableMemoryArtifact, precondition: WritePrecondition) -> PublishAck: ...
    def write_tombstone(ref: ArtifactRef, tombstone: TombstoneArtifact, precondition: WritePrecondition) -> PublishAck: ...
```

Carrier capability matrix:

| Capability | PSS requirement | LocalFilesystem default | Any future non-local adapter |
|------------|-----------------|--------------------------|------------------------------|
| List consistency | Required for restore correctness | Required, strong local directory listing | Required directly or through a manifest that provides complete ordered visibility |
| Atomic CAS | Required for manifests, tombstones, and compaction records | Required through atomic create/rename and compare semantics | Required through conditional create/update or equivalent |
| Locking | Optional advisory only; correctness cannot depend on locks | Optional | Optional |
| Streaming writes | Optional for Portable Memory Artifacts; adapters must advertise support truthfully | Optional | Optional |
| Conditional writes | Required to prevent overwrite races | Required | Required |
| Encryption | Optional for local adapter, because local disk policy is outside this ADR | Required in transit and at rest for any non-local adapter |

Adapters that cannot satisfy required capabilities are read-only or invalid for PSS publication. This keeps remote storage optional (PROD I6), avoids provider-specific context behavior (PROD I3), and prevents storage races from corrupting lifecycle history (PROD I1).

### R3: Identity tuple

Every Portable Memory Artifact is scoped by this identity tuple:

`project_id + workspace_id + user_id + state_schema_version + carrier_namespace`

- `project_id`: stable project identity, not the current folder name.
- `workspace_id`: checkout, worktree, or clone identity, used to separate concurrent local workspaces.
- `user_id`: the HestAI user whose portable memory is being restored or published.
- `state_schema_version`: the PSS artifact schema version used for compatibility checks.
- `carrier_namespace`: logical namespace for the selected carrier, such as personal, team, staging, or production.

Restore must refuse artifacts whose identity tuple does not match the requested tuple. This prevents silent hydration from forks, renames, worktrees, or personal clones. A mismatch is a structured restore error, not an empty fallback. This preserves PROD I3 by making context synthesis deterministic for the intended identity and PROD I1 by preserving provenance.

### R4: Portable artifact schema, versioning, and migration

Portable Memory Artifacts are versioned records. Each artifact includes: artifact id, artifact kind, identity tuple, schema version, producer version, minimum reader version, created timestamp, monotonic sequence id, parent ids, redaction provenance, classification label, payload hash, and payload.

Migration rules:

- If a reader supports the artifact schema version, it may hydrate it.
- If an artifact is older than the reader, the reader migrates it locally into the current Context Projection during restore. The original artifact is not rewritten during restore.
- If a v2-capable machine reads a v1 artifact, it migrates locally and may publish future artifacts as v2 at `clock_out`.
- If a v1-only machine reads a v2 artifact whose `minimum_reader_version` exceeds its support, restore fails closed with a structured `schema_too_new` error. It must not silently fall back to empty memory and must not publish over the newer stream.
- Unknown optional fields may be ignored only when `minimum_reader_version` allows it.

This protects provider-agnostic context shape (PROD I3) and avoids lifecycle corruption (PROD I1). Fail-closed behavior aligns with credential safety posture under PROD I2.

### R5: Lifecycle binding

PSS binds storage to the existing lifecycle:

1. `clock_in`: Restore Portable State from the configured adapter, then create a named local snapshot bound to `session_id`.
2. `get_context`: Read only the named local snapshot and existing local projection. It performs zero network I/O and zero writes.
3. In-session refreshes: May update cache or outbox metadata, but must not change the snapshot seen by that session.
4. `clock_out`: Redact, archive locally, produce Portable Memory Artifacts, then Publish Portable State through the adapter.

The named snapshot prevents intra-session context drift. If portable memory changes remotely after `clock_in`, the current session does not see it through `get_context`; the next session can restore a newer snapshot. This preserves PROD I5 and keeps context synthesis identical within a session regardless of provider, CLI, or machine (PROD I3). Local archive and session close remain functional even if no remote carrier exists (PROD I1 and PROD I6).

### R6: Redaction provenance metadata

Redaction is the publication gate. A `redaction_success` boolean is insufficient. Every Portable Memory Artifact must carry redaction provenance:

- redaction engine name and version
- ruleset hash
- input artifact hash
- output artifact hash
- timestamp
- classification label
- redacted credential categories, when available

`write_redacted_artifact()` must fail closed without complete provenance metadata. This prevents stale redactor output from being treated as safe after rules change. It directly enforces PROD I2.

### R7: Publish acknowledgement, durable queue, and unpublished status

`clock_out` has two separable outcomes: local lifecycle archive and portable publication. If local archive succeeds but remote publish fails, `clock_out` must report local archive success and portable publish failure or queued status. It must also expose `unpublished_memory_exists: true` until the durable outbound queue is empty.

The durable outbound queue is Local State, for example `.hestai/state/portable/outbox/{artifact_id}.json`. Retry may happen on later `clock_in`, `clock_out`, or explicit Publish Portable State, but never inside `get_context`. A publish acknowledgement records artifact id, carrier namespace, sequence id, durable carrier receipt if any, and final status. This preserves lifecycle integrity without making remote publication mandatory (PROD I1 and PROD I6).

### R8: Tombstone and revocation semantics

PSS is not append-only-only. It is append-first with explicit revocation. A Portable Memory Artifact may be revoked by a tombstone artifact that identifies the target artifact id, reason, timestamp, publisher identity, and redaction provenance if the tombstone is driven by post-hoc redaction failure.

Restore must exclude tombstoned artifacts from Context Projection. Compaction must preserve revocation semantics. If a carrier supports hard delete, deletion may be used after tombstone publication, but hard delete is not the only revocation mechanism. This is required for correction, removal, and right-to-forget paths, and it protects PROD I2 when missed sensitive data is discovered after publication.

### R9: Concurrency model

PSS uses append-first, monotonic IDs, compact-later. It explicitly rejects Last-Write-Wins. LWW risks selecting the least complete artifact and losing concurrent session memory.

Each publish appends a monotonic artifact id and parent references. Restore merges valid artifacts by identity tuple and monotonic order. Duplicate artifact ids are idempotent. Conflicting compactions do not delete source events until their tombstone and parent coverage are validated. Compaction is a separate projection step, not the authoritative event stream.

This preserves lifecycle evidence (PROD I1) and keeps context deterministic across machines (PROD I3).

### R10: Testable invariants

Future implementation must add fixtures for these invariants before behavior is considered complete:

- Filesystem snapshot diff is empty before and after `get_context`.
- The full test suite passes with remote adapters disabled.
- `write_redacted_artifact()` fails closed without redaction provenance metadata.
- The same Portable Memory Artifacts on different machines produce identical context shape, allowing machine-specific absolute paths only in explicitly local fields.
- Hydration failure produces a structured error, not silent empty fallback.

These invariants directly test PROD I5, PROD I6, PROD I2, PROD I3, and PROD I1 respectively.

### R11: Anti-pattern: no custom Git refs

PSS must not use custom Git refs such as `refs/hestai/*` as the storage carrier.

The prohibition is evidence-based. HestAI-MCP commit `9dad66035922363a3d18e154d85e31fedb680f87` added reproducible phantom-substrate evidence:

- `evidence_git_ref_behavior.txt`: "refs/hestai/* exist on remote but are NOT cloned/fetched by default"; "explicit fetch refspec required to fetch refs/hestai/*"; "default push does NOT push refs/hestai/*"; "`--work-tree` checkout updates shared index (status pollution)" unless isolated with `GIT_INDEX_FILE`.
- `evidence_git_index_pollution.txt`: "shared index pollution when context ref tree != working branch tree" and status showed `MM ctx/state.txt` after checkout.
- `evidence_ref_reflog_recovery.txt`: deleting `refs/hestai/main` produced `MISSING`, `RECOVER_SHA: <none>`, and `NO_REFLOG_AVAILABLE`.

Custom refs are not a portability substrate for this service. They are invisible to default clone and fetch, fragile for push, capable of polluting the shared index, and weak for recovery. Using them would repeat a known institutional failure and risk PROD I1 lifecycle evidence, PROD I2 safety, and PROD I6 local-first operability.

### R12: Out of scope for this ADR

The following are explicitly out of scope for this ADR:

- hosting target and region
- auth model
- RemoteHTTP wire format or schema
- first-run UX state taxonomy
- specific adapter implementations beyond LocalFilesystem

These require future ADRs. This ADR defines the PSS architecture boundary, classification, lifecycle, provenance, concurrency, and invariants only.

## Consequences

Positive consequences:

- Multi-machine continuity becomes possible without syncing raw `.hestai/state/`.
- Existing LocalFilesystem behavior remains the default and complete offline mode.
- `get_context` stays pure, local, and deterministic.
- Credential safety is strengthened by provenance rather than weakened by remote storage.
- Future carriers can be added without changing stdio JSON-RPC transport.
- Wrong-memory hydration from forks, clones, and worktrees becomes explicitly detectable.

Negative consequences:

- PSS adds schema, migration, queue, and tombstone concepts that must be implemented carefully.
- Publication can lag behind local archival, so callers must surface unpublished memory status.
- A future non-local adapter must meet strict capability requirements before it can publish.
- Session-bound snapshots require tool contracts to carry or resolve session identity during context reads.

Neutral consequences:

- `.hestai/state/` remains local and gitignored.
- Remote storage is a portability option, not a runtime dependency.
- Compaction becomes a projection concern, not a replacement for append history.

## Alternatives Considered

Class A: Pluggable Storage Adapter. Accepted. It preserves local-first behavior, keeps raw state local, confines remote I/O to lifecycle points, and supports future carriers without changing MCP stdio transport. It best satisfies PROD I1, PROD I2, PROD I3, PROD I5, and PROD I6 together.

Class T: Transport proxy. Rejected. Putting storage or context synthesis behind a mandatory remote transport would make runtime operation depend on remote availability and breach PROD I6. It also risks coupling context behavior to provider or deployment assumptions, undermining PROD I3.

Class S: Raw sync. Rejected. Syncing `.hestai/state/` directly would publish unclassified mutable state and risk credential persistence. It contradicts the deliberate Tier 3 move in commit `70b63d06d11edede2e57f81986f601c4931bb441` and breaches PROD I2.

Custom Git refs. Rejected. The phantom-substrate evidence from commit `9dad66035922363a3d18e154d85e31fedb680f87` proves default clone, fetch, push, checkout, index, and reflog behavior are unsuitable for portable memory.

Last-Write-Wins remote state. Rejected. LWW selects a winner, not a complete memory set. PSS needs append-first events and compact-later projections to preserve concurrent session evidence.

## References

- hestai-context-mcp Product North Star: `.hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR.md`
- hestai-context-mcp Product North Star summary: `.hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md`
- System Standard: `.hestai-sys/SYSTEM-STANDARD.md`
- Current local state evidence: `.hestai/state/sessions/control-room-ledger.oct.md`
- Current LocalFilesystem state convention: `.gitignore`
- Current server transport: `src/hestai_context_mcp/server.py`
- Current lifecycle implementation references: `src/hestai_context_mcp/tools/clock_in.py`, `src/hestai_context_mcp/tools/get_context.py`, `src/hestai_context_mcp/tools/clock_out.py`
- Current RedactionEngine reference: `src/hestai_context_mcp/core/redaction.py`
- HestAI-MCP `70b63d06d11edede2e57f81986f601c4931bb441`: `refactor: move working state from .hestai/ to .hestai/state/ (Tier 3)`
- HestAI-MCP `9071a2a8c3b76ed61dae8f244b17dbbb8b60705e`: `Merge PR #382 hestai-mcp-control-room: docs: sync ecosystem docs and lock hestai-context-mcp Phase 1.5 plan`
- HestAI-MCP `9dad66035922363a3d18e154d85e31fedb680f87`: `Merge PR #48 review-hestai-folder: docs: HestAI context architecture debates and synthesis`

**END OF ADR-0013**
