# Assumptions and unvalidated values

Layer 1 contains no claimed strategy edge and no fabricated historical statistics.

The following operator choices are **unvalidated** rather than empirical strategy parameters:

- The risk limits and tax reserve in `config.yaml` reproduce the build brief. The reserve is an
  accounting estimate, not tax advice.
- `magic_number` is merely a namespace chosen for this bot; it has no market significance.
- Logging sizes, connection timeout, and Telegram timeout are operational defaults. They do not
  influence trade selection or position size.
- A conventional Forex pip is defined as 0.0001, or 0.01 for three-decimal JPY quoting. The code
  derives this as ten MT5 points for symbols with 3 or 5 digits and one point otherwise, and prints
  the derivation during verification.
- **UNVALIDATED —** the expected FX weekend closure is approximated as Friday 22:00 UTC through
  Sunday 22:00 UTC, with up to four hours allowed for an H4 reopen bar. Broker hours move with DST,
  so both boundary hours are visible in `config.yaml`. Gaps outside that window are reported rather
  than silently accepted.
- The configurable H1 three-hour and H4 eight-hour freshness limits are operational starting
  values, not measured strategy parameters. They are intentionally wider than one bar so a delayed
  terminal is detected without classifying a normally forming candle as stale.

Strategy indicators, weights, thresholds, ATR multipliers, and fusion parameters will be added
only after Layer 4 measurement. The fabricated prototype scenario library is deliberately omitted.
