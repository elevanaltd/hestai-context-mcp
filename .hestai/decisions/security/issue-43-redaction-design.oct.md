===REDACTION_DESIGN_REVIEW===
META:
  TYPE::SECURITY_DESIGN_REVIEW
  VERSION::"1.0"
  ISSUE::"elevanaltd/hestai-context-mcp#23"
  AUTHOR_ROLE::SECURITY_SPECIALIST
  COGNITION::ETHOS
  ARCHETYPES::[
    ARGUS,
    THEMIS,
    APOLLO
  ]
  PERMIT_SID::"035a4c9d-6ba3-484f-9daf-9acdeed90ad0"
  SESSION_ID::"646ddcc6-7ba4-48f5-b55f-fa16e26ca8bb"
  WORKTREE::dispatch-rd12-rd13-a6
  PROJECT_PHASE::B1_FOUNDATION_COMPLETE
  CREATED::"2026-05-05"
  SCOPE::DESIGN_ONLY
  IMPLEMENTATION_FORBIDDEN::true
  NAMESPACE::PROD
  PURPOSE::"Adversarial review of issue#23 proposed redaction design vs. current engine; gap-list and PROD::A4 cadence recommendation."
§0::SECURITY_VERDICT
  HEADER::"[SECURITY_VERDICT]"
  OVERALL::HIGH
  RATIONALE::"Current engine SATISFIES PROD::I2 fail-closed contract for the in-scope publish path, but PROD::A4 80% pattern-coverage claim is UNSUBSTANTIATED. Five regex families cover Claude-era surface only; multi-provider future (Codex, Gemini, Goose) and modern token shapes (GitHub PAT, Slack, GCP, Azure, generic JWT) are not represented. Proposed Phase-1 design in issue#23 is ALREADY IMPLEMENTED; treating issue#23 as new design work is a category error."
  DISPOSITION::CONDITIONAL_RATIFICATION_BLOCKED_PENDING_PATTERN_SURFACE_ENUMERATION
§1::CURRENT_ENGINE_SUMMARY
  HEADER::"[EVIDENCE]"
  LOCATION_FOUND::"src/hestai_context_mcp/core/redaction.py"
  LOCATION_BRIEFED::"src/hestai_context_mcp/redaction/"
  LOCATION_DELTA::"FINDING_F0::Brief and reality disagree on module path. Current code is a single module core/redaction.py, NOT a redaction/ package. Any future Phase-2 work that grows pattern surface or adds adapter-specific normalisers SHOULD promote to a package; design must specify migration path."
  ENGINE_NAME::hestai-context-mcp.redaction
  ENGINE_VERSION::"1"
  PROVENANCE_STAMP::"REDACTION_ENGINE_NAME⊕REDACTION_ENGINE_VERSION embedded in PortableMemoryArtifact.RedactionProvenance per ADR-0013 R6 (RISK_004 + G6 + A4)"
  PATTERNS_PRESENT::[
    "ai_api_key::regex(sk-[a-zA-Z0-9]{20,}) → [REDACTED_API_KEY]",
    "aws_key::regex((AKIA|ASIA)[0-9A-Z]{16}) → [REDACTED_AWS_KEY]",
    "private_key::regex(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----, DOTALL) → [REDACTED_PRIVATE_KEY]",
    "bearer_token::regex(Bearer [a-zA-Z0-9\\-\\._~\\+\\/]+=*) → Bearer [REDACTED_BEARER]",
    "db_password::regex((\\w+://[^:]+:)(.+)(@)(?=[^@]*$)) → \\1[REDACTED_PASSWORD]\\3"
  ]
  PUBLIC_API::[
    "RedactionEngine.redact(text)→RedactionResult{redacted_text,redaction_count,redacted_types}",
    "RedactionEngine.redact_content(text)→str (classmethod, backward-compat)",
    "RedactionEngine.copy_and_redact(src,dst) (classmethod, fail-closed: dst.unlink on exception)"
  ]
  FAIL_CLOSED_CONTRACT::"copy_and_redact catches Exception, deletes partial dst, re-raises. clock_out publish path (PR#17 RISK_010) blocks archive on redaction failure. Verified by tests/integration/test_clock_out_rework_redaction_failclose.py."
  STREAM_PROCESSING::"Line-by-line iteration over src_file. PRIVATE KEY pattern requires DOTALL across lines — line-by-line streaming CANNOT match PEM blocks; only redact_content over a fully buffered string, or a multi-line accumulator, can. Single-line streaming therefore SILENTLY MISSES multi-line PEM blocks. CRITICAL FINDING — see §3 G1."
  COVERAGE_BASELINE::"PROJECT-CONTEXT 91.20% repo coverage; tests/core/test_redaction.py + tests/unit/core/test_redaction.py + tests/integration/test_clock_out_rework_redaction_failclose.py exist."
