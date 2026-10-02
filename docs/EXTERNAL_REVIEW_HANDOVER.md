# EXTERNAL_REVIEW_HANDOVER v1 (machine-oriented; for third-party AI review)

```yaml
meta:
  generated_utc: 2026-10-02
  author: Claude Code session (handover; operator continues with another assistant)
  repo: https://github.com/iamarasinghe96/forex   # public
  branch: claude/determined-thompson-f4ewei        # all work; PR #18 NOT merged; main untouched
  head_commit_at_writing: a935b91
  deployed_on_vps: 0a4ac35 (learning loop + one-position-per-pair fix); a935b91 adds only a read-only script
  primary_records:            # authoritative; this file summarises them
    - BUILD_PROGRESS.md        # chronological log, pre-registrations, results (numbers below are copied from it)
    - docs/STRATEGY_JOURNAL.md # operator reading notes -> candidate ideas J1..J6 with status
    - docs/LEARNING_RESOURCES.md
    - docs/LEARNING_LOOP.md
    - docs/RESEARCH_RESULTS.md # walk-forward report hashes
  evidence_tags: {M: measured from data/run output, C: computed from M, E: estimate/assumption, O: opinion/hypothesis}
operator:
  goal_stated: "make profit from small capital; originally 20%/week (assessed unrealistic)"
  goal_current: "solid learning model for trial-and-error; paper money; seeking external review of direction"
  risk_attitude: "accepts paper losses; wants aggressive action"
hard_constraints:
  - real-money trading disabled; execution.demo_enabled=false; PaperBroker never calls MT5 order APIs
  - credentials (.env, Firebase admin JSON, Telegram token) never printed or committed
  - do not merge PR #18 without review
```

## 1. System / infrastructure (what exists and runs)

```yaml
runtime:
  host: Windows VPS, repo C:\forex, Python venv, MT5 terminal (IC Markets AU demo 23011822, data only)
  symbols: {EURUSD: EURUSD.a, GBPUSD: GBPUSD.a, USDJPY: USDJPY.a}   # plain symbols are CLOSE_ONLY at broker; .a are FULL
  mode: paper (simulated fills at live bid/ask; no commission/swap/slippage modelled)
  paper_account: {database: data/paper-a1000.sqlite3, start_balance_aud: 1000, started_utc: 2026-10-01}
  previous_account: {database: data/paper.sqlite3, start_aud: 100, end_balance_aud: 96.70, trades: 1 (USDJPY range trade, STOP, -3.30)}
  loop: poll 5 s; analysis hourly at HH:00 on closed H1/H4 bars; management (stops/trailing) every cycle
  launcher: scripts/run-bot.ps1 (desktop + Startup icon "Forex Paper Bot"; duplicate guard; retry 120 s; QuickEdit disabled)
  start_check: waits for a live tick, validates server clock, then runs
monitoring:
  telegram_alerts: trade_opened/closed, alerts, errors (grace 30 s, repeat hourly), readable daily summary, trade reviews, strategy updates
  telegram_commands (operator chat id only): /help /scores /settings /review /approve N /reject N /rollback; pasted JSON change sets
  firestore_mirror: every journal event mirrored (outbox, retry, nested arrays wrapped {items:[...]})
  dashboard: GitHub Pages https://iamarasinghe96.github.io/forex/ (Vite + Firebase Auth, read-only)
    simple_view: bot state (heartbeat <=180 s), period dropdown (24h/7d/14d/30d/90d/all), invested, profit, balance, trades, won, lost, open trades with unrealized P&L, latest trades
    invested_formula: latest_balance - realized_pnl_aud (all time)
    account_reset_filter: trades closed before summary.first_event_at_utc are ignored (fresh account)
    technical_view: equity curve, filters, CSV export, reserve (tax 32.5%) evidence
ai_providers (free tiers): [groq openai/gpt-oss-120b, gemini gemini-3.1-flash-lite, openrouter gemma (429-limited)]
  uses: (1) pre-trade context review can approve/reject/reduce size only; (2) post-trade explanation
code_quality: 219 pytest tests pass; ruff clean; mypy clean except 2 Windows-only msvcrt lines on Linux
```

## 2. Strategy definition (exact, as implemented in src/forex/analysis.py, risk.py, paper.py)

