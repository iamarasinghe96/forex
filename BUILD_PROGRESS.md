# Build progress and resumption

User authorization: continue building through Layer 11 without routine interruptions;
leave credential/manual setup placeholders disabled and record the final operator checklist.
Do not merge semantic/architecture changes or place real orders. Existing guardrails in
PROJECT_CONTEXT.md remain authoritative. Do not fabricate costs, broker checks or soak evidence.

## Completed in this work session
- All three Dukascopy pairs imported/verified with original hashes and no data committed.
- Layer 4 pre-holdout research completed using draft PRs #9/#10. Gross expectancy R:
  EURUSD -0.06453886285315559; GBPUSD -0.07469902592687842; USDJPY 0.001297812487040083.
- Final holdout begins 2025-09-28T16:00:00Z; parameters remain UNVALIDATED.
- PR #9: CLI holdout correction. PR #10: exact replay performance. Neither merged.
- PR #11: requirements/guardrails reconciliation, not merged.

## Active
Layer 6 implemented on codex/layer6-context, based on documentation branch. 112 tests passed; Ruff/mypy clean; verify-context passed offline. Providers remain disabled. Next: Layer 7 execution/reconciliation.
Implement constrained JSON review, provider abstraction/failover, persistent response cache,
cost/attempt ledger and offline verification. Then continue Layers 7–11 and deployment tools.
Each layer needs independent tests, Ruff/mypy, a runnable verification command, docs and draft PR.

## Remaining manual/external evidence
Track details in OPERATOR_SETUP.md as implementation progresses. No actual provider credentials,
Firestore/Auth/Vercel setup, MT5 execution verification or VPS soak has been completed here.

## Continuation
A persistent Codex goal is active. This session exposes no automation scheduling tool.
No automatic hourly-reset retry has been configured or verified; usage reset timing is not known.
Do not launch concurrent writers or claim that scheduling exists. Resume from this file and GitHub
branches/PRs, check working-tree changes first, and preserve all uncommitted work.

Layer 7 checkpoint: implemented offline-verified execution service and guarded demo-only MT5
transport on codex/layer7-execution. 126 pytest tests passed; Ruff/mypy clean; verify-execution
passed with no broker calls. Includes restart-safe reservations, ambiguity/reconciliation,
fresh-risk rechecks, review identity/ceiling binding, runtime constraints, filling modes,
monotonic stop changes, bot-ticket closes and non-clearing equity observations. SQLite handles
are now closed explicitly on Windows. External broker verification remains pending.
Next: Layer 8 full decision journal/attribution, tax evidence and asynchronous Firestore mirror.

Layer 8 checkpoint: transactional full-state journal, reserve ledger, evidence attribution, CSV export and persistent asynchronous Firestore outbox implemented. Optional Firebase SDK installed; cloud credentials/rules deployment and external verification remain pending. Continue Layer 9 read-only dashboard after tests/commit.
Validation: 133 pytest tests passed; Ruff clean; mypy clean (25 source files). Layer 8 ready for draft review. Active next work: Layer 9.