§2::PROPOSED_DESIGN_FROM_ISSUE_23
  HEADER::"[EVIDENCE]"
  SOURCE::"GitHub issue elevanaltd/hestai-context-mcp#23"
  PROPOSED_MODULE::"tools/shared/security.py with RedactionEngine class"
  PROPOSED_PHASE_1_PATTERNS::[
    "AI Provider Keys::sk-[a-zA-Z0-9]{20,}",
    "AWS Keys::AKIA*, ASIA*",
    "Private Keys::PEM blocks",
    "Bearer Tokens::Bearer [token]",
    "DB Passwords::URI password component"
  ]
  PROPOSED_FAILURE_MODE::"Fail CLOSED — don't archive if redaction fails"
  PROPOSED_PROCESSING_MODEL::"Stream-based (not in-memory)"
  PROPOSED_INTEGRATION::"Replace shutil.copy at clockout.py L214 with RedactionEngine.copy_and_redact"
  ACCEPTANCE_CRITERIA::[
    "All Phase-1 patterns detected and redacted",
    "No false positives on common identifiers (session_id, project_id, ...)",
    "Stream-based processing (handles large archives)",
    "Fail-closed behavior (no archive on redaction failure)",
    "All CI checks pass"
  ]
  PROPOSED_VS_CURRENT::"NEAR_IDENTITY: the five Phase-1 patterns and fail-closed contract proposed in issue#23 are LIVE TODAY in core/redaction.py. The proposal does not advance the engine; it documents what already shipped under PR#17 RISK_010."