```yaml
data: H1 and H4 candles (H4 regime, H1 trigger)
features (per timeframe):
  ema: {fast: 20, slow: 50, context: 200}
  rsi: 14; macd: 12/26/9; atr: 14
  structure_window: 20   # rolling high/low of previous 20 bars (excl. current)
  volatility_rank: percentile of current ATR within last 100 ATR values
  directional_efficiency (Kaufman ER): |close[-1]-close[-W]| / sum|close[i]-close[i-1]| over W bars; W = trend_efficiency_window or structure_window(20)
  ema_fast_slow_atr: (ema20-ema50)/atr; ema_slope_atr: (ema20 - ema20[-5])/atr
  directional_follow_through: mean sign of last 5 closes' changes
  range_position: (close-low20)/(high20-low20); mean_zscore: (close-mean20)/std20
regime (on H4):
  direction = tanh((ema_fast_slow_atr + ema_slope_atr + follow_through)/2)
  trend = min(1, 0.45*|direction| + 0.55*efficiency); range_strength = 1 - trend
  label:
    HIGH_VOLATILITY if volatility_rank>=0.9 (unless high_volatility_blocks_trend=false and trend>=trend_threshold and |direction|>0.15)
    TREND_UP/DOWN if trend>=0.55 and direction>+-0.15
    RANGE if range_strength>=0.58
    UNCERTAIN if |direction|<0.1 else TRANSITION
setups:
  TREND_CONTINUATION_BREAKOUT_PULLBACK (only enabled family):
    side = sign(direction)
    components: {h4_trend: trend, h1_momentum: max(0, sign*tanh(macd_hist/atr)), structure: max(0, sign*(range_position-0.5)*2), pullback_coherence: max(0, 1-|close-ema20|/atr/3)}
    score = mean(components); candidate if score >= setup_score_threshold (0.45)
  RANGE_MEAN_REVERSION: disabled (allowed_setups) - lost in every tested year
  style: SWING if trend>=0.68 else DAY (label only)
conviction: (1 - uncertainty)*100 = score*100; risk tiers by conviction thresholds
stop: structural = rolling_low (long) / rolling_high (short) of last 20 H1 bars; median stop ~72-86 pips (M, 13-year exports)
exits: break-even at +1R; optional ATR trailing after +1R (trail = close -/+ m*H1_ATR, never loosens); fixed target (R multiple)
sizing: volume = floor(balance*risk% / (stop_distance*value_per_unit) / 0.01)*0.01; blocked if < 0.01 lot
portfolio_limits: max 4 positions, max 20% total open risk, max 1 position per pair (added 2026-10-01), daily loss circuit
costs_assumed_in_research (E): round-trip 0.9 / 1.2 / 1.0 pips (EURUSD/GBPUSD/USDJPY); not measured from broker
```

```yaml
live_profile_now: "operator-aggressive-v1 (operator choice; NOT validated)"
settings:
  analysis: {high_volatility_blocks_trend: false, trend_efficiency_window: 10, trend_threshold: 0.55, setup_score_threshold: 0.45, allowed_setups: [TREND_CONTINUATION_BREAKOUT_PULLBACK]}
  risk: {per_trade_percent: 5 (all tiers), conviction_minimum: 0, daily_loss_percent: 25, max_simultaneous_risk_percent: 20}
  exits: {target_reward_risk: 10, atr_trailing_multiple: 3, breakeven_at_r: 1}
  paper: {max_positions_per_pair: 1, stale_quote_alert_seconds: 900}
  learning: {enabled: true, prior_trades: 20, min_trades: 10, min_factor: 0.25, skip_below_r: null}
previous_profiles: [unvalidated-v1 (all setups, conviction>=55, 2/3.5/5%), trend-only-v1 (2026-09-30)]
```

## 3. Data

