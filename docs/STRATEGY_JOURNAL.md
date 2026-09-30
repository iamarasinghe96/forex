# Strategy learning journal

Notes from the operator's reading, condensed so they can later become testable rules. Nothing
here changes the bot. An idea only reaches the bot after it is written as a precise rule with a
pass mark decided in advance, and passes on 2012-2018 and 2021-2025 plus a fresh untouched
period (the original final year, 2025-09-28 to 2026-09-28, has already been used).

Evidence levels used below: **opinion** (anecdote, no data), **plausible** (reasoned but untested),
**tested** (we have run it on our data; result noted).

---

## Entry 1 — 2026-09-30 — "Multi timeframe analysis seems to be just arbitrary decisions"

Source: Reddit r/FuturesTrading thread by u/tkb-noble (about 2 years old, 37 comments),
https://www.reddit.com/r/FuturesTrading/comments/1jf8rqf/ . Futures traders, not forex, but
the ideas are generic.

**The question.** Traders are told to check a "higher timeframe" (for example 4-hour or daily)
before trading a lower one, but nobody shows proof for which timeframes, or why 4 hours rather
than 5. If price is "fractal", is the higher timeframe adding anything?

**Main claims from the replies, condensed**

1. *Alignment:* the more timeframes point the same way, the stronger the move. (Several people.
   Opinion.)
2. *Higher-timeframe closes:* a candle closing beyond a swing high/low on a higher timeframe is
   a more credible sign of direction than on a lower one. (Opinion.)
3. *Support/resistance awareness:* don't buy on a small timeframe just below a big-timeframe
   resistance level (or sell just above big support); the higher timeframe shows where those
   levels are. (Plausible; commonly taught.)
4. *Context vs execution:* higher timeframe for direction/context, lower timeframe for the entry
   and a tighter stop. "Same price history at different resolutions." (Common view.)
5. *Why 4h/daily and not 5h/9h:* because most participants, including large institutions, watch
   the standard ones, so levels on them get reacted to (a self-fulfilling effect). (Plausible,
   unproven.)
6. *Zoom out instead:* one commenter found a zoomed-out view of the same timeframe as useful as
   switching timeframe — it just shows longer history with less noise. (Equivalent to a longer
   lookback.)
7. *Scepticism:* exact numbers (4h, Fibonacci ratios) are "numerology"; what matters is what the
   chart shows. One reply: if higher timeframes always win you could only ever buy, since the
   longest trend is up.
8. *Size instead of filter:* one scalper uses alignment only for position size — full size when
   timeframes agree, half when they don't.
9. *Timeframe sets the stop:* the chosen timeframe decides how much noise the stop must survive,
   so stop size and targets must match the timeframe.
10. *News matters:* charts without scheduled events (interest-rate decisions, inflation, jobs
    data) miss the bigger picture; political shocks can reverse trends instantly.
11. *Volume/order flow:* some prefer volume- or tick-based charts over time-based ones. (Not
    available to us: spot forex has no central volume, and our data has none.)

**How this relates to our bot and results**

- The bot already does multi-timeframe analysis: the 4-hour chart decides trend or range, the
  1-hour chart times the entry (claim 4). Its timeframes were chosen by convention, not tested —
  exactly the original poster's criticism.
- Our results support scepticism over folklore: range setups lost in every year; trend setups
  were break-even; waiting for confirmation and trailing stops did not survive fresh data.
- Our data agrees with claim 9 in one way: slower (swing) trades did better than day trades, and
  costs hurt small stops far more.