§3::ADVERSARIAL_GAP_LIST
  HEADER::"[CONSTRAINT_CATALOG]"
  REVIEW_LENS::"ARGUS exhaustive enumeration ⊕ THEMIS compliance check ⊕ APOLLO pattern-family recognition"
  SEVERITY_SCALE::[
    CRITICAL,
    HIGH,
    MEDIUM,
    LOW,
    INFO
  ]
  GAP_G1::"\n"
  NAME::"Stream-mode multi-line PEM block evasion"
  SEVERITY::CRITICAL
  LOCATION::"core/redaction.py copy_and_redact() lines 180-187"
  EVIDENCE::"Stream loop reads file line-by-line; calls cls.redact_content(line) per line. private_key pattern uses DOTALL and matches across newlines. A single line never spans BEGIN→END, so a multi-line PEM block in a transcript is NEVER redacted by the streaming path. The non-streaming engine.redact(text) path DOES match because it sees the full buffer."
  EXPLOITABILITY::"High — pasting an actual private key into a Claude session is the canonical leak shape. Streaming archive path will persist it verbatim while reporting redacted_count=0 and STILL succeed (fail-closed only triggers on exception, not on missed match)."
  PROD_IMMUTABLE_VIOLATED::"PROD::I2 CREDENTIAL_SAFETY (\"zero credentials persist in archives\")"
  BLOCKING::true
  REMEDIATION_DIRECTION::"Either (a) buffer with bounded look-back so PEM begin/end markers can be paired across lines, or (b) detect BEGIN markers and switch to block-accumulation mode until END marker, or (c) accept memory cost and use full-buffer redact() in the publish path. Decision must be recorded as ADR-tier."
  GAP_G2::"\n"
  NAME::"GitHub Personal Access Tokens not covered"
  SEVERITY::CRITICAL
  EVIDENCE::"PATTERNS dict has no entry for ghp_*, gho_*, ghu_*, ghs_*, ghr_* (40-char alphanumeric tail), nor for fine-grained github_pat_* tokens. GitHub explicitly recommends these prefixes for secret scanning since 2021."
  PROD_IMMUTABLE_VIOLATED::"PROD::I2; PROD::A4 (coverage)"
  BLOCKING::true
  NOTES::"Claude transcripts and tool outputs in this repo's primary use-case routinely include git command output that may surface PATs (e.g., 'gh auth token' leakage)."
  GAP_G3::"\n"
  NAME::"Slack tokens (xox[bopars]-...) not covered"
  SEVERITY::HIGH
  EVIDENCE::"No xox[bopars]- pattern entry."
  PROD_IMMUTABLE_VIOLATED::"PROD::A4"
  GAP_G4::"\n"
  NAME::"GCP service-account keys / API keys not covered"
  SEVERITY::HIGH
  EVIDENCE::"No regex for AIza[0-9A-Za-z\\-_]{35} (GCP API key) nor for the JSON service-account key shape (private_key_id + private_key field). PEM block catches the embedded private_key string only when full-buffered; but the JSON envelope's other identifiers (private_key_id, client_email) leak independently."
  PROD_IMMUTABLE_VIOLATED::"PROD::A4"
  GAP_G5::"\n"
  NAME::"Azure AD / SAS tokens / connection strings not covered"
  SEVERITY::HIGH
  EVIDENCE::"No pattern for Shared Access Signature (sig=, se=, sp=) nor Azure SQL connection-string pwd= form (db_password regex requires URI scheme://user:pass@; ADO-style 'Server=...;Password=X;' is missed)."
  PROD_IMMUTABLE_VIOLATED::"PROD::A4"
  GAP_G6::"\n"
  NAME::"Generic JWT tokens not covered"
  SEVERITY::HIGH
  EVIDENCE::"No pattern for eyJ[A-Za-z0-9_\\-]+\\.eyJ[A-Za-z0-9_\\-]+\\.[A-Za-z0-9_\\-]+. Bearer regex catches them only when prefixed by literal 'Bearer '; raw JWT in JSON payload, headers, log lines, or curl examples is missed."
  PROD_IMMUTABLE_VIOLATED::"PROD::A4"
  GAP_G7::"\n"
  NAME::"Anthropic / OpenAI key prefix drift"
  SEVERITY::HIGH
  EVIDENCE::"sk-[a-zA-Z0-9]{20,} captures sk-... but Anthropic uses sk-ant-* and OpenAI introduced sk-proj-* / sk-svcacct-* shapes with longer base64 bodies including hyphens and underscores. Current regex MAY capture by accident (alphanumeric tail) but boundaries (no hyphen/underscore in [a-zA-Z0-9]) cause early-termination — capturing only the prefix and leaving the entropy tail in cleartext for some shapes."
  PROD_IMMUTABLE_VIOLATED::"PROD::I2 (partial leak); PROD::A4"
  NOTES::"Adversarial test must verify the FULL token, not just the prefix, is replaced."
  GAP_G8::"\n"
  NAME::"Bearer regex over-greed and trailing-char leakage"
  SEVERITY::MEDIUM
  EVIDENCE::"Bearer [a-zA-Z0-9\\-\\._~\\+\\/]+=* matches greedily across non-whitespace; in JSON payloads where the bearer is followed by '\",' the regex stops at the quote — correct. But in YAML/log contexts where the token is wrapped or tokenised across lines, partial token may persist."
  GAP_G9::"\n"
  NAME::".env-style assignment leakage"
  SEVERITY::HIGH
  EVIDENCE::"Issue#23 explicitly cites '.env values' as a foot-gun. No pattern for KEY=VALUE shapes where KEY matches a known secret-naming convention (e.g., .*(SECRET|TOKEN|KEY|PASSWORD|PASSWD|API_KEY|ACCESS_KEY)=...). High false-positive risk; requires careful boundary anchoring (line-start, quote-aware)."
  PROD_IMMUTABLE_VIOLATED::"PROD::I2 (direct user concern); PROD::A4"
  GAP_G10::"\n"
  NAME::"High-entropy fallback absent"
  SEVERITY::MEDIUM
  EVIDENCE::"No entropy-based catch-all (e.g., Shannon entropy >4.5 over 32+ char base64-like runs). The 80% claim cannot be defended for unknown / future provider tokens without a generic fallback."
  PROD_IMMUTABLE_VIOLATED::"PROD::A4"
  NOTES::"Entropy fallback comes with false-positive cost; must be tuned with allow-list (e.g., known UUIDs, known hash prefixes in commit SHAs)."
  GAP_G11::"\n"
  NAME::"Identifier false-positive policy untested"
  SEVERITY::MEDIUM
  EVIDENCE::"Issue#23 acceptance criterion 'No false positives on common identifiers (session_id, project_id, etc.)' is not validated by an explicit allow-list test corpus. UUIDs (8-4-4-4-12 hex) are safe under current patterns but session IDs that happen to start with a redaction-shaped prefix (e.g., 'sk-' as part of an opaque ID) would be over-redacted."
  GAP_G12::"\n"
  NAME::"Provenance does not record per-pattern hits"
  SEVERITY::LOW
  EVIDENCE::"RedactionResult exposes redaction_count + redacted_types but the published RedactionProvenance schema (out of scope of this file) should capture per-pattern hit-count for forensic auditability. A future leak investigation needs to know WHICH pattern fired, not just total."
  PROD_IMMUTABLE_VIOLATED::"PROD::I4 (STRUCTURED_RETURN_SHAPES — partial)"
  GAP_G13::"\n"
  NAME::"Provider-specific transcript shape coupling"
  SEVERITY::MEDIUM
  EVIDENCE::"PROJECT-CONTEXT §4 KNOWN_GAPS confirms only Claude transcript adapter shipped. Patterns were tuned against Claude transcript shape. Codex/Gemini/Goose adapters (deferred) will introduce different containerisations (e.g., tool-call JSON envelopes, base64-encoded image attachments, function-call argument blobs) that the regex layer has never been adversarially tested against."
  PROD_IMMUTABLE_VIOLATED::"PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT) and PROD::A4 cadence trigger"
  NOTES::"This gap is the single strongest argument for TRIGGER_NOW under §4."
  GAP_G14::"\n"
  NAME::"Engine-version bump policy not documented for partial-pattern additions"
  SEVERITY::LOW
  EVIDENCE::"REDACTION_ENGINE_VERSION='1' is a single integer. Adding patterns SHOULD bump version so downstream readers can identify pre-bump artifacts as 'older redactor output'. Issue#23 design says nothing about this lifecycle."
  PROD_IMMUTABLE_VIOLATED::"PROD::I2 (provenance trust); PROD::I4"
  GAP_G15::"\n"
  NAME::"copy_and_redact symlink / TOCTOU surface"
  SEVERITY::MEDIUM
  EVIDENCE::"src.exists() → open(src) is a TOCTOU window. If src is a symlink swapped between check and open, the engine could read attacker-pointed content. Low realistic exploitability for this single-user MCP server but worth noting under defense-in-depth."
