# Loss review pack: USDJPY buy, 7 Oct 2026 (-1.04 R, A$-53.70)

This file has three parts:

- **Part A** is the shared brief. Paste it into both tools.
- **Part B** is for Codex, which has the repository and the research databases.
- **Part C** is for ChatGPT (Deep Research), which has the web.

Paste it as it is. No extra data is needed.

---

## Part A: shared brief (paste into both)

I run an automated forex bot on paper money: an A$1,000 simulated account using IC Markets MT5 demo prices. Real-money trading is off. One trade lost 1.04 R (A$53.70) and I want to know whether anything specific caused it, beyond ordinary bad luck. For example:

- a recurring time-of-day pattern, such as a "usual morning move", the Tokyo fix, or the London open;
- a news event;
- a weakness in how the bot picks entries or places stops.

Please separate three kinds of claim:

1. what the data shows;
2. what is plausible but untested;
3. what one trade cannot tell us.

### The bot's rules (settings version 4977cb76)

**Pairs:** EURUSD, GBPUSD, USDJPY.

**Decisions:**
- The bot decides once an hour, at each H1 (one-hour) bar close.
- H4 (four-hour) bars are built from H1 bars on fixed UTC hours 0/4/8/12/16/20.

**Entry ("trend continuation breakout/pullback"):**
- The H4 trend score must pass. It is built from the EMA 20/50 gap and slope, MACD, and directional efficiency over a 10-bar window.
- An H1 setup score must also pass. Its components are:
  - `h1_momentum` (MACD histogram);
  - `structure` (position in the 20-hour range);
  - `pullback_coherence` (distance from the fast EMA);
  - `h4_trend`.
- There is no check for consolidation or for a confirmed breakout.

**Stop:**
- Buys: the lowest low of the last 20 closed H1 bars.
- Sells: the highest high of the last 20 closed H1 bars.
- No buffer is added beyond that level.

**Exits:**
- Break-even once the trade reaches +1 R.
- Then a trailing stop at 3 × H1 ATR(14).
- Target at 10 R, which is rarely hit.

**Risk:**
- 5% of the balance per trade, capped by available margin at 30:1.
- One position per pair.

**Paper fills:**
- The bot checks quotes every few seconds.
- A buy closes at the first bid at or below the stop.
- Commission and swap are not modelled; the spread is real.

### What earlier research found

Earlier tests used Dukascopy H1 data from 2012–2026 and compared the bot's trades with matched random entries in the same trend regime, with the same stop width, session and exits.

- **The entry rules add no skill over random entries in the same H4 trend.** Pre-registration 5, run R-B, 2021–2025: 728 trades, +0.055 R per trade after costs. The matched random entries did better, at +0.087 R.
- **The small profit is H4 trend exposure, concentrated in USDJPY longs.** Excluding JPY pairs, the result is -0.010 R per trade.
- **Most trades end near -1 R.** Profit comes from a few long trailing winners.
- **Textbook swing-structure rules showed no edge.** Pre-registration 4 failed.

### The losing trade (from the bot's own records)

```
TRADE fx-091f156bb2e3e92e4af8ac36
  USDJPY BUY 0.11 lots | opened 2026-10-07T04:00:09 UTC (Wed 07 Oct 15:00 Sydney) | closed 2026-10-07T08:15:01 UTC (Wed 07 Oct 19:15 Sydney) by STOP
  entry 158.427 | first stop 157.913 (51.4 pips) | exit 157.89 | target 163.5560
  result -1.04 R = A$-53.70; balance A$1164.23 -> A$1110.53
  planned loss at the stop A$51.18 = 4.4% of the balance
  exit was 2.3 pips past the stop

WHY IT ENTERED
  style DAY | setup TREND_CONTINUATION_BREAKOUT_PULLBACK | H4 trend strength 0.673 (swing threshold 0.68)
  component h1_momentum: 0.23
  component h4_trend: 0.67
  component pullback_coherence: 0.46
  component structure: 0.64
  H1 range position 0.82 (1 = top of the last 20 hours), 20-hour low 157.91, H1 ATR 0.115 (11.5 pips)
  spread at entry 0.1 pips = 0.00 R

STOP SIZE
  stop = 4.46 x H1 ATR (51.4 pips)

HOUR BY HOUR (UTC hour start; R = distance from entry in units of the first stop, 1 R = 51.4 pips)
  UTC              Sydney            high R   low R  close R  note
  2026-10-06T22:00 Wed 07 Oct 09:00   -0.47   -0.69    -0.49  before
  2026-10-06T23:00 Wed 07 Oct 10:00   -0.20   -0.49    -0.23  before
  2026-10-07T00:00 Wed 07 Oct 11:00   +0.09   -0.22    -0.01  before
  2026-10-07T01:00 Wed 07 Oct 12:00   +0.16   -0.24    -0.09  before
  2026-10-07T02:00 Wed 07 Oct 13:00   +0.08   -0.22    +0.02  before
  2026-10-07T03:00 Wed 07 Oct 14:00   +0.07   -0.15    -0.00  before
  2026-10-07T04:00 Wed 07 Oct 15:00   +0.07   -0.07    -0.00  <- ENTRY
  2026-10-07T05:00 Wed 07 Oct 16:00   +0.05   -0.17    -0.14
  2026-10-07T06:00 Wed 07 Oct 17:00   -0.05   -0.36    -0.24
  2026-10-07T07:00 Wed 07 Oct 18:00   -0.06   -0.76    -0.62
  2026-10-07T08:00 Wed 07 Oct 19:00   -0.47   -1.12    -0.48  <- STOP HIT
  2026-10-07T09:00 Wed 07 Oct 20:00   -0.34   -0.53    -0.35  after exit
```

