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
