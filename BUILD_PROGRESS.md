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
Current branch: `codex/layers6-11-integration`. Layers 6–11 implemented and pushed as draft
PRs #12–17, stacked on documentation PR #11. Main remains unchanged. Draft PR9/10 research
fixes have also been cherry-picked into this integration branch. Final integration edits
and checklist/report are in progress; preserve the working tree.

Latest full suite: 167 passed. Subsequent report-writing regression passed separately;
Ruff and mypy (30 source files) clean. Dashboard: six model tests, real Edge mobile setup
test, production build and local Firestore emulator authorization/write-denial checks passed.

Actual fixed-baseline three-pair walk-forward command is running sequentially. The first
attempt computed EURUSD but failed when serializing AnalysisConfig into its report; this
was fixed and regression-tested. No result from that failed run is counted. Current process
is the rerun (exec session 18157); preserve it and inspect reports/backtest for completed
walk-forward artifacts. Memory is limited on this PC, so do not start parallel research.
Final holdout stays untouched; costs/H4 limitations still prevent formal validation.

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

Layer 9 checkpoint: read-only mobile dashboard implemented with Firebase Auth, precomputed all-time cards, paginated decision history, rejected/no-trade evidence, subset filters/performance, equity observations, reserve FY grouping and safe CSV exports. Six model tests and one real Edge mobile setup test passed; production build passed. Dependencies audited with zero vulnerabilities. External Firebase auth/rules/Pages not configured or claimed verified. Next: Layer 10 durable paper runtime and failure/soak tooling.

Layer 10 checkpoint: durable quote-driven paper broker and shared analysis/risk/context/execution runtime implemented, with duplicate process/decision guards, restart recovery, simulated exit/reserve replay, halt latch, heartbeat/watchdog, independent notifications, backups and Windows operation notes. Full suite 142 passed before one additional notification test; focused paper suite now 10 passed. Ruff/mypy passed before latest small additions. Actual elapsed live-data soak NOT_RUN; paper disabled pending starting balance/rollover/MT5. Continue final verification/commit then Layer 11 evidence-based research/promotion gates.
Layer 10 validation finalized: 143 tests passed; 10 focused paper tests passed after feed-heartbeat tightening; Ruff/mypy clean and verify-paper passed without MT5. Active next: Layer 11.

Layer 11 checkpoint: full-state diagnosis and immutable experiment registry implemented, with explicit pre-registered criteria and historical/recent/walk-forward/OOS/shadow/paper evidence gates. Source/report hashes, UTC boundaries, holdout separation, costs/H4 and genuine elapsed-duration limits checked; ready means operator review only, never automatic config mutation. Ten focused intelligence tests passed. Final suite running; next integrate draft Layer 4 holdout/performance fixes into a review-only integration branch and finish final review/limitations report.
Layer 11 validation: 153 pytest tests passed; Ruff clean; mypy clean (30 files); verify-intelligence passed. No real evidence promoted.

Integration review: cherry-picked all draft PR9/10 commits, preserved new commands, fixed pre-break-even historical ATR trailing with regression test, linked full decision provenance to paper fills, added optional admin-console remote PAPER halt latch (disabled; dashboard writes remain forbidden), and ran local Firestore emulator security checks successfully. Actual fixed-baseline walk-forward research running for all three pairs; final holdout stays untouched. Development-only Firebase CLI audit has five moderate transitive advisories; browser production audit zero. Continue final tests/reports and preserve the active research process.
