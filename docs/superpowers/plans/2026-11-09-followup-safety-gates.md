# NovelGraph Safety Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task; TDD RED→GREEN, scoped review, full regression before claiming completion.

**Goal:** Prevent misleading asset totals and reject demonstrable draft inconsistencies before manuscript approval, without bypassing trusted approvals.

**Architecture:** Keep SQLite approved events as the source of truth. Mark combined cash/liquid totals as unresolved unless the liquid asset is explicitly validated as separate. Introduce a read-only draft-gate which checks extracted draft candidates against current official state and blocks only deterministic contradictions. Do not infer semantic certainty from syntactically valid JSON.

**Tech Stack:** Existing Python 3 stdlib, sqlite3, Decimal, unittest, Graphify unchanged.

**Spec:** docs/superpowers/specs/2026-11-09-novelgraph-current-state-design.md

## Global Constraints
- Never persist private story excerpts in git. Use synthetic fixtures only.
- Source and approval integrity must remain mandatory for official state updates.
- Do not autonomously approve facts solely on an LLM's confidence.
- No new dependencies, services, or databases. Never touch /shared/NovelGraph main.
- Draft conflict checking is partial by design; successful preflight is not proof of semantic validity.

## Review Focus
- Cash and liquid amounts in the same currency may represent the same money: cannot output a falsely exact total.
- Distinct confirmed non-cash liquid assets should still be counted once.
- Draft checks must not write official DB or mutate the candidate ledger.
- A future planned transfer must not automatically update current holdings.
- Unsupported/unclear cases require review, not false pass.

### Task 1: Ambiguous liquid asset totals fail closed
**Files:** Modify novelgraph/world_state.py, novelgraph/state_query.py, tests/test_state_query.py, tests/test_current_state.py.
**Interfaces:** `state_set` with category `liquid` may include `separate_from_cash: true` only when proven by source. Existing facts without marker remain valid but ambiguous if cash coexists in the same currency. `query_state(... assets/net_assets)` reports `ambiguous_cash_liquid_currencies` and excludes ambiguous currency from numeric totals.
- [ ] Write failing tests: same cash value duplicated as liquid → no USD total and ambiguity flag; explicitly separate non-cash liquid → total includes both; illegal marker on stock rejected.
- [ ] Run tests, watch expected assertions fail.
- [ ] Minimal implementation: payload validation/replay attribute and fail-closed total aggregation.
- [ ] Run targeted tests and full regression.
- [ ] Review changed source, stage allowed files and commit.

### Task 2: Read-only draft conflict gate
**Files:** Create novelgraph/draft_gate.py; modify novelgraph/__main__.py, tests/test_candidate_preflight.py; document CLI in docs/02-architecture.md.
**Interfaces:** `draft-gate --source <draft.txt> --input <candidates.json> --as-of-episode N`. Consumes original preflight candidates and approved snapshot at episode N; returns JSON with status `REJECTED` on deterministic contradiction, else `NEEDS_REVIEW`. `blocking: true` always until separate human workflow finalizes. No candidate import or state mutations.
- [ ] RED test: impossible cash payment and backward current time → REJECTED, no DB changes; valid state change → NEEDS_REVIEW.
- [ ] Minimal implementation reusing existing input validation, payload validation and approved world-state reader.
- [ ] Verify read-only DB byte invariance, source hash, and no draft quotes in output.
- [ ] Run targeted tests and full regression.
- [ ] Review changed source, stage allowed files and commit.

### Task 3: Review and remaining-scope report
**Files:** New docs/36-safety-gates-2026-11-09.md, update README.md only if needed.
- [ ] Run all existing tests plus new tests, inspect git diff and sensitive paths.
- [ ] Run independent Moon review process if available; clearly distinguish tooling review from independent AI.
- [ ] Report remaining P1: safe automatic official approval of source-extracted claims and external writer handoff must be separately validated, not assumed done.
