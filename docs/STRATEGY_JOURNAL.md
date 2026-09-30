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