**Candidate ideas to test later (not yet tested)**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J1-a | Only take a trend trade if the **daily** trend agrees with the 4-hour trend (claim 1). | Add a daily trend label (e.g. price vs 50-day average); compare aligned vs not. | Yes (daily can be built from H1). |
| J1-b | Skip buys that are within a small distance (e.g. 1 ATR) below the prior **week's high**, and sells just above the prior week's low (claims 3, 5). | Measure distance to prior week high/low at entry; compare near vs far. | Yes. |
| J1-c | Use timeframe agreement for **size** (full vs half), not as a yes/no filter (claim 8). | Same trades, two sizing schemes; compare risk-adjusted results. | Yes. |
| J1-d | Avoid new trades in the hours around major scheduled news for the currencies traded (claim 10). | Needs a historical economic calendar (not yet sourced). | No — calendar needed. |
| J1-e | Test other timeframe pairs (daily+4h, 4h+1h, 1h+15m) instead of assuming 4h+1h (original question). | Re-run the same logic on different pairs of timeframes. | Partly (15-minute data would need downloading). |

**My note.** The thread is mostly opinions; nobody shows tested results. That's fine for
generating ideas. The most promising for us are J1-a and J1-b: they are simple, use data we
already have, and add a genuinely new piece of information (the daily and weekly picture) rather
than re-filtering the same signal.

---

## Entry 2 — 2026-09-30 — "Master Trading With Multiple Time Frames" (Investopedia)

Source: Investopedia article by Joey Fundora, updated 12 October 2025, part of its "Guide to
Swing Trading" series. Educational article, reviewed and fact-checked by the publisher; the
worked example is a single stock (Bath & Body Works, BBWI), not forex.

**Main claims, condensed**

1. *Three timeframes, each with a job:* a long one for the **primary trend**, a middle one for the
   **trading signal**, a short one to **refine entry and exit**. (Standard teaching.)
2. *Typical stacks* (roughly 4-6x apart):
   - swing trader: weekly (trend) / daily (signal) / 60-minute (entry)
   - day trader: 60-minute (trend) / 15-minute (signal) / 5-minute (entry)
   - position trader: monthly (trend) / weekly (signal) / daily (entry)
3. *Longer timeframe = more reliable signals;* shorter charts carry more noise and false moves.
   (Plausible. Our data leans the same way: swing trades beat day trades.)
4. *Disagreement is a warning:* when timeframes conflict, pause or reassess the trade.
5. *Worked example (BBWI stock, 2023-2024):* weekly price crosses above its 12-week simple moving
   average -> daily price crosses above its 10-day average and closes above a resistance line ->
   enter on the 4-hour chart when the **KST** momentum indicator crosses up; exit when the KST
   crosses down. Quoted gains of about 27%, 7% and 5% on three trades.
6. *Indicators said to work across timeframes:* moving averages, RSI, MACD, Bollinger Bands,
   Fibonacci retracements, stochastic oscillator.
7. *Risks it admits:* conflicting signals, over-trading, more time, stress and transaction costs.

**Critical notes**

- The example is **one hand-picked stock over a few months, described after the fact**. It shows
  how the method is applied, not that it works: nothing is said about the times the same signals
  lost money (hindsight / cherry-picking). Evidence level: opinion/illustration.
- The swing-trader stack (weekly / daily / 1-hour) is **slower than our bot's** (4-hour / 1-hour).
  That fits our finding that slower trades held up better and are less eaten by costs.
- KST ("Know Sure Thing", Martin Pring) is a momentum indicator built from several smoothed
  rates of change; the article uses its crossovers for both entry and exit.

**Candidate ideas to test later (not yet tested)**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J2-a | **Slower "swing stack":** only buy when price is above its 12-week average (weekly trend), the daily price has just crossed above its 10-day average (signal), then enter on the 1-hour or 4-hour chart; mirror for sells. | Build weekly/daily candles from our hourly data; one trade per pair at a time; 2012-2018 and 2021-2025. Expect few trades, so pool all three pairs. | Yes. |
| J2-b | **Exit on a momentum turn** (e.g. KST or MACD crossing back) instead of a fixed 1.5x target or trailing stop. | Same entries, compare exit rules. | Yes. |
| J2-c | When timeframes disagree, don't trade (claim 4). | Same as J1-a — merged there. | Yes. |