§4::PROD_A4_CADENCE_RECOMMENDATION
  HEADER::"[CONSTRAINT_CATALOG]"
  RECOMMENDATION::TRIGGER_NOW
  CONFIDENCE::HIGH
  REASONING::[
    R1::"PROD::A4 cadence-trigger conditions are 'each minor release OR on new provider adapter'. PR#17 (2026-04-29) shipped a minor release of the redaction publish path (engine_version=1, RedactionProvenance contract); the adversarial review for THAT release was not separately conducted — the implementation review folded into the B1 ratification gate but without the explicit pattern-coverage adversarial enumeration A4 demands.",
    R2::"Codex/Gemini/Goose adapters are tracked as deferred (PROJECT-CONTEXT §4 KNOWN_GAPS / issue#15). The first such adapter to land WILL re-trigger A4 by definition. Better to enumerate the gap surface NOW than to compound design debt at adapter-merge time, where the temptation to ship-then-review is highest.",
    R3::"This review enumerated 15 named gaps, 2 CRITICAL (G1 stream-mode PEM evasion, G2 GitHub PAT) and 6 HIGH. CRITICAL gaps directly violate PROD::I2 fail-closed semantic intent (zero credentials persist) even if the technical fail-closed-on-exception contract is intact. The 80% coverage claim cannot be defended without remediating at minimum the CRITICAL gaps.",
    R4::"Issue#23 itself triggers A4 by topic (PROD::TRIGGERS §8: 'credential or redaction or security = I2 safety critical → load full North Star'). That trigger is satisfied, and the corresponding action is full adversarial review — i.e., this document is the cadence event."
  ]
  COUNTERARGUMENTS_CONSIDERED::[
    C1::"Defer to next minor release: REJECTED. Next minor release is unscheduled; deferring creates an unbounded window during which the CRITICAL gap G1 (stream-mode PEM evasion) is exploitable.",
    C2::"Defer to first new-adapter merge: REJECTED. Same window-of-exposure problem; also concentrates risk at adapter-merge time when reviewer attention is divided.",
    C3::"This review IS the cadence event, no further action needed: PARTIALLY ACCEPTED. The review IS the cadence event for ENUMERATION; remediation of CRITICAL gaps is a separate implementation engagement that THIS document explicitly does NOT begin (DESIGN_ONLY scope)."
  ]
  RATIFICATION_GATE_DIRECTIVE::"HO blocks implementation pending design ratification per dispatch brief. Recommend HO ratify THIS adversarial-review document AND open a separate implementation issue (or scope this onto issue#23) for CRITICAL/HIGH gap remediation, sequenced ahead of any new-provider-adapter merge."
  IMPLEMENTATION_GATING_FOR_REMEDIATION::[
    G_GATE_1::"CRITICAL gaps (G1, G2) MUST be remediated before any new provider adapter (Codex/Gemini/Goose) is permitted to merge.",
    G_GATE_2::"HIGH gaps (G3, G4, G5, G6, G7, G9) SHOULD be remediated in the same minor release that addresses CRITICAL gaps; engine_version MUST bump.",
    G_GATE_3::"MEDIUM/LOW gaps tracked as backlog; revisit at next A4 cadence event."
  ]
