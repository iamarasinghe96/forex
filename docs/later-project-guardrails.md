Project context / guardrails — please treat this as authoritative for this Forex project.
We have already designed this system layer-by-layer in another long-running chat. Do not redefine the architecture simply because the repo does not contain every future-layer decision.
Current status
Layers 1–5 are already implemented and merged.
- Layer 1 — Foundation ✅
- Layer 2 — Market Data ✅
- Layer 3 — Analysis / deterministic strategy ✅
- Layer 4 — Backtesting/research engine ✅, but formal strategy validation is not complete
- Layer 5 — Deterministic Fusion/Risk ceiling ✅
- Historical research import architecture ✅
- Layer 6+ has not yet been implemented.
The authoritative main commit before this Work session began was:
6b0273d8ccc84143ffeb0495adcf9a19f0021d8b
The local research dataset has now been built and verified from Dukascopy:
- EURUSD / GBPUSD / USDJPY
- H1 Bid
- 2019-01-01 through 2026-09-28
- EURUSD: 48,263 rows
- GBPUSD: 48,260 rows
- USDJPY: 48,262 rows
- no fabricated candles
- 13 bad EURUSD H1 closes were independently verified/repaired from Dukascopy tick data
- 531 missing EURUSD H1 candles were rebuilt from Dukascopy tick data
- provenance/hashes are preserved
Important Layer 4 warning
Do NOT declare Layer 4 formally validated merely because there are now >5 years of data or because validate-backtest exits successfully.
There are still two methodological issues we already identified:
1. Research H4 currently uses a fixed UTC alignment, while live IC Markets H4 candles are broker/server-DST dependent. A fixed UTC H4 series is not automatically equivalent to the live strategy’s H4 boundaries.
2. Current research data is Bid-only and therefore does not yet provide a complete realistic historical transaction-cost model. Spread/commission/slippage/swap cannot be guessed or fabricated.
These must be resolved or explicitly bounded before claiming formal strategy validation.
Layer 4 protocol
- ≥5 years H1/H4
- same deterministic Layer 3 logic
- no lookahead
- next-H1 research fills
- structural invalidation
- minimum RR 1.5
- breakeven only after 1R
- ATR trailing only after breakeven
- adverse treatment of intrabar ambiguity
- chronological walk-forward
- reserved final holdout
- Monte Carlo
- realistic costs where genuine data exists
- no fabricated assumptions presented as observed facts
- parameters remain UNVALIDATED until evidence supports promotion
The desired 3–8 trades/week is only a future executed-trade calibration target, not a hard strategy veto and not a requirement on raw candidate frequency.
Layer 5 policy — already implemented
- conviction = (1 - candidate.uncertainty) * 100
- below 55: ineligible
- 55–<70: 2% risk
- 70–<85: 3.5%
- 85–100: 5%
- leverage must remain ≤1:30
- minimum RR 1.5
- max positions: 4
- max simultaneous portfolio risk: 20%
- daily circuit breaker: 12%
- BE at 1R
- ATR trailing only after BE
- runtime MT5 tick/pip/volume metadata only; do not invent constants
- Layer 5 is a ceiling, not a recommendation to increase risk
Planned remaining architecture
Layer 6 — LLM Context
LLM/context layer may add qualitative context, uncertainty or veto/reduce a deterministic Layer 5 allowance. It must never increase risk above Layer 5, enlarge position size, loosen a stop, lower minimum RR, or bypass a risk block. Unavailable context is neutral, not fabricated.
Layer 7 — Execution
Production-safe MT5 execution/reconciliation. MT5 is source of truth for open positions. Prevent duplicate orders, reconcile state after restart/network failure, validate broker constraints at runtime, and fail safely. No execution logic should silently modify strategy/risk rules.
Layer 8 — Journal & Attribution
Persist all candidate, executed, rejected and no-trade states. Use evidence-backed, multi-label attribution. Distinguish hard risk blocks from analytical/learning outcomes. Do not learn only from winners/losers.
Layer 9 — Dashboard / Operator visibility
Read-only operational visibility into system state, trades, risk, decisions, attribution, data health and alerts. Dashboard must not become a hidden execution path.
Layer 10 — Paper Soak
Long-running unattended paper-trading soak before real money. Exercise restart recovery, stale feed behaviour, broker errors, duplicate prevention, alerts, kill controls, state reconciliation and operational failure modes.
Layer 11 — Performance Intelligence / Strategy Decay
Closed-loop learning is:
observe → diagnose/attribute → hypothesis → historical/recent testing → walk-forward/OOS → candidate version → shadow/paper → promotion
It must analyse executed trades and generated/rejected/no-trade decisions.
Do not implement crude reactive rules such as “3 losses = stop trading” or automatically mutate production strategy parameters after recent losses.
Parameter/version promotion must be evidence-backed and gated.
Layer 12 — Production
Real-money production comes after Layer 10/11 evidence and is not part of the current development target unless explicitly approved later.
General architecture rules
- local-first SQLite
- UTC throughout
- MT5 source of truth for broker/open-position state
- deterministic core first
- no invented market data
- no unsourced constants
- no lookahead
- no automatic strategy/risk loosening
- no secret credentials committed to Git
- historical CSV/tick data and research SQLite databases must not be committed to GitHub
- GitHub remains source of truth for code
Workflow
You may execute PowerShell, edit code, test, create branches, commit, push and prepare PRs with minimal involvement from me.
However, pause before merging any PR that changes strategy semantics, Layer boundaries, validation methodology, risk policy, execution behaviour, learning/promotion logic, or the agreed architecture above. Show me:
1. what was found,
2. why the change is needed,
3. what files changed,
4. tests/Ruff/mypy results,
5. whether it changes an agreed behaviour.
Pure bug fixes that preserve established behaviour may be implemented and tested, but still do not silently redefine the system.
Regarding the holdout issue you just identified: please treat it as a candidate bug fix. Explain precisely how the old code leaked/evaluated the reserved holdout, what your modification changes, and whether it alters any previously intended Layer 4 semantics before we accept/merge it.
Continue the current Layer 4 research work after applying these guardrails.