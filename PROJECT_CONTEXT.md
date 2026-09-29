# Project requirements and current reconciliation

This project continues from merged main `6b0273d8ccc84143ffeb0495adcf9a19f0021d8b`.
Do not restart or rebuild Layers 1–5 from the original brief.

## Authority

1. Explicit later operator decisions and guardrails, including [the later guardrails](docs/later-project-guardrails.md).
2. Existing merged implementation and its tested behavior.
3. [The original build brief](docs/original-build-brief.md), retained as the original requirements baseline.

The operator supplied this precedence on 29 September 2026. The original brief is
historical context where it conflicts with later decisions. Its initial-build instructions,
prototype fusion weights and layer numbering do not reset the completed implementation.

The operator authorizes local commands, coding, tests, branches, commits, pushes and PR
preparation. Pause before merging changes to strategy semantics, risk policy, layer interfaces,
validation/H4 methodology, execution, learning/promotion, or major architecture. First report
what was found, why the change is needed, changed files, test/Ruff/mypy evidence, and whether
agreed behavior changes. Keep broker/VPS verification separate from offline test evidence.

## Original requirement → merged-main implementation → outstanding at reconciliation

This table records the starting merged-main state. For the completed draft implementation
through Layer 11 and remaining external checks, read BUILD_PROGRESS.md.

| Requirement | Merged implementation | Still outstanding |
|---|---|---|
| Shared deterministic strategy/risk | Pure Layer 3 analysis; shared Layer 5 conviction in research; tested sizing/risk policy | Full portfolio/execution replay with genuine historical account-currency/broker metadata |
| Graded agreement and day/swing classification | Implemented; unavailable macro is explicit | Genuine optional news/calendar context and operational holding rules |
| Conviction/risk ceilings | `(1 - uncertainty) * 100`; 55/70/85 thresholds, 2/3.5/5% tiers, 1:30 leverage cap, 1.5R floor, 4 positions, 20% risk, 12% circuit breaker | Broker/runtime enforcement and operational verification |
| Historical validation | Replay, normalized-R metrics, walk-forward functions, IID bootstrap, provenance imports | Broker-aligned H4, observed execution costs, completed OOS evidence, account-level reporting and readable equity reporting |
| LLM context/review | Layer 5 ceiling helper | Structured JSON, provider failover, cache, costs, versioned prompts and journal provenance |
| Execution resilience | Read-only broker adapter and order placeholders | Runtime constraints/retcodes, placement, idempotency, broker-authoritative reconciliation and restart recovery |
| Journal/Firestore | SQLite, risk latches, outbox foundation | Every candidate/rejected/no-trade/executed state, attribution, reserve ledger, exports, async cloud mirror/reconciliation |
| Dashboard | Not implemented | Authenticated read-only visibility; later read-only rule overrides original embedded controls |
| Alerts and controls | Mode-labelled logs and optional Telegram transport | Event wiring, remote emergency-control path, watchdog, daily/no-trade alerts |
| Paper soak | PAPER configuration and log labels | Actual full-path simulated runtime on live data, failure tests and elapsed soak evidence |
| Deployment | Foundation runbook | Windows service/recovery, backups, safe updates and environment verification |
| Performance intelligence | Research snapshots, rejection reasons and labelled outcomes | Evidence-backed diagnosis, hypotheses, historical/OOS tests, candidate versions, shadow/paper and gated promotion |

The later build sequence is Layers 6 LLM Context, 7 Execution, 8 Journal & Attribution,
9 Dashboard, 10 Paper Soak, 11 Performance Intelligence. Deployment requirements remain
outstanding even though the original brief called deployment Layer 11. Layer 12 real-money
production is outside the current development authorization.

Do not restore prototype 50/25/25 fusion. The 3–8/week target refers to future executed
trades and is calibration context, never a candidate-frequency veto. Unavailable context
must not be fabricated or penalized. Learning must include rejected/no-trade states and
must not automatically mutate production parameters or block trading after recent losses.

## Research status and pending corrections

The genuine local Dukascopy H1 Bid dataset contains EURUSD 48,263, GBPUSD 48,260 and USDJPY
48,262 rows over approximately 7.74 years. Research H4 is derived from complete H1 groups
at fixed UTC hour 0. It is not established as equivalent to IC Markets broker-native H4.
Spreads/commission/slippage/swap are incomplete; no realistic profitability or formal
strategy validation follows from a five-year depth gate or a successful command exit.
Raw CSV/tick data, research SQLite databases and secrets stay out of Git.

- Draft PR #9 proposes a CLI holdout correction: baseline replay previously covered the
  full history before the reserved holdout dates were attached. The candidate correction
  bounds decisions and outcomes first. This changes baseline metrics, while preserving
  the intended reserved-holdout protocol. The separate walk-forward function already
  enforced its boundaries. Review before merge.
- Draft PR #10 proposes exact causal indicator preparation to make long research replay
  practical. It is stacked on #9 and is not a strategy/parameter change. Review before merge.
- Additional candidate defect: Layer 4 simulation currently permits configured ATR trailing
  before the breakeven stage. The default multiple is null, so current baseline runs do not
  exercise this path. The integration branch now fixes this with a break-even latch and
  regression coverage; review the semantic correction before merge.

At initial reconciliation the CLI reported planned walk-forward windows only. The integration
branch now includes an executed fixed-baseline walk-forward command; nine folds per pair
completed, with evidence in docs/RESEARCH_RESULTS.md. Current
Monte Carlo is seeded IID bootstrap, not the original brief's trade-order permutation;
these are distinct methods and must not be silently relabelled. Current research is in
normalized R, not an account-sized portfolio simulation. Preserve these distinctions.