§5::NON_IMPLEMENTATION_DECLARATION
  HEADER::"[REMEDIATION]"
  SCOPE_REAFFIRMATION::DESIGN_ONLY
  WHAT_THIS_DOCUMENT_IS::"Adversarial review of the redaction engine and the proposed design in issue#23, with a gap list, severity ratings, and an explicit PROD::A4 cadence recommendation."
  WHAT_THIS_DOCUMENT_IS_NOT::[
    "Code change",
    "Test modification",
    "Pattern addition or removal",
    "Engine version bump",
    "Provenance schema mutation",
    "Adapter implementation",
    "CI configuration change"
  ]
  PRODUCTION_FILES_MODIFIED::NONE
  TESTS_MODIFIED::NONE
  CODE_COMMITS::NONE
  HO_RATIFICATION_REQUIRED_BEFORE_IMPLEMENTATION::true
  ESCALATION::"Final security decisions → Critical Engineer (per agent §2 OPERATIONAL_BEHAVIOR INTEGRATION ESCALATION). Ratification authority → HO."
§6::REFERENCES
  REFS::[
    SRC::"src/hestai_context_mcp/core/redaction.py",
    TESTS::[
      "tests/core/test_redaction.py",
      "tests/unit/core/test_redaction.py",
      "tests/integration/test_clock_out_rework_redaction_failclose.py"
    ],
    GITHUB_ISSUE::"elevanaltd/hestai-context-mcp#23",
    PRIOR_FAILED_PR::"elevanaltd/hestai-mcp-server#162",
    LANDED_PR::"elevanaltd/hestai-context-mcp#17 (ADR-0013 B1, RISK_010 fail-closed publish path, 2026-04-29)",
    DEFERRED_ADAPTERS_TRACKER::"elevanaltd/hestai-context-mcp#15",
    NORTH_STAR::".hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md",
    PROJECT_CONTEXT::".hestai/state/context/PROJECT-CONTEXT.oct.md",
    PROD_IMMUTABLES_CITED::[
      I2,
      I3,
      I4
    ],
    PROD_ASSUMPTIONS_CITED::[A4]
  ]
===END===
