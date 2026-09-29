# Build progress and resumption

## Current status: development implementation through Layer 11 complete

Updated 30 September 2026. User-authorized local implementation and verification are complete.
Credential-dependent integrations remain disabled, manual setup is documented, and actual
broker/cloud/VPS verification and elapsed paper soak remain NOT_RUN. No real-money orders,
parameter promotion, deployment or merge has been performed.

Current branch: `codex/layers6-11-integration`.
Combined draft review: https://github.com/iamarasinghe96/forex/pull/18
Main remains `6b0273d8ccc84143ffeb0495adcf9a19f0021d8b`.
The runtime/dashboard source is commit `89e0cbc84bc1cb5445c1ae7976c7fc2d39e40667`;
`bbd3f9972e9968b93520ed3f40e9ecf11b907c6e` adds the local cloud adapter verification script.
Later commits close out documentation and completed research evidence.

## Authorization and review boundary

Continue from the existing repository, not from a fresh build. PROJECT_CONTEXT.md and
later operator guardrails govern the original brief. Local commands, tests, branches,
commits, pushes and draft PRs are authorized. Do not merge semantic/risk/interface/
validation/execution/promotion/architecture changes without operator review. Do not commit
historical market data, SQLite databases or secrets. Keep external setup placeholders
explicit and disabled; do not fabricate realistic costs, broker checks or soak duration.

## Implemented

- Layer 6: constrained JSON context review, provider failover/cache, risk ceilings and costs.
- Layer 7: durable order identities, fresh risk checks, ambiguity/reconciliation, demo-only
  MT5 transport, monotonic stop protection and persistent risk latches.
- Layer 8: full-state SQLite journal, decision provenance, attribution, reserve ledger,
  exports, persistent cloud outbox and aggregate divergence repair.
- Layer 9: authenticated read-only mobile dashboard, history/rejections, scoped performance,
  reserve evidence and exports; client writes denied. Remote PAPER halt is separately
  administered and cannot remotely clear a local halt latch.
- Layer 10: durable paper broker/runtime, restart recovery, duplicate guards, quote marks,
  heartbeat/watchdog, notifications, backups, Windows operations and actual-interval soak reports.
- Layer 11: all-state diagnosis, immutable hypotheses, pre-registered criteria, hashed
  evidence and historical/recent/walk-forward/OOS/shadow/paper gates. Promotion requires
  operator review and never automatically changes production parameters.

Draft PRs #12â€“17 preserve the individual layer stack on requirements PR #11. PR #18 also
includes the research corrections from #9/#10. It is an alternative combined review path;
do not blindly merge both the stack and integration. Main was preserved.
Historical trailing now requires break-even first; the baseline used trailing disabled.

## Final verification

- Current full Python suite: **173 passed** (36.95 seconds, final rerun).
- Ruff clean; mypy clean across 31 source files.
- Dashboard: six model tests, actual Edge mobile setup test and production build passed.
- Local Firestore emulator: operator-only PAPER/DEMO reads, unauthorized/anonymous denial,
  all client-write denial, mode restriction and operator revocation passed.
- Actual Python Firebase adapter passed local-emulator event delivery, aggregate repair
  and separate PAPER halt latching. Script: scripts/verify_firestore_mirror.py.
- Windows start/watchdog scripts parsed; offline layer verification commands passed.
  Default paper runtime refuses incomplete/disabled setup.
- Dashboard GitHub CI passed on runtime source commit 89e0cbc:
  https://github.com/iamarasinghe96/forex/actions/runs/36556956061
- Production browser dependency audit: zero vulnerabilities. Development-only Firebase
  CLI tooling: five moderate transitive advisories; no forced major downgrade applied.

## Historical research: complete local runs, not formal validation

All three original imports were verified: EURUSD 48,263 H1 rows, GBPUSD 48,260, USDJPY
48,262; approximately 7.74 years. Full data/reports remain local and ignored by Git.
Research DB: data/dukascopy-research.sqlite3.
Dataset: dukascopy-h1-bid-2019-2026-v1; Dukascopy bid; volume unavailable; fixed UTC H4 hour 0.