```yaml
datasets:
  research_2019_2026: {source: Dukascopy H1 BID via dukascopy-node 1.50.0, id: dukascopy-h1-bid-2019-2026-v1, fingerprint: 185c5a2aa877, rows: {EURUSD: 48263, GBPUSD: 48260, USDJPY: 48262}, span_years: 7.74}
  independent_2012_2018: {same tool/settings, fingerprint: bed3584927bd, rows: {EURUSD: 43635, GBPUSD: 40441, USDJPY: 42009}, flats_excluded: true, repairs: 0, eval_from: 2012-04-01 (warm-up)}
  vps_stored_candles: ~365 days H1/H4 per pair in paper DB (from MT5), used for replays/scans
known_data_limits: [bid only (no spread history), volume unavailable, H4 built at fixed UTC hour 0 (broker H4 alignment unverified), H1 granularity -> intra-bar stop/target order unknown (policy: adverse first)]
```

## 4. Method

```yaml
unit_of_result: R = (exit - entry)*side / |entry - initial_stop|; net R = gross R - cost_pips*pip/|entry-stop|
walk_forward: {train_days: 730, test_days: 180, step_days: 180, folds_per_pair: 9, test_span: 2021-01-01..2025-06-09, parameters: fixed (no optimisation)}
final_holdout: 2025-09-28T16:00Z..2026-09-28 (CONSUMED once on 2026-09-30)
sequencing: one open trade per pair (research_summary.one_at_a_time); every-signal stats also reported
pre_registration: hypothesis + exact rule + pass criterion written to BUILD_PROGRESS.md before data examined
pass_rule: net average R > 0 AND net profit factor > 1 (all pairs combined); prereg3 adds "beats baseline on both periods"
scripts:
  research_trades.py: per-trade OOS export (walk-forward or single window), --reward-risk/--atr-trailing/--horizon-bars/--analysis-set
  research_summary.py: costs, one-at-a-time, rule sets, by year
  research_entries.py: signal-N-in-a-row, stop-size, per pair
  research_candidate.py: pre-registered rules confirm3 / trend55; verdict; account-size feasibility (0.01 lot, A$0.15/pip/0.01 lot approx)
  replay_decisions.py: hourly replay of live analysis on stored candles + rough one-at-a-time trade sim
  scan_protections.py: remove one protective layer at a time on stored candles; compare A$/R
  why_no_trade.py / open_risk.py: read-only journal diagnostics
verification: export reproduced walk-forward counts exactly (EURUSD 8024, GBPUSD 8176, USDJPY 8824)
```

## 5. Experiments and results (chronological; all numbers M unless tagged)

