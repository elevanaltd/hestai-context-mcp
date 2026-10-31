===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-HC-WEEKEND-DELEGATION-20261031
  STATUS::RATIFIED
  TIER::TACTICAL
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_quotes,window,scope,relay_rule,limits,merge_rules,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T01:31:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-31T01:31:00Z"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:hc-control-room-20260929"
  OPERATOR_RULING::"Shaun Buswell, 2026-10-31, HC control room session, first-party. Grant, verbatim: 'In addition, I am away for the weeknd but you have complete authority to continue work for the next 48 hours, making decision , merging PRS, and other agents will have authority to push PRs, etc'. Answers to the four HC questions (1 relay counts as authority, option b; 2 scope; 3 YAML for prose mode; 4 limits), verbatim: '1. b / 2. OK and I havne't done the ruleset, so you may do that / 3. Yes / 4. OK'. Merge rules, verbatim: 'one merge at a time per repo, the full review gate approved at head, required checks green, --match-head-commit, check main CI afterwards. Order in hestai-context-mcp: #219 first (its code, #218, is already merged as 279b2c8d), then HO-RECORDS' PR-5.'"
  WINDOW::"2026-10-31T01:18Z to 2026-11-02T01:18Z, then this authority lapses without further action"
  SCOPE::"hestai-context-mcp only, plus one setting in hestai-workbench: ruleset 12626210 workflow sha set to 254bed2112717f7c85d49663819be439d9fd2c86. elevana-studio is out of scope: the ES room acts on its own authority or waits for the operator"
  RELAY_RULE::"Option b: during WINDOW, an HC control-room relay that cites this TOKEN counts as operator authorization in hestai-context-mcp for the HO-RECORDS and topic-records lanes to push, open PRs and rework. Merges are done by HC, or by a stream HO under EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025"
  MERGE_RULES::"one merge at a time per repo; full review gate approved at the head SHA; required checks green; gh pr merge --match-head-commit; main CI checked after each merge; merge SHAs reported to HW-PROGRAMME; order #219 then PR-5"
  LIMITS::"no force-push to main; no branch-protection or ruleset change other than ruleset 12626210; no deleting branches that hold unmerged work; nothing posted outside GitHub PRs and issues in these repos; cross-repo contention goes to the control tower; no release or MCP server version bump; GitGuardian incident 39315314 waits for the operator"
  RELATED_DECISIONS::[EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025,HO-GOVERNANCE-AMEND-IN-PLACE-20260926]
  RELATED::"hestai-workbench HW-PROGRAMME-WEEKEND-AUTHORITY-20261031 (hestai-workbench #651) carries the same weekend authority for HW-PROGRAMME; provenance only"
  DECISION::"For 48 hours from 2026-10-31T01:18Z the HC control room may decide and merge in hestai-context-mcp and re-point ruleset 12626210, and an HC relay citing this record authorizes the HO-RECORDS and topic-records lanes."
  BECAUSE::"The operator is away for the weekend and granted this first-party in the HC session; lanes refuse relayed authority by design, so the operator ruled that a relay citing this record counts during the window only."
===END===