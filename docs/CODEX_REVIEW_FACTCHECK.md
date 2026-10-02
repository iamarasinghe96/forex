# Fact-check of the Codex review (2026-10-03)

Inputs: Codex chat plan, `ALPHALEDGER_REVIEW.md`, `RESEARCH_TEST_SPEC.md`, draft PR #19.
Method: each code claim checked against the source on branch `claude/determined-thompson-f4ewei`;
research claims checked against BUILD_PROGRESS.md; AlphaLedger figures could not be re-checked
(this session's network policy blocks app.alphaledger.ai and the site needs the operator's login).

## Verdicts

| # | Codex claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Live ATR trailing never activates (ATR cached under EURUSD, positions use EURUSD.a) | **TRUE** | runtime.py caches `trailing_atr[symbol.upper()]`; paper.py looks up `p.symbol` = broker name (`EURUSD.a`). Live trades get break-even only. PR #19 fixes it correctly; merging tightens stops on open trades. |
| 2 | Short-trade excursions in trade reviews are wrong | **TRUE** | learning.py `price_path` used max(low)/min(high) for shorts. Affects AI review text only, not trading. Fixed in PR #19. |
| 3 | ATR not refreshed for held pairs when entries are paused, and after restart | **TRUE (minor)** | ATR updates only inside the hourly analysis loop (skipped for paused/quiet pairs; cache empty after restart until the next hour). |
| 4 | Historical selection unreliable: trades open at window boundaries are dropped, letting later trades in | **PARTLY TRUE** | backtest.py marks trades lacking 120 future bars `WINDOW_BOUNDARY_CENSORED` and exports only completed trades; `one_at_a_time` then runs on that CSV. Real, but affects only trades opened within ~5 days of each window end (8 inner boundaries per pair in 2021-2025, 1 end in 2012-2018). "Unreliable" is overstated until measured; `scripts/causal_replay.py` measures it. |
| 5 | Research and live exits differ | **TRUE** | Research: 120-bar time exit (480 in prereg 2), trailing uses entry ATR. Live: no time exit, latest ATR, 10R target. Results do not transfer one-to-one. |
| 6 | Costs/financing/broker H4 alignment unverified | **TRUE** (already recorded) | Bid-only data; costs assumed 0.9/1.2/1.0 pips; no swap; fixed UTC H4 (BUILD_PROGRESS "known limitations"). |
| 7 | Random-entry controls never run | **TRUE** | Was idea J5-b; now built: `scripts/causal_replay.py`. |
| 8 | Slow-momentum benchmark never run | **TRUE** | Was idea J4-a; now built per spec section 3: `scripts/slow_momentum.py`. |
| 9 | News blackout can only be tested with a timestamped historical calendar | **TRUE** | No calendar data in the project. A proxy (e.g. NFP first-Friday rule) would be approximate. |
| 10 | AlphaLedger top accounts add to losing positions and close baskets; high win rate does not prove edge | **PLAUSIBLE, unverified here** | Consistent with grid/averaging systems; the 72%-win-rate comparator with PF 0.79 illustrates it. Figures are site-displayed, not audited (Codex says so). |

## Gaps in the Codex review (not wrong, but missing)

1. **Nothing new was tested on Dukascopy history.** The review is a plan plus two correct bug finds.
2. **Statistical power was not stated.** Per-trade R has SD ~1.2. Detecting the measured edge
   (~+0.03 R/trade) at 2 standard errors needs n = (2 x 1.2 / 0.03)^2 ~ 6,400 trades: about 60
   years at 2 trades/week. A 52-week forward run cannot confirm or reject it. Realistic routes are
   a larger per-trade edge, many more independent bets (more pairs/markets), or slower strategies
   judged on return series rather than trade counts.
3. **The slow-momentum spec uses three USD-correlated pairs.** Published time-series momentum
   results rely on diversification across many markets; three pairs give few independent bets.
   A pre-registered extension to more Dukascopy pairs (AUDUSD, USDCAD, USDCHF, NZDUSD, EURJPY,
   GBPJPY...) should be part of the test.
4. **The four open trades** were opened by the stacking defect (fixed in 0a4ac35). PR #19's
   deployment decision applies to them; restoring trailing will lock in part of their profit.

## New tools (research only; bot unchanged)

- `scripts/causal_replay.py`: one chronological stream per pair, no window boundaries; trades
  occupy their pair until exit; trades still open at the end are marked separately; exits match
  the live engine (latest ATR, optional time exit); 1,000 matched random-entry controls (same
  H4 direction, stops, exits, costs, entry rate by pair x UTC session; seeds 2026100200+).
- `scripts/slow_momentum.py`: spec section 3 (3/6/12-month sign average, 10% vol target split
  across pairs, |w| cap 1, monthly rebalance, cost and financing stress), compared with flat and
  constant-long; block-bootstrap CI (1/3/6-month blocks).

Both verified on synthetic data only. Real results need the Dukascopy databases (operator PC) or
network access to datafeed.dukascopy.com from this session.

## Update 2026-10-03: Codex audit files and AlphaLedger data checked

**INDEPENDENT_TRADE_AUDIT.json / EXTERNAL_REVIEW.md** - all nine recalculated variants match
BUILD_PROGRESS exactly (trades, mean net R, PF): baseline 475/+0.028/1.063 and 361/+0.040/1.086;
trailing 418/+0.013 and 297/+0.079; holdout 56/-0.303/0.513; J6-a 511/+0.037 and 395/+0.019;
J6-b 713/-0.003 and 536/+0.091. New facts from it that we accept:
- Measured per-trade SD is 1.04-1.08 R (we had assumed 1.2). Power estimate becomes
  n = (2 x 1.06 / 0.03)^2 ~ 5,000 trades to detect +0.03 R at 2 SE.
