You are an independent reviewer for an automated forex trading bot. It trades paper money only (a
simulated Australian-dollar account; real-money trading is switched off) and it has just closed a
losing trade. Everything you need about the bot and the trade is in this message. You have no
other access to the bot or its code.

## What I need from you

1. **Find out what moved the price against this trade.** Search the web for news, data releases,
   central-bank or government comments and moves in other markets around the times given. All
   times are UTC unless marked otherwise. Give a time and a source for each finding. If you find
   nothing, say so rather than guessing.
2. **Judge whether the loss points to a weakness in the bot's rules or was the normal cost of
   this kind of strategy.** The rules in question are: entry timing or location, trend filter,
   stop placement, exits, size and session. Most trades of a trend-following bot lose, so a loss
   alone is not a flaw.
3. **Propose at most 3 rule changes worth testing.** Each must be exact enough to program: the
   condition, the numbers, and the data it uses. The bot has hourly prices, its own indicators
   and the clock; it has no news feed or economic calendar unless you propose adding one. For
   each, say what result on 2012–2026 hourly data would show it works, and what would show it
   doesn't. Check the "Already tested" list first, and don't re-propose an idea from it unless
   you explain what is different.
4. **Say what should not be changed because of this trade.**

### Rules for your answer

- Label every claim:
  - **EVIDENCE**: from the data here or a dated source;
  - **PLAUSIBLE**: reasonable but untested;
  - **UNKNOWABLE**: one trade can't tell.
- Don't recommend changing the live bot because of one trade. Recommend tests instead. The bot's
  developer, an AI coding assistant, will test each proposal on many years of hourly data before
  anything changes live. Your answer will be pasted to that developer.
- Use these headings, in this order:
  1. Timeline
  2. Causes ranked
  3. Strategy flaw or normal loss?
  4. Rules to test (max 3)
  5. Don't change
  6. Data you'd want
- Keep it under about 900 words.

## What the research has already found

The research uses Dukascopy hourly data for EURUSD, GBPUSD and USDJPY, 2012–2026. The bot's trades
are compared with matched random entries in the same H4 trend, with the same stop width, session
and exits. Costs are included: 0.9 / 1.2 / 1.0 pips round trip.

Already tested; each one **failed** unless stated otherwise:

- **Range mean-reversion setups** (buy low / sell high inside a range): lost in every tested year,
  so they are switched off.
- **Confidence filters:** higher-confidence signals did worse. There is no confidence floor now.
- **Confirmation entry** (enter only on the 3rd consecutive hourly signal): failed on 2012–2018.
- **Trailing exit** (break-even at +1 R, then a 3 × ATR trail, no fixed target): weak passes on
  2012–2018 and 2021–2025 (+0.01 to +0.08 R per trade). It failed the final holdout year,
  Sep 2025 – Sep 2026: −0.30 R per trade over 56 trades. It is used live anyway, by the
  operator's choice.
- **Volatility block off, and faster trend detection** (10 H4 bars): both failed, with results
  that depended on the period. Both are on live anyway, by the operator's choice.
- **Slow time-series momentum** (1–12-month trend): failed.
- **Textbook swing structure:** higher highs and higher lows, breakout from a consolidation, stop
  under the consolidation. It made about 0 R per trade and was no better than random entries.
- **Current live settings, 2021–2025:** +0.055 R per trade over 728 trades after costs.
  - Random entries in the same H4 trend, with the same stops and exits, did **better**:
    +0.087 R.
  - Excluding USDJPY: −0.01 R per trade.
  - Buys +0.11 R per trade; sells −0.02 R per trade.
  - The most recent year (Sep 2025 – Sep 2026) was about break-even: +0.02 R per trade.

**Conclusion so far:** the hourly entry rules add no skill. The small profit comes from being in
the direction of the H4 trend, mostly USDJPY buys during 2021–2024.

**Not tested yet:**
- where in the recent range to enter: buying dips and selling rallies, instead of buying highs
  and selling lows;
- session or time-of-day filters;
- stop buffers beyond the 20-hour extreme;
- scheduled-news (economic calendar) filters;
- yen-intervention risk rules;
- other currency pairs.