```yaml
E1_walk_forward_baseline (2021-2025 OOS, gross, every candidate incl. below-min conviction, all setups):
  EURUSD: {n: 8024, expectancy_R: -0.0397, PF: 0.924}
  GBPUSD: {n: 8176, expectancy_R: -0.0589, PF: 0.889}
  USDJPY: {n: 8824, expectancy_R: +0.0408, PF: 1.086}
E2_factor_breakdown (same OOS, gross):
  conviction_bands_inverse: {below_min: +0.028 (11445), LOW: -0.033 (10274), MEDIUM: -0.121 (3175), HIGH: -0.323 (130)}   # higher "confidence" -> worse
  setup: {trend_continuation: +0.063 (9133), range_mean_reversion: -0.064 (15891)}
  style: {swing: +0.096, day: -0.041}; high_volatility: -0.075
E3_rule_sets (2021-2025, net, one per pair):
  live_rules_then (all setups, conv>=55): {avg: -0.488 R, n: 6643, every year negative}
  trend_only_conv55 ("trend55"): {avg: +0.040 R, PF: 1.09, n: 361, ~1.6/week, by_year: [2021 -0.085, 2022 +0.162, 2023 +0.028, 2024 +0.082, 2025 -0.101]}
  action: range disabled -> trend-only-v1 deployed 2026-09-30
E4_prereg1_confirm3 (trend, conv>=55, enter on 3rd consecutive signal): 2012-2018 {n: 349, avg: -0.001 R, PF: 1.00} -> FAIL
  supporting_2012_2018: {all_setups: -0.425 R (9548, every year negative), trend55: +0.028 R PF 1.06 (475; 5/7 years positive)}
E5_prereg2_trailing (trend55, no target, BE 1R, 3xATR trail, max 480 bars):
  2012_2018: {n: 418, avg: +0.013 R, PF: 1.03} PASS
  2021_2025: {n: 297, avg: +0.079 R, PF: 1.16} PASS
  note: USDJPY positive in all 4 runs (+0.063, +0.162, +0.313, +0.486); EURUSD/GBPUSD negative
E6_final_holdout (2025-09-28..2026-09-28, used once, trend55+trailing): {n: 56, avg: -0.303 R, PF: 0.51} FAIL
  by_pair: {EURUSD: -0.080 (18), GBPUSD: -0.321 (17), USDJPY: -0.480 (21)}; secondary USDJPY-only also failed
  conclusion_then: no variant shows reliable edge; real money not recommended
E7_chart_review_replay (Sep 9-30 2026, operator screenshots; live code on VPS candles; rough sim, 1.5R target, BE 1R):
  market_moves_pips: {EURUSD: -276, GBPUSD: -248, USDJPY: +414, USDCHF: ~+250 (not traded)}
  bot_would: {EURUSD: +1.89 R (+132 pips, 3 closed), GBPUSD: +1.48 R (+74), USDJPY: -1.02 R (-89)}; total +2.35 R (~12% of move captured)
  diagnosis: [trend labelled ~2-3 days late (USDJPY +270 pips labelled RANGE), HIGH_VOLATILITY blocked 107 EURUSD trend hours, 1.5R cap small vs 3-5x moves]
  evidence_level: anecdote (one favourable month)
E8_protection_scan (stored candles 2025-11-15..2026-10-01; A$100; 2-5% sizing; live exits):
  current_rules: {trades: 2, R: +2.94, A$: +9.35}   # ~1300 idea-hours blocked by conviction<55, ~240 by 0.01-lot minimum
  conviction_and_minlot_off: {trades: 83, win: 35%, R: -3.59, A$: -64.79, max_risk_per_trade: 29%}
  +J6a: {R: -5.29, A$: -103.75}; +J6b: {R: -1.44}; +J6a+b: {R: -3.53}; +setup_threshold_off: {R: -22.28}; range_on: {R: -438}
  conclusion: on that year, blocked trades lost on balance (layers saved money); A$100 cannot hold typical 70-90 pip stops at 2-5% risk
E9_prereg3_J6 (trend55, 1.5R, BE 1R; must beat baseline on both periods):
  baseline: {2012_2018: +0.028/1.06/475, 2021_2025: +0.040/1.09/361}
  J6a_vol_block_off: {2012_2018: +0.037/1.08/511, 2021_2025: +0.019/1.04/395} FAIL
  J6b_efficiency_window_10: {2012_2018: -0.003/0.99/713, 2021_2025: +0.091/1.22/536} FAIL
  J6b_by_year_2021_2025: [2021 +0.100, 2022 +0.210, 2023 -0.008, 2024 +0.152, 2025 -0.198]
  J6b_by_year_2012_2018: [2012 -0.014, 2013 +0.029, 2014 +0.098, 2015 +0.039, 2016 -0.018, 2017 -0.040, 2018 -0.106]
  account_feasibility (0.01-lot min, A$0.15/pip/0.01 lot approx): A$100 -> 0-2 trades per period fit; A$1000 -> 87-96% fit (baseline 456/475 and 321/361), similar R (+0.021 / +0.067)
```

```yaml
statistics_caveats (C/E):
  per_trade_R_sd_estimate: ~1.2 R (E; 1.5R-target outcomes cluster at -1/0/+1.5)
  std_error_trend55_2012_2018: 1.2/sqrt(475) = 0.055 R -> 95% CI about +0.028 +- 0.11 (C from E)
  std_error_trend55_2021_2025: 1.2/sqrt(361) = 0.063 R -> 95% CI about +0.040 +- 0.12
  implication: baseline indistinguishable from 0; differences between variants (~0.02-0.05 R) are within noise
  multiple_testing: ~5 pre-registered tests + many exploratory cuts on 2021-2025 -> 2021-2025 no longer clean; holdout consumed
  drawdowns: trend55 max DD ~16-17 R -> at 5% risk ~ -55% account (C); at 1% ~ -16%
  regime_dependence: profits concentrated in USDJPY 2021-2024 (carry-trade trend); failed in 2025-26
```

## 6. Live paper evidence (small; not statistically meaningful)