---

## Entry 3 — 2026-09-30 — Full technical-analysis lesson (YouTube video, ~77 minutes, summarised)

Source: a beginner-to-intermediate technical-analysis video (presenter sells a paid "EAP Training
Program", US$697; the operator pasted a detailed summary, not the video). Forex-focused examples
(EUR/NZD, EUR/AUD, AUD/CAD daily charts). The presenter says his examples are cherry-picked.

**Framework, condensed (his order)**

1. *Candles:* open/high/low/close; meaning is the same on every timeframe.
2. *Trend by structure, not indicators:* uptrend = higher highs and higher lows; it stays valid
   until price **closes below the last pullback low** (downtrend: closes above the last pullback
   high). Trade with the trend rather than picking tops and bottoms.
3. *Support/resistance and "break and retest":* broken resistance often becomes support (and the
   reverse). Enter on the pullback to the broken level, not on the breakout itself.
4. *Stops and targets from structure:* stop **beyond** the swing level plus room; target at the
   next opposing level; never aim through a major opposing level (take profit before it or move
   the stop to break-even).
5. *ATR on every trade* to size stops to current volatility:
   - method 1: stop = distance to swing high/low **+ 1 ATR**; target about 2 ATR or next structure;
   - method 2: stop = **2 ATR**, target = **4 ATR** (2:1).
   A fixed 10-pip stop ignores that a daily candle may move 190 pips.
6. *Moving averages:* 20 MA as short-term trend/volatility filter (price above = bullish); 20/50/200
   as "areas of value" that are widely watched — **but never buy just because price touches one**
   (he tried; it did not work). Optional: trail the stop along the 20 MA to catch 3:1 or 4:1 moves.
7. *RSI is momentum, not an automatic signal:* buying below 30 / selling above 70 alone "is not
   viable". Use only as supporting evidence, e.g. bearish divergence (price higher high, RSI lower
   high) at major resistance.
8. *Objective entry triggers (candles):*
   - **38.2 candle**: bullish if the whole body is above the 38.2% level of the candle's range
     measured from its low (a rules-based "hammer"); bearish mirror.
   - **Engulfing**: colour changes and the new body is larger than the previous body.
   - **Close-above / close-below**: close beyond the previous candle's high / low.