- Doubling assumed costs turns the 2012-2018 trailing result negative (-0.002 R); baseline stays
  slightly positive (+0.014 / +0.024 R).
- Block-bootstrap 95% intervals include zero for every variant except the holdout (entirely
  negative) and J6-b 2021-2025 (positive, but J6-b lost in 2012-2018).
- "Net mean R > 0" and "PF > 1" are the same condition on the same trades: our pass rule's two
  criteria were redundant, not two confirmations. Correct.
- Backtests fill stops at the stop price even through gaps (optimistic); causal_replay.py now fills
  at the gapped bar's open.
- The learning score's n/(n+20) is an evidence weight, not statistical confidence; renamed in the
  bot's messages. Scores also pool trades from different settings (open item: tag by version).

**ALPHALEDGER_OBSERVATIONS.json** (summaries; the raw 100-row tables were not uploaded):
- Gold Reaper 28 Aug basket re-computed: 9 EURUSD shorts, 4.13 lots, +$48.81, displayed P&L equals
  price change x 100,000 x lots to the cent. Verified.
- Not computed by Codex: the first five shorts (1.24 lots, average entry 1.15453) were still open
  when later shorts were opened at 1.16580, so the basket was at least **-$1,398 floating** at that
  price - about 29 times its final +$48.81 profit. The true worst point is unknown (needs EURUSD
  highs 14-28 Aug 2026; available in the Dukascopy data).
- Leaderboard (157 rows, two page snapshots): 119 positive / 38 negative returns; median return
  +14.8% with median max drawdown 17.5%, over unstated and differing periods. Highest returns are
  gold/crypto systems with 25-57% drawdowns. Several providers run multiple listed strategies
  (e.g. Gold_Xv2, Mateen, numbered "Alex" accounts), so rows are not independent. 11 rows show
  >20% return with <10% drawdown, but no entry rules, cashflows or equity paths are available.
- Conclusion unchanged: the inspected winners show averaging into losing positions and basket
  exits; high win rates coexist with large hidden floating losses. Nothing here is a copyable,
  testable entry rule.

## Update 2026-10-03: research results on real Dukascopy data

Run on the operator PC with `scripts/causal_replay.py` and `scripts/slow_momentum.py`.

**Causal replay with 1,000 matched random-entry controls (Codex items 4 and 7)**

| Period | Strategy trades / mean R / PF / total | Controls mean R/trade (total, SD) | Share of controls >= strategy (total / mean) |
|---|---|---|---|
| 2012-2018 | 427 / +0.0263 / 1.054 / +11.23 | -0.0687 (-34.4, 25.4) | 0.041 / 0.034 |
| 2021-2025 | 322 / +0.0417 / 1.084 / +13.42 | -0.048 (-18.6, 22.2) | 0.070 / 0.059 |

| Pair | 2012-2018 total R | 2021-2025 total R |
|---|---|---|
| USDJPY | +23.73 | +34.24 |
| EURUSD | +4.51 | -12.79 |
| GBPUSD | -17.01 | -8.04 |

Years 2012-2018 (mean R): +0.122, +0.059, +0.017, +0.293, -0.130, -0.075, -0.032.
Years 2021-2025: -0.134, +0.200, +0.196, +0.060, -0.234.

Verdict:
1. **The entry timing is better than chance.** Random entries in the same H4 direction with the
   same stops, exits, costs and entry rate lose 0.05-0.07 R/trade (roughly the trading cost). The
   strategy's entries add about +0.09 R/trade over them in both periods. Only 2012-2018 is clean
   evidence (the rules were designed on 2021-2025): about a 4% chance under random timing.
   Combined with 2021-2025 (Fisher), about 2%.
2. **The net edge is still small.** +0.03 to +0.04 R/trade, PF 1.05-1.08. This matches every earlier
   export. It does not clear the ~5,000-trade power bar and falls to about zero under doubled costs.
   The edge is real-looking timing on top of a cost drag, not a large edge.
3. **It is concentrated.** USDJPY is positive in both periods, GBPUSD negative in both, and EURUSD
   mixed. The edge also comes and goes by year (2016-2018, 2021 and 2025 negative). Removing GBPUSD
   would be chosen after seeing these numbers. Any pair rule must be pre-registered and tested on
   pairs not yet examined (AUDUSD, USDCAD, USDCHF, NZDUSD, EURJPY, GBPJPY).
4. **Codex claim 4 measured: negligible.** Causal vs walk-forward export: +0.026 vs +0.028
   (2012-2018) and +0.042 vs +0.040 (2021-2025). Boundary censoring did not inflate results.

**Slow time-series momentum (Codex item 8), EURUSD/GBPUSD/USDJPY, 2013-04 to 2026-09**
+0.70%/yr, Sharpe 0.165, max drawdown 20%; constant-long +0.66%/yr. Paired monthly difference
+0.006% (95% CI -0.31 to +0.34) -> **FAIL / inconclusive**. Under cost and financing stress -0.78%/yr.
USDJPY dominates and 2022 alone contributed +11.2%. Three USD-correlated pairs are too few
independent bets (gap 3 above); not adopted.