```yaml
A100_account (2026-09-30..10-01): 1 closed trade (USDJPY range setup, STOP, -A$3.30)
A1000_account (from 2026-10-01, aggressive profile):
  opened: 4 x EURUSD SELL at 09:00, 10:00, 11:00, 12:00 UTC 2026-10-01 (hourly repeat signals stacked; bug)
  bug_fix: paper.max_positions_per_pair=1 (deployed 0a4ac35); existing 4 left to exit by their own stops
  unrealized_snapshot: {equity_aud: 1112.93 at ~2026-10-01T15:33Z; dashboard later +17.43,+11.12,+27.36,+64.80 = ~+120.7}
  closed_trades: 0 at writing
  interpretation: one favourable EUR move with ~20% of equity at risk on one direction; not evidence of edge
learning_scoreboard: empty (no closed trades); /review prompt generated 2026-10-01 15:10Z shows "No closed trades yet"
```

## 7. Operator reading -> ideas (docs/STRATEGY_JOURNAL.md, docs/LEARNING_RESOURCES.md)

```yaml
sources: [Reddit r/FuturesTrading MTF thread, Investopedia MTF article, 77-min TA video, research notes (Moskowitz-Ooi-Pedersen 2012 TSMOM; Kaufman ER; USDJPY carry; Aronson data-mining bias; ASIC 2021-22: 32% retail CFD clients profitable, 19% of most active), 3 PDFs (fuzzy-logic MT5 robot arXiv 2507.06383: 6 months EURUSD only; RL MQL4 bot: 1-week demo only; MLP thesis: 53.5% accuracy, lost to buy-and-hold), operator chart screenshots Sep 2026]
ideas_status:
  J1-a daily trend must agree with H4: untested (strongest recurring theme, 3/3 sources)
  J1-b avoid entries near prior-week high/low: untested
  J1-c timeframe agreement as size not filter: untested
  J1-d news blackout: untested (needs historical economic calendar)
  J1-e other timeframe pairs: untested
  J2-a weekly/daily swing stack: untested
  J2-b momentum-turn exit (MACD/KST): untested
  J3-a entry trigger candle: untested
  J3-b ATR-padded stop (+1 ATR): untested
  J3-c structural target (prior swing): untested
  J3-d structure-based trend (HH/HL): untested
  J3-e break-and-retest: untested
  J3-f 20-MA trailing exit: untested
  J4-a slow time-series momentum (3-12 month, vol-scaled): untested; strongest external evidence
  J4-b USD-JPY rate-differential filter: untested (needs rate data)
  J5-a multi-period oscillator agreement: untested (weak source)
  J5-b random-entry baseline: NOT yet built (needed to judge "better than chance")
  J5-c max-spread check: untested (needs spread history)
  J6-a volatility block off: FAILED prereg3 (but enabled live by operator choice)
  J6-b faster trend detection: FAILED prereg3 (but enabled live by operator choice)
  J6-c trailing exit: passed 2 periods, FAILED holdout (enabled live by operator choice)
  confirm3 (3rd signal entry): FAILED prereg1
  range_mean_reversion: rejected (negative every year, both periods)
```

## 8. Learning loop (built 2026-10-01; src/forex/learning.py, learning_worker.py, telegram_commands.py)