9. *Chart patterns (10-50 candles):* double bottom/top with an objective "termination zone"
   (second test must reach, but not close beyond, the first bottom's body-to-wick zone), then
   neckline break, pullback to the neckline, first candle in the trade direction = entry.
10. *Higher-timeframe alignment:* take a 1-hour double bottom only if the **daily** is in an
    uptrend (and the reverse for tops).
11. *Breakout patterns:* flags in strong trends (above the 20 MA); flat resistance with rising
    lows (and the bearish mirror) - enter on the retest of the broken level, accepting that some
    moves leave without you.
12. *Core rule:* **stack evidence** - trend + structure + area of value + entry trigger +
    ATR-sized stop + structural target. Any single pattern or indicator alone is not an edge.
13. *Beyond charts:* risk management and trading psychology are separate essentials. Advice:
    combine concepts into explicit rules, **backtest**, then demo-trade about **three profitable
    months** before going live. (His "ahead of 95% of traders" claim is unsupported.)

**How this relates to our bot and results**

- Our bot already matches much of this: trend on the higher timeframe, 20/50/200 averages, entry on
  a pullback toward the 20 average, stop at the recent swing low/high.
- What it lacks, per this framework: (a) an explicit **entry trigger candle** ("wait for buying
  pressure" at the pullback), (b) **ATR room beyond the swing** in the stop (ours has none),
  (c) **targets at the next structure** instead of a fixed 1.5x, (d) **daily-trend alignment**,
  (e) trend defined by **swing structure** (higher highs/lows) rather than moving-average maths.
- Consistent with our data: RSI/"overbought-oversold" mean-reversion alone lost money (our range
  setups lost in every year); he independently says the same.
- Caution: every added filter is another knob. Stacking five conditions can make any past chart
  look perfect (overfitting) and leaves few trades to judge. We should test a **small, fixed**
  combination written down in advance, not search for the best-looking stack.

**Candidate ideas to test later (not yet tested)**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J3-a | **Entry trigger:** after a trend pullback, only enter once a bullish 38.2, engulfing or close-above candle appears (mirror for sells). | Add candle-trigger check at the entry bar; compare with entering without a trigger. | Yes. |
| J3-b | **ATR-padded stop:** stop = swing low/high **+ 1 ATR** (ours has no padding); or method 2: stop 2 ATR / target 4 ATR. | Same entries, alternative stop/target rules. | Yes. |
| J3-c | **Structural target:** target the previous swing high (buys) / low (sells); skip trades where that level gives less than 1.5:1. | Needs swing-level detection (codeable from our data). | Yes. |
| J3-d | **Structure-based trend:** trend = higher highs/lows, invalid on a close beyond the last pullback extreme; replaces the moving-average trend score. | Swing detection with an ATR threshold. | Yes. |
| J3-e | **Break-and-retest continuation:** buy the first pullback into the most recently broken swing high, with a J3-a trigger. | Most complex; after J3-a to J3-d. | Yes. |
| J3-f | **20-MA trailing stop** instead of a fixed target. (Our 3x ATR trail failed the final year; this is a different trail.) | Same entries, exit on close back through the 20 MA. | Yes. |

---

## Entry 4 — 2026-09-30 — Research notes on the bot's building blocks

Web research on the techniques the bot uses (full reading list: docs/LEARNING_RESOURCES.md).

1. **Trend following has real academic support - on slower horizons.** Moskowitz, Ooi and Pedersen
   (Journal of Financial Economics, 2012) found returns persisting over **1 to 12 months** across 58
   futures markets including currencies, partly reversing later. Our bot trades a 1-hour/4-hour
   horizon with 1.5x targets - far shorter than the horizon where the evidence is strongest.
   Supports testing slower versions (J2-a, daily/weekly trend). Evidence level: tested (academic).
2. **Kaufman's Efficiency Ratio** = net price change over N bars divided by the sum of bar-to-bar
   moves (1 = straight line, near 0 = chop). Our bot's "directional efficiency" is the same idea,
   so its trend/range labelling rests on a well-known measure.
3. **USDJPY and the carry trade.** USDJPY tends to trend while US rates sit well above Japanese
   rates (investors earn the gap by holding dollars), and can fall sharply when that trade unwinds.
   Plausible explanation for USDJPY leading in 2012-2015 and 2021-2024 and failing in the final
   year; interest-rate differentials are an input the bot does not use. Evidence level: plausible.
4. **Data-mining bias is the normal failure mode.** Aronson's *Evidence-Based Technical Analysis*
   reports that profitable-looking backtested rules were, in the cases it examined, explained by
   data-mining bias. Consistent with our failed candidates; keep pre-registering.
5. **Retail reality in Australia.** ASIC found only 32% of retail CFD clients profitable after fees
   (19% of the most active). Costs and over-trading are the main killers - consistent with our
   finding that frequent, small-stop trading lost most.

**Candidate ideas added**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J4-a | **Slow trend following:** hold the direction of the past 3-12 month price change, exiting when it flips (classic time-series momentum), with volatility-based position size. | Daily bars built from our hourly data; very few trades per year, so results need all three pairs and both periods. | Yes. |
| J4-b | **Rate-differential filter** for USDJPY: only trade in the direction the US-Japan interest-rate gap favours. | Needs historical interest-rate data (not yet sourced). | No. |

---

## Entry 5 — 2026-09-30 — Three papers on trading bots (uploaded PDFs)

Three documents the operator uploaded. All three build an automated trading system; none shows an
edge that would survive our testing standard. Their most useful content is what went wrong.

### 5.1 "Forex Trading Robot Using Fuzzy Logic" (Shabani, Nasiri, Nafardi; arXiv 2507.06383, 2025)

**What they did.** An MT5 robot for EUR/USD. RSI, CCI and Stochastic are each computed at three
settings (for example RSI 9/14/21), and a "fuzzy logic" system turns them into buy/sell/hold votes
(36 hand-written rules). A trade happens only when most of the votes agree.

**Claimed result.** Tested on **6 months** (first half of 2022) with $10,000. Profit factor 2.35 and
16.2% maximum drawdown for the fuzzy robot; the single-indicator robots were far worse: RSI profit
factor 1.06 (drawdown 49.4%), CCI 0.99 (99.7%), Stochastic 0.95 (87.1%).

**Assessment.** Evidence level: **weak**. One pair, one six-month period, no out-of-sample test,
trading costs not clearly stated, thresholds and rules set by hand (easy to fit to the period
shown). The more useful finding is the baseline: **plain overbought/oversold oscillator trading
lost money or nearly so**, the same as our range-reversion results.

### 5.2 "Automated Forex Trading Bot Using MQL4: A Reinforcement Learning-based Approach" (Markus, Raphael, Mazadu; ACIS 13(3), 2025)

**What they did.** Describes reinforcement-learning agents (PPO, DQN, SAC) for EUR/USD in MT4, and a
walk-forward test on 2013-2023 data.

**Claimed result.** No walk-forward results are actually reported. The only numbers come from a
**one-week demo**: 62% win rate, profit factor 1.45, 4.2% drawdown, with 4 example trades listed.
The paper also calls the system "high-frequency", which does not match what it describes.

**Assessment.** Evidence level: **opinion** (one week is noise). Worth keeping only as a checklist
of safety features a live bot should have - maximum spread, news blackout, trading-session filter,
drawdown limit, logging, running on a VPS. Our bot already has most of these; the gaps are a
**news blackout** (J1-d) and a **maximum-spread check** (our paper broker assumes fixed costs).

Lead worth following: it cites **Menkhoff, Sarno, Schmeling and Schrimpf, "Currency Momentum
Strategies" (Journal of Financial Economics, 2012)** - a proper academic study. As generally
summarised, it finds momentum profits across many currencies over 1-12 month horizons, but mostly
in smaller, costlier currencies and much weaker in major pairs. Same message as Entry 4: momentum
is a slow-horizon effect, and costs decide whether it survives. (Not yet read in full.)

### 5.3 "Designing an automated trading bot for strategic order execution" (Antelo Cortegana; Bachelor thesis, HEG Geneva, 2024)

**What they did.** Stocks, not forex (Amazon, daily bars). A small neural network (multilayer
perceptron) predicts whether tomorrow closes higher, using OHLC, volume, EMA, RSI, MACD and VWAP
plus the previous 14 days. Tuned with time-ordered cross-validation. Trades use a 5% take-profit
and 2% stop, long only, with 1% slippage and $5 commissions.

**Result (honestly reported).** Best validation accuracy **53.5%** (barely above a coin flip); the
model mostly predicted "up". Simulated 1 Jan - 31 Aug 2024, starting with $10,000:

| Strategy | End value | Profit factor |
|---|---|---|
| Buy and hold | $10,376 | 1.08 |
| Indicator rules (RSI/MACD/EMA/VWAP) | $9,013 | 0.84 |
| Neural network | $8,861 | 0.23 |
| Random buy/sell | $7,516 | 0.39 |

**Assessment.** Evidence level: **tested, negative**. The author concludes the model is not good
enough to use. Useful lessons: (1) predicting next-day direction from indicators is close to
guessing; (2) "doing nothing" (buy and hold) beat every active strategy; (3) frequent trading
with costs (the random strategy) loses fastest; (4) its method - time-ordered splits, costs
included, simple baselines - is the right way to test, and the same way we test.

### What the three papers tell us together

1. **Plain indicator signals don't pay.** Every paper's simple indicator baseline lost or roughly
   broke even (5.1 RSI/CCI/Stochastic, 5.3 RSI/MACD/EMA/VWAP). Matches our range setups losing in
   every year.
2. **More complex models (fuzzy logic, neural networks, reinforcement learning) did not fix this**
   in any properly tested case. The only strong-looking results (5.1, 5.2) are from very short
   tests with no out-of-sample check.
3. **Always compare to a simple baseline** ("do nothing", buy and hold, or random entries with the
   same stops). We do not currently report one.

**Candidate ideas added**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J5-a | **Indicator agreement:** only take a trend trade when the momentum oscillator agrees at several settings (for example RSI 9, 14 and 21 all above 50 for a buy). | Same trend-only exports; add the filter; compare trades kept vs removed. Low priority - weak source. | Yes. |
| J5-b | **Random-entry baseline:** same stops, targets, pairs and trade count, but random direction/timing. Our strategy must beat it to count as an edge. | Add to the research scripts as a reference line on every future test. | Yes. |
| J5-c | **Maximum-spread check:** skip a trade if the live spread is wider than a limit (for example 2x normal). | Needs spread history (Dukascopy bid/ask ticks) for a backtest; easy to add to the live bot as a safety rule. | Partly. |

---

## Entry 6 — 2026-10-01 — Chart review: the US-dollar trend of 9-30 Sep 2026

Source: the operator's MT5 H1 screenshots (EURUSD, GBPUSD, USDJPY, USDCHF), replayed through the
bot's own analysis code on the candles stored on the VPS (`scripts/replay_decisions.py`, read-only).
The live bot had only been running since 30 Sep, so it missed the move simply by not being on.

**What the market did.** A broad US-dollar rally: EURUSD about -276 pips, GBPUSD about -248,
USDJPY about +414 (to 158.4, then -154 on 25 Sep and sideways), USDCHF about +250 (not traded).

**What the bot would have decided (hourly replay)**

| Pair | First trend idea | What held it back |
|---|---|---|
| EURUSD | 16 Sep, two days in | 107 hours blocked by the HIGH_VOLATILITY rule while the trend measure was strong, including the start (14-15 Sep). |
| GBPUSD | 17 Sep | 60 hours blocked the same way; the -89 pip day (16 Sep) was labelled TRANSITION. |
| USDJPY | 18 Sep, after about +270 pips | 14-17 Sep labelled RANGE despite +76 to +100 pips a day - the old range setup would have sold into this rally. |

Choppy periods (GBPUSD and USDJPY from 28 Sep) were correctly labelled RANGE/TRANSITION: no trades.

**Rough simulated result** (one position per pair, entry at the hour's close, structural stop,
1.5R target, stop to entry at +1R, research cost assumptions; risk checks and news review not
applied):

| Pair | Closed trades | Net |
|---|---|---|
| EURUSD | -1.05 R, +1.45 R, +1.49 R (the last took 13 days) + one still open | +132 pips, +1.89 R |
| GBPUSD | +1.48 R + one still open since 17 Sep | +74 pips, +1.48 R |
| USDJPY | -1.01 R (short on 9 Sep, just before the rally), -0.01 R (long reached +1R, stopped at entry in the 25 Sep drop) | -89 pips, -1.02 R |
| **Total** | 6 closed | **+117 pips, +2.35 R** |

At the bot's 2-5% risk per trade that is roughly +5% to +12% of the account for three weeks.
The market moved about 940 pips across the three pairs; the rules captured about 12% of it.

**Assessment.** Evidence level: **anecdote** (one favourable month). It shows the trend rules do
what they are designed to do in a clean trend, and where the gains leak: late detection, the
volatility block, and a 1.5R cap on moves that ran 3-5 times further. It does not change the
13-year finding that such months are cancelled out by losing ones in choppy markets. The
breakeven rule helped here: it turned the USDJPY long into a scratch instead of a -1R loss.

**Candidate ideas added**

| # | Plain-language rule | Test sketch | Data we have? |
|---|---|---|---|
| J6-a | **Don't let the volatility block stop a strong trend:** when the H4 trend measure is above its threshold, label the market as a trend even if volatility is in the top 10%. | Same exports and costs, 2012-2018 and 2021-2025; compare trades added by the change on their own. | Yes. |
| J6-b | **Faster trend detection:** shorter lookback for the trend measure, so trends are recognised in about 1-2 days instead of about 3. | Same; expect more false starts in chop - the test is whether net R improves. | Yes. |
| J6-c | **Let winners run further** once a trade is past +1R (bigger target or trailing stop). | The 3x ATR trail passed two periods but failed the final year; retest only combined with J6-a/J6-b, pre-registered. | Yes. |

---

## Recurring themes across entries

| Theme | Sources | Status |
|---|---|---|
| Higher-timeframe trend agreement (daily/weekly must agree before trading) | Entry 1 (claims 1, 3), Entry 2 (claims 1, 4), Entry 3 (claim 10) | Untested. Strongest recurring idea (3 of 3 sources): J1-a / J2-a. |
| Slower timeframes are more reliable, less noise, cheaper | Entry 1 (claim 9), Entry 2 (claim 3), Entry 4 (1, 5), Entry 5 (Menkhoff lead) | Partly supported by our data (swing > day trades) and by academic trend-following research (1-12 month horizons). |
| Higher-timeframe support/resistance levels matter | Entry 1 (claims 3, 5), Entry 2 (example), Entry 3 (claims 3, 4) | Untested: J1-b, J3-c, J3-e. |
| News/scheduled events can override charts | Entry 1 (claim 10), Entry 5 (5.2 news blackout) | Untested: J1-d (needs an economic calendar). |
| Wait for an entry trigger ("buying pressure") rather than entering on location alone | Entry 2 (KST cross), Entry 3 (claims 8, 12) | Untested: J3-a. |
| Stops sized to volatility (ATR) and placed beyond structure | Entry 3 (claims 4, 5) | Untested: J3-b. Our stops have no ATR padding. |
| Let winners run with a trailing stop | Entry 3 (claim 6), Entry 6 (1.5R cap took ~12% of the move) | 3x ATR trail: passed 2012-2018 and 2021-2025 but FAILED the final year. 20-MA trail untested (J3-f). |
| Overbought/oversold mean reversion alone does not work | Entry 3 (claim 7), Entry 5 (5.1, 5.3 baselines), Entry 6 (USDJPY rally labelled RANGE) | Agrees with our data: range setups lost in every year. |
| Complex models (fuzzy logic, neural networks, reinforcement learning) don't rescue weak signals | Entry 5 (5.1-5.3) | No properly tested case showed an edge; the neural network lost to buy and hold. Not planned. |
| Trend detection is late; the volatility block removes strong trend hours | Entry 6 | Seen in Sep 2026 replay; untested: J6-a, J6-b. |
| Beat a simple baseline before calling it an edge | Entry 5 (5.3) | Not yet reported in our tests: J5-b. |

## Suggested first test batch (to agree before running)

Test a small number of ideas, each written down in advance, so we don't "search until something
looks good": (1) **daily-trend alignment** (J1-a) - backed by all three sources; (2) **entry
trigger candle** (J3-a); (3) **ATR-padded stop** (J3-b). Each on 2012-2018 and 2021-2025, one
position per pair, after costs; a fresh untouched period is needed for any final check.
Report a random-entry baseline (J5-b) next to each result, so "better than chance" is visible.
