# Prompt for an external deep-research review

Paste everything below the line into ChatGPT. It is written to be read by an AI.

---

## ROLE

Act as an adversarial quantitative researcher and FX market-microstructure expert. Your job is
to **break** this project first, then find what could make it profitable.

- Assume nothing works until the evidence shows it.
- Every claim needs a source: a peer-reviewed paper or central-bank working paper with
  year/author/link, or a file and line in this repository.
- Label each claim **VERIFIED** (with source) or **HYPOTHESIS**.
- Do not promise profits.

## PROJECT IN ONE PARAGRAPH

An automated forex bot runs on a Windows VPS against an IC Markets MT5 **demo** account, used for
data only. All trades are simulated by a PaperBroker on an A$1,000 paper account; real-money and
demo execution are disabled in code. Pairs are EURUSD, GBPUSD and USDJPY. The bot decides every
hour. Goal: a strategy with a **positive expected return after real costs**, robust out of
sample, that a small account can run automatically.

## WHERE TO LOOK

Repository: `iamarasinghe96/forex`, branch `claude/determined-thompson-f4ewei`, commit `88952c9` or
later. Read these first.

**Code: entries, exits and sizing**

| File | What it contains |
|---|---|
| `src/forex/analysis.py` | All entry logic: `feature_state` (indicators), `calculate_regime` (H4 trend label), `_candidate_logic` (entry decision), `analyse_market` |
| `src/forex/runtime.py` | Hourly cycle: analysis, risk check, AI context review, learning sizing, paper execution, trailing-ATR refresh, cost recording |
| `src/forex/risk.py` | `decide_risk` (sizing and limits); `protective_stop` (break-even at +1R, then N x ATR trail) |
| `src/forex/paper.py` | Simulated fills at live bid/ask, stop and target checks, P&L |
| `src/forex/learning.py`, `src/forex/telegram_commands.py` | Learning loop: per-settings-version bucket scores, size reduction only for reliably losing buckets, operator-approved setting patches |
| `config.yaml` | Every live parameter |

**Research scripts**

| File | Purpose |
|---|---|
| `scripts/causal_replay.py` | One chronological replay per pair plus 1,000 matched random-entry controls |
| `scripts/swing_structure.py` | Classic swing rules test: Dow-theory swings, tight consolidation, breakout close, swing-low trailing exit |
| `scripts/slow_momentum.py` | Monthly time-series momentum benchmark |
| `scripts/research_*.py`, `src/forex/backtest.py` | Walk-forward machinery |
| `scripts/cost_report.py`, `src/forex/costs.py` | Live spread and swap recorder (recording since the 2026-10-03 deploy) |

**Documents**

| File | Contents |
|---|---|
| `BUILD_PROGRESS.md` | Full history, pre-registrations 1-4 with their results |
| `docs/STRATEGY_JOURNAL.md` | Operator ideas and how they were judged |
| `docs/EXTERNAL_REVIEW_HANDOVER.md` | Machine-oriented summary of the earlier research |
| `docs/CODEX_REVIEW_FACTCHECK.md` | Previous external review, fact-checked, with real-data results |
| `docs/SWING_TRADING_REVIEW.md` | Swing-trading theory compared with the bot, with literature |

## EXACT CURRENT STRATEGY (verify against the code)

**Trend label (H4)**
- direction = tanh((EMA20-EMA50 gap in ATRs + EMA20 slope in ATRs + 5-bar follow-through) / 2)
- trend = 0.45·|direction| + 0.55·directional efficiency
- Efficiency window: 10 H4 bars (config J6-b).
- TREND_UP/DOWN when trend ≥ 0.55 and |direction| > 0.15.
- The high-volatility block is OFF (J6-a).

**Entry**
- On each closed H1 bar in a trend regime, the setup score is the mean of four components:
  - H4 trend strength;
  - H1 MACD-histogram alignment;
  - position in the 20-bar H1 range;
  - closeness to the H1 EMA20.
- If the score is ≥ 0.45, it buys or sells at market.
- No consolidation, breakout or pullback condition exists, despite the setup's name
  "TREND_CONTINUATION_BREAKOUT_PULLBACK".
- Range mean-reversion setups are disabled; they lost in every out-of-sample year.

**Filters**
- An AI news/context review (Groq/Gemini/OpenRouter) can reject a trade or reduce its size.
- One open position per pair.
- Conviction floor 0.

**Stop and exits**
- Initial stop: the 20-bar H1 low (long) or high (short).
- Break-even at +1R.
- After +1R, trail 3 × the latest H1 ATR(14).
- Target 10R. No time exit.

**Sizing and limits**
- 5% of balance risked per trade (aggressive paper profile chosen by the operator).
- Daily loss circuit 25%; maximum leverage 30.

## EVIDENCE SO FAR

**Data**
- Dukascopy H1/H4 **bid-only** candles for the 3 pairs, 2012-2026.
- Costs assumed: round trip 0.9/1.2/1.0 pips; no swap; fixed UTC H4 bars.

**Walk-forward research settings** (1.5R target, conviction ≥ 55, 120-bar time exit)

| Period | Trades | Net R per trade | PF |
|---|---|---|---|
| 2012-2018 | 475 | +0.028 | 1.06 |
| 2021-2025 | 361 | +0.040 | 1.09 |
| Final holdout (2025-26, used once) | 56 | −0.30 | 0.51 |