### Data we do not have

- The bot's records shown above cover only 6 hours before entry and 1 hour after the exit.
- The stop level (157.91, the 20-hour low) was set on 6 October between about 08:00 and 21:00 UTC, outside that window.
- If you can see public USDJPY prices for 6–8 October 2026, use them for:
  - when that low formed;
  - whether price recovered after the stop-out.
- Say which source you used.

### Session clock for that day

| Event | UTC | Japan (JST) | London (BST) |
|---|---|---|---|
| NY close / daily rollover (spreads widen, thin market) | 21:00 Oct 6 | 06:00 | 22:00 |
| Tokyo open | 00:00 | 09:00 | 01:00 |
| Tokyo fix (9:55 JST) | 00:55 | 09:55 | 01:55 |
| **Bot entry** | **04:00** | **13:00** (Tokyo afternoon) | 05:00 |
| Frankfurt open | 06:00 | 15:00 | 07:00 |
| London open | 07:00 | 16:00 | 08:00 |
| **Stop hit** | **08:15** | **17:15** | **09:15** |

7 October 2026 is a Wednesday. It is not a "gotobi" day (the 5th, 10th, 15th, 20th, 25th or 30th, when Japanese importers' dollar buying at the fix is said to be heavier).

### What we already see

- **Sizing and costs were correct.** The stop was wide, not tight: 4.5 × ATR. The spread was negligible. The extra 0.04 R was 2.3 pips of slippage.
- **The bot bought near the top of its 20-hour range** (0.82), after a rally of about 0.7 R since 22:00 UTC. Short-term momentum was weak (0.23). The H4 trend was just below the bot's "persistent swing" threshold.
- **Price fell steadily from about the Frankfurt and London opens.** The stop was hit at 08:15 UTC by a dip about 6 pips past the stop. That hour then closed at -0.48 R, about halfway back.
- **The stop was the plain 20-hour low, with no buffer.** Levels like that are where many traders' stops sit.

### Hypotheses to check (please add others)

1. **London-open reversal.** Moves made during the Asian session often reverse at the Frankfurt/London open (06:00–08:00 UTC). Entries at 03:00–05:00 UTC may be systematically worse.
2. **Buying the top of the Asian range.** Entries with range position above 0.8 may underperform.
3. **Stop at an obvious level gets "run".** A small buffer beyond the 20-hour low (0.25–0.5 × ATR, with a smaller position for the same A$ risk) might avoid stop runs. See Osler's work on stop-loss clustering and price cascades.
4. **Daily rollover low.** If the 20-hour low formed in the thin 21:00–23:00 UTC hours, it may be a poor stop level.
5. **Tokyo fix effect.** USDJPY often rises into the 00:55 UTC fix and gives it back later. The morning rally may have been fix-driven, not trend.
6. **News or official comments.** Something may have moved the yen around 07:00–08:15 UTC: Japanese Ministry of Finance or BoJ comments (USDJPY near 158 is close to past intervention zones), European data, or US yields.
7. **Marginal signal.** A weak H1 momentum score plus an H4 trend just under the threshold may be a low-quality bucket.
8. **Plain variance.** -1 R is the most common outcome for this strategy.

---

## Part B: for Codex (repository and research databases on the PC)

Repository: `C:\Users\Indika\Desktop\forex`, base branch `claude/determined-thompson-f4ewei`.

### Working rules

**Branch and data:**
- Work only on a new branch, `codex/loss-review-usdjpy`, and push only that branch.
- Treat the research databases as read-only.
- Never print or commit `.env`, credentials or tokens.

**What not to touch:**
- Do not change `config.yaml` or anything the live bot runs.
- Live changes need a passed, pre-registered test and the operator's approval.

**Before you look at any results:**
- Write each test's pass/fail rule into `BUILD_PROGRESS.md` as "Pre-registration 6".
- Testing several ideas inflates false positives. Use a Bonferroni-adjusted bar.
- A pass needs all three of the following:
  1. both periods (2012–2018 and 2019–2026) agree;
  2. the result holds at 2× costs;
  3. the result holds excluding JPY.

**How to run the tests:**
- Use `scripts/causal_replay.py`, which has matched controls, net, 2× cost and ex-JPY outputs, and month-block confidence intervals.
- Use the live rules (run R-B settings) rather than writing a new simulator.
- Check data gaps with `scripts/data_coverage.py` and report them.

### Tests

**T1 — Entry hour and session.**
- Measure net R per trade by entry hour in UTC, grouped into four sessions:

  | Session | Hours (UTC) |
  |---|---|
  | Asia | 00–06 |
  | Europe open | 06–09 |
  | Europe/US | 09–16 |
  | Late | 16–24 |

- Report the matched-control gap for each session, so session effects shared by random entries are removed.
- Question: are 03:00–05:00 UTC entries worse than random entries at the same hours?

**T2 — When stops are hit.**
- Find the distribution of stop-hit times by UTC hour. Compare it with what the hourly share of volatility would predict.
- Question: are stops hit disproportionately at 06:00–09:00 UTC on trades entered during the Asian session?

**T3 — Stop buffer.**
- Test the stop at the 20-bar extreme plus 0, 0.25 and 0.5 × H1 ATR, with the position resized so the A$ risk stays the same.
- Report:
  - net R;
  - win rate;
  - average win and loss;
  - the share of stops hit by less than 0.25 × ATR beyond the level ("near-miss stop-outs").

**T4 — Range position at entry.**
- Compare outcomes for range positions 0.5–0.65, 0.65–0.8 and above 0.8, against matched controls.

**T5 — Where the stop level formed.**
- Compare outcomes when the 20-bar extreme formed in 21:00–23:00 UTC against other hours.

**T6 — This trade's bucket.**
- Find historical trades with the same profile:
  - USDJPY long;
  - entry at 03:00–05:00 UTC;
  - range position above 0.75;
  - `h1_momentum` below 0.3.
- Report how many there are, their net R and the controls. Expect a small sample and say so.

### Deliverable

Write `docs/LOSS_REVIEW_USDJPY_RESULTS.md` containing:
- a table per test;
- a plain-English verdict per hypothesis: supported, not supported, or not enough data;
- a recommendation that is either "no change" or a specific pre-registered change for the operator to approve.

Include the exact commands so the results can be reproduced. Then commit and push to `codex/loss-review-usdjpy`.

---

## Part C: for ChatGPT (Deep Research, web)

Use the shared brief in Part A, then:

1. **What moved USDJPY on 7 October 2026, especially 06:00–08:30 UTC?** Look for:
   - Japanese officials' comments (Ministry of Finance or BoJ) on the yen or intervention;
   - BoJ or Fed speakers;
   - European data releases;
   - moves in US Treasury yields or the US dollar index.

   Also check what happened on 6 October 2026, when the 20-hour low near 157.91 was formed. Give dated sources. If you can't find a cause, say so plainly rather than guessing.
2. **Intraday seasonality in USDJPY, from peer-reviewed or central-bank sources:**
   - Tokyo fix behaviour, including the gotobi effect;
   - volatility and direction changes at the Frankfurt/London open;
   - whether moves made in Asian hours tend to reverse in Europe.

   Starting points include Andersen & Bollerslev (1998) on intraday FX volatility, and Ito & Hashimoto (2006) on intraday seasonality on EBS. For each source, give its sample period and whether the effect still held in later data.
3. **Stop-loss clustering and stop runs.** Look at Osler (2003, 2005) on order clustering at round numbers and recent extremes, and on price cascades. Should a trend-following bot put its stop exactly at the recent extreme, or beyond it? What evidence exists on buffer size?
4. **Yen-specific risk around 158–160.** Cover past intervention episodes and their timing, and whether long-USDJPY trend trades near those levels carry extra event risk that a fixed stop cannot handle.
5. **Your conclusion:** rank the likely causes of this particular loss and say which are testable with hourly data. Give the falsifiable tests that would confirm or rule each one out. Keep "evidence", "plausible" and "unknowable from one trade" separate.

Please don't recommend a change to the live bot from this one trade. Recommend tests instead.