```yaml
purpose: trial-and-error learning from live paper trades with operator approval
per_closed_trade:
  facts: from journal provenance (candidate JSON, risk decision, intent): symbol (suffix stripped), side, setup, H4 regime, style, sessions, volatility bucket (thirds of volatility_context), conviction, entry, initial stop, exit, exit reason, R, P&L
  buckets: [all, pair, setup, regime, style, volatility, session(each), pair|side, pair|regime]
  score_R: total_R / (n + prior), prior=20 (shrinkage toward 0 R); confidence = n/(n+prior)
  ai_postmortem: provider JSON {summary, likely_causes, lesson, category}; facts + MFE/MAE in R from H1 candles; rule-based fallback
  telegram: "Trade review: <pair> <side> WIN/LOSS <R> ... Why ... Lesson ... Score <pair|regime> n, score, confidence"
sizing_feedback:
  buckets with n>=min_trades(10): weighted score s; factor = clamp(1 + 2*s, min_factor 0.25, 1.0); optional skip if s < skip_below_r
  never > 1 (configured risk is ceiling); applied after AI news review; Layer-5 ceiling preserved in execution
strategy_change_channel:
  /review -> bot sends prompt file (instructions, settings, scoreboard, last 20 reviews, JSON schema)
  operator pastes into an LLM; pastes reply back -> parse_patch (fenced or raw JSON with "forex_patch":1)
  StrategyPatch whitelist+bounds: analysis{high_volatility_blocks_trend, trend_efficiency_window 3-40|null, trend_threshold 0.3-0.9, setup_score_threshold 0.2-0.9, swing_trend_threshold 0.3-0.95, allowed_setups}, exits{target 1.5-20|null, atr_trailing 1-6|null}, risk{risk_percent_per_trade 0.25-5}, learning{...}, disabled_pairs, research_requests (text only, not applied)
  -> PENDING change set #N with human-readable diff -> /approve N writes data/<paper>.strategy-overlay.json -> runtime hot-reloads within one cycle, rebuilds risk policy/execution, announces "Strategy updated"; /rollback restores previous overlay
  security: operator chat id only; no code execution; cannot touch execution/credentials/files; invalid overlay keeps settings and alerts
limitations: score needs dozens of trades/bucket (~1-2 months to reach n=10 at 2-3 trades/week); LLM post-mortems are narratives not evidence; buckets overlap (not independent)
```

## 9. Bugs found and fixed during the work (operational facts)

```yaml
- empty first tick after symbol select -> tick rejection + wait_for_tick
- negative quote age with open position -> 5 s future tolerance
- Firestore nested-array InvalidArgument -> firestore_safe wrapper
- fresh risk re-check used minimum objective (biased) -> uses requested objective
- Telegram token visible in httpx INFO logs -> httpx WARNING + redaction filter (token not rotated: operator choice)
- QuickEdit froze console -> disabled by launcher
- stale quote at 17:00 NY rollover failed whole cycle + Telegram spam -> per-pair pause; error only after 900 s silence
- hourly repeat signals stacked 4 positions on one pair -> max_positions_per_pair=1
- broker symbol suffix (.a) vs bucket keys -> normalised
- A$100 account could not place 70-90 pip stops at 2-5% risk -> fresh A$1,000 paper account
```

## 10. Current assessment by this agent (O, with basis)

```yaml
status: no demonstrated edge. Base trend rules ~ +0.03 R/trade after assumed costs on 2 periods (CI includes 0); every refinement either failed pre-registration or the holdout.
live_profile_risk: aggressive profile combines 3 failed/unvalidated changes at 5% risk; expected long-run outcome ~break-even with large variance (drawdowns 30-60% plausible)
what_seems_real (weakly): trend > mean-reversion on these pairs; swing > day; USDJPY trends in carry regimes; profits come from long moves (12% capture in Sep 2026 example)
what_is_noise: parameter tweaks on H1/H4 (efficiency window, vol block, confirmation count)
recommended_next (priority):
  1. J5-b random-entry baseline with identical stops/exits/frequency (quantify "better than chance")
  2. J4-a slow time-series momentum on daily bars from existing H1 data (3/6/12-month lookbacks fixed a priori, vol-targeted sizing, all pairs); pre-register; both periods
  3. J1-a daily-trend alignment filter on existing trend55 (pre-registered)
  4. measure real costs (IC Markets raw spread + commission from MT5 ticks) and model swap for multi-day holds
  5. fresh out-of-sample: untouched pairs (AUDUSD, USDCAD, NZDUSD, USDCHF) via same Dukascopy pipeline; and forward paper with 1% risk for statistical continuity
  6. reduce live risk to 1-2% for learning-phase paper so drawdowns do not end the experiment
open_questions_for_reviewer:
  - Is H1/H4 technical trend-following on majors a viable research direction for a retail operator, or should effort shift to daily/weekly time-series momentum and carry?
  - Is the pre-registration + two-period + holdout protocol adequate, and how should a new holdout be built now the original is consumed?
  - Is the learning-loop design (shrunk bucket scores, size-down only, whitelisted operator-approved patches) statistically sound for trial-and-error, and what minimum sample/decision rules should govern approving changes?
  - Better statistic than avg R/PF for pass/fail (e.g. bootstrap CI of mean R, deflated Sharpe, White's reality check given multiple tests)?
  - Which journal ideas (Section 7) deserve testing first, given the evidence so far?
```