Corrected pre-holdout baseline gross expectancy R:
EURUSD -0.06453886285315559; GBPUSD -0.07469902592687842; USDJPY +0.001297812487040083.

Actual fixed-baseline walk-forward process **finished successfully** for all three pairs.
The old session 18157 is finished; do not restart or wait on it. Nine folds per pair were
verified, with 730-day training, 180-day testing/step, one unchanged parameter version and
no optimization. Test span: 2021-01-01 through 2025-06-09 UTC. Final holdout begins
2025-09-28T16:00:00Z and was not evaluated by these runs. An earlier serialization failure
was fixed and regression-tested; only the successful complete reports count.

| Pair | Completed candidate simulations | Gross expectancy R | Gross profit factor |
|---|---:|---:|---:|
| EURUSD | 8,024 | -0.03967421 | 0.923877 |
| GBPUSD | 8,176 | -0.05885054 | 0.889211 |
| USDJPY | 8,824 | +0.04080980 | 1.085538 |

See docs/RESEARCH_RESULTS.md for scope and report SHA256 hashes. Reports are under
reports/backtest/walk-forward-<PAIR>-185c5a2aa8772f0fc863437b3f80b057d449085df03702b9ea1dfe09497e12ab.json.
These include below-minimum-conviction candidate outcomes and are not executed portfolio
returns. Costs remain incomplete, broker DST/H4 equivalence unresolved, and all three
reports explicitly state strategy_validated=false. No candidate was promoted.
Monte Carlo remains IID outcome bootstrap, not trade-order permutation.

## Manual/external completion checklist

OPERATOR_SETUP.md and docs/PAPER_OPERATIONS.md contain the concrete setup steps:
1. Review the draft changes before merging/deploying.
2. DONE: operator selected AUD 100; delegated daily boundary configured as 17:00 New York
   with automatic US DST. Paper/demo execution remain disabled.
3. Configure provider keys/models, Firebase credentials/Auth/operator UID/web settings,
   and optional Telegram credentials locally.
4. Verify actual MT5 demo account, quotes, broker alignment, constraints, execution,
   reconnects and reconciliation; collect genuine costs.
5. Deploy reviewed rules and read-only Pages dashboard; verify access, revocation,
   outages and the separate emergency halt.
6. Configure Windows/VPS startup/watchdog and test backups/recovery under the MT5 session.
7. Run a real unattended paper soak and independently review candidate evidence.

## Resume guidance

There is no unfinished background research to preserve from this checkpoint. Inspect the
working tree and GitHub before any follow-up. The next phase is operator setup and external
evidence, not another implementation pass through the already-built layers. Credentials,
operator decisions and genuine elapsed duration must not be replaced with fabricated values.
No automatic usage-reset retry was configured. Real-money production remains out of scope.

User-facing handoff and full local research copies are in the task outputs folder:
C:/Users/Indika/Documents/Codex/2026-09-29/referenced-chatgpt-conversation-this-is-an/outputs
Files: FOREX_BUILD_HANDOFF.md, WALK_FORWARD_RESULTS.md, walk-forward-summary.json, and the
three full walk-forward reports. Historical baseline evidence is retained separately.

## Setup continuation — 30 September 2026

Operator selected AUD 100 virtual starting balance and delegated the reset time based on
industry practice. Config now uses 17:00 America/New_York, matching IC Markets published
New York-close day. Added an explicit NY-close option alongside backward-compatible fixed
UTC settings, mutual-exclusion validation, and DST-boundary regression tests. This is an
unmerged change on draft PR #18. No default paper database or running MT5 terminal was
found during setup. Next user action: open MT5 and sign into the configured IC Markets AU
demo account; credentials stay local. Then perform read-only account/quote/spec checks.

Setup verification: full suite 180 passed, including winter/summer and both US DST transition
days; Ruff and mypy clean after an explicit naive-timestamp test fixture adjustment.