- Per-trade SD is about 1.06R. Detecting +0.03 R/trade at 2 SE needs about 5,000 trades.
- The bootstrap 95% CIs for the main strategy include zero in both periods.

**Causal replay** (no window boundaries; 1,000 matched random-entry controls with the same
direction, stops, exits and costs)

| Period | Strategy R per trade | Random controls R per trade | Controls ≥ strategy |
|---|---|---|---|
| 2012-2018 | +0.026 | −0.069 | 4% |
| 2021-2025 | +0.042 | −0.048 | 7% |

- The entry timing adds about +0.09R over random entries, but the net edge stays about zero
  after costs.
- By pair: USDJPY positive in both periods, GBPUSD negative in both, EURUSD mixed.

**Other tests**
- Variants J6-a and J6-b each passed one period and failed the other.
- A 3×ATR trailing exit passed two periods and failed the holdout.
- Slow time-series momentum on the 3 pairs: +0.70%/yr, not distinguishable from constant-long;
  −0.78%/yr under cost and financing stress. FAIL.
- AlphaLedger leaderboard "winners" inspected: they average into losing positions and close
  baskets. One basket carried at least −$1,398 floating for a +$48.81 result. No copyable rules.

**Pending**
- Swing-structure test (pre-registration 4).
- Replay of the exact live settings (10R target, 3×ATR trail, conviction 0).
- Live spread and swap measurement.

## CONSTRAINTS

- Retail costs (IC Markets Raw or Standard), MT5, Python. Decisions on H1 bars or slower.
- Small account. Any strategy must survive a 2× cost stress and include swap.
- The operator accepts high paper risk but wants **real** expected profit, not luck.
- More Dukascopy pairs can be downloaded: AUDUSD, USDCAD, USDCHF, NZDUSD, EURJPY, GBPJPY and
  more. There is no tick history, no order-book data and no historical news calendar yet.
- Research discipline already in use: rules fixed and pass criteria written before data is run;
  random-entry controls; out-of-sample periods. Keep it.
- No grid, martingale or averaging-down proposals unless you quantify their tail risk.

## TASKS

**1. Break it.** Find every way the current results could be wrong or misleading:
- look-ahead;
- survivorship or selection;
- data snooping across the many variants tried;
- bid-only data bias;
- intrabar stop/target ordering;
- weekend gaps;
- cost and swap realism;
- H4 bar alignment against the broker's server time;
- AI-review leakage;
- the learning loop overfitting live noise.

Cite `file:line` for each.

**2. Literature.** What has **documented, after-cost** evidence in FX at H1-to-monthly horizons?
Consider:
- carry;
- time-series momentum across many currencies;
- cross-sectional currency momentum and value;
- intraday and session seasonality (e.g. around the London 4 pm fix and Tokyo fixing);
- short-horizon mean reversion;
- volatility-breakout and range-expansion rules;
- event and news drift;
- chart patterns;
- anything else relevant.

For each, give:
- effect size;
- sample period;
- whether it decayed after publication;
- whether it is reachable for a retail MT5 account.

**3. Diagnose.** Given the evidence above:
- Is the hourly trend-continuation approach worth continuing?
- Is the measured +0.09R timing advantage likely real, and what could convert it into net profit?
  Consider fewer, better entries; wider stops on higher timeframes; exits; pair selection; cost
  reduction.
- Judge the USDJPY concentration: is it carry, the BoJ regime, or chance?

**4. Propose at most 3 strategies, ranked.** For each, give:
- exact, codeable rules: entry, stop, exit, sizing, timeframe, pairs;
- data needed;
- expected trades per year;
- the pre-registered pass/fail test: periods, controls and thresholds;
- what result would falsify it;
- where it plugs into this codebase (files and functions).

At least one should use more pairs to reach statistical power.

**5. Sizing.** Recommend risk per trade from the measured edge and variance (Kelly and
fractional Kelly), and assess the current 5%.

**6. Setup score and dynamic risk.** Read `docs/SETUP_SCORE_SPEC.md`. The operator wants each
opportunity scored 0-100 from past, scale-invariant patterns, with higher scores taking more
risk. Note that the existing conviction score was inversely related to results.
- Critique the spec.
- Recommend the feature set and model (bucket table, regularised linear, k-NN analog or monotone
  GBM).
- If the data is available, build the dataset with the research scripts and run acceptance
  tests T1-T7 out of sample.
- Report the scorecard as "N/7 passed", with numbers.

**7. Verdict.** Give a one-paragraph honest answer: is a profitable retail FX bot realistic here,
and what is the single highest-value next experiment?

## OUTPUT FORMAT

1. A JSON block:
   `{"defects": [{"claim", "evidence", "severity", "fix"}], "literature": [{"strategy", "source", "effect_after_costs", "decay", "retail_feasible"}], "proposals": [{"name", "rules", "data", "trades_per_year", "test", "falsified_if", "code_location"}], "sizing": {...}, "setup_score": {"scorecard": "N/7", "tests": [...], "recommended_model": "..."}, "verdict": "..."}`
2. Then plain-English prose for the operator, who is learning to trade: short sentences, no
   jargon without a one-line explanation.
