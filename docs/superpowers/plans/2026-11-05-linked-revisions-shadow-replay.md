# [2/N] Linked revision intake & shadow replay implementation plan

**Goal:** 20 corrected model-proposed claims are imported with immutable old→new provenance, without competing approvals; independently replay real 3–5 and 10–11 episode semantics in private shadow only.
**Stack:** Moon MCP, stdlib Python sqlite3, existing novelgraph CLI, unittest, GitHub PR.
**Spec:** docs/35-linked-revisions-and-shadow-replay-2026-11-05.md

## Task 1 — TDD lineage-based import
- [x] FAIL tests synthetic: old+new registration, repeated identical mapping=0 new, cross-work/episode/different sha rejected, partial batch rollback, forged old/unknown old rejected, old human approval blocked, unrelated works unaffected.
- [x] Add CLI `import-revisions --source --input --mapping` with private-only JSON mapping `revisions` list, same-work, same-episode matching IDs and set equality.
- [x] Implement atomic candidate+lineage record, no schema change to existing candidates, exactly one replacement per old/new; subsequent revision chains allowed, histories immutable.
- [x] GREEN targeted tests.

## Task 2 — workflow visibility
- [x] FAIL test: raw proposed includes superseded history; active proposed excludes old; model_review summarizes only active proposals.
- [x] Implement `revision_summary` counts, retain old existing `candidate_counts`; no phantom review completion.
- [x] GREEN targeted tests and docs contract.

## Task 3 — actual private pilot intake
- [x] Source SHA+candidate evidence preflight 20 across 7 chapters; independently compute canonical 20 old/new pairs and exact list.
- [x] create-only online backup official DB and integrity check.
- [x] import-revisions 1 chapter at a time; repeated same import returns duplicates; original 118 immutable, new 20 proposed, old 20 approval blocked, official approved 0/apply 0.
- [x] Record total 138 historical, 118 active proposals, 20 superseded, active model review 81 supports/17 needs_review/20 unassessed; revise figures if observed evidence differs.

## Task 4 — private shadow real manuscript replay
- [x] Backup/restore to separate private DB and replay only validated 3+5 contract_signed/real cash_payment/equity_transfer. Source 3 prior signed; 5 retroactive effective4 payment+transfer. Unknown trust opening cash stays null.
- [x] For 10–11, register and shadow-review qualified amount observations, mark Erie settlement requested without cash receipt. Confirm 55만 이상, 약 38만, total assets null and no exact shadow cash mutation.
- [x] Compare as-of episode 3,4,5,10,11 and repeat apply idempotency; log evidence reference without sharing manuscript.

## Task 5 — regression, review, PR
- [x] Full tests, SHA/integrity/foreign key checks, private data excluded from Git.
- [ ] Reviewer note (self review if no independent), GitHub CI, PR merge and Moon clean sync.
