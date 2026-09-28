# Assumptions and unvalidated values

Layers 1–2 contain no claimed strategy edge and no fabricated historical statistics.

The following operator choices are **unvalidated** rather than empirical strategy parameters:

- The risk limits and tax reserve in `config.yaml` reproduce the build brief. The reserve is an
  accounting estimate, not tax advice.
- `magic_number` is merely a namespace chosen for this bot; it has no market significance.
- Logging sizes, connection timeout, and Telegram timeout are operational defaults. They do not
  influence trade selection or position size.
- IC Markets MT5 timestamps are assumed to encode broker server wall time: GMT+2 outside US DST
  and GMT+3 from the second Sunday in March through the first Sunday in November. The adapter
  normalizes each tick and historical candle using the offset for that timestamp before broker-
  neutral objects or SQLite see it. It also converts each UTC history-request bound independently
  onto the server-wall timeline expected by MT5, including ranges whose bounds use different
  offsets. FX is closed during the Sunday transition, avoiding ambiguous H1/H4 market bars; this
  documented schedule remains an **unvalidated** broker assumption.
- H1/H4 stale limits and the configured Friday/Sunday UTC closure hours are operational defaults.
  Weekend classification shifts those standard-time UTC boundaries one hour earlier during US DST.
  It does not fabricate bars, and unusual historical broker sessions remain unvalidated.
- The live MT5 server-clock sanity tolerance is an **unvalidated** operational value. Verification
  expects the raw server wall clock to be approximately two or three hours ahead of synchronized
  system UTC, according to the same historical schedule, and fails with operator guidance otherwise.
- UTC is canonical after adapter normalization: ticks, candles, SQLite timestamps, freshness and gap
  calculations, and future backtesting data all use true UTC.
- Five years is a later backtesting depth target, not an assertion that MT5 exposes five years.
  Layer 2 records and reports only the terminal's actual history.
- A conventional Forex pip is defined as 0.0001, or 0.01 for three-decimal JPY quoting. The code
  derives this as ten MT5 points for symbols with 3 or 5 digits and one point otherwise, and prints
  the derivation during verification.

Strategy indicators, weights, thresholds, ATR multipliers, and fusion parameters will be added
only after Layer 4 measurement. The fabricated prototype scenario library is deliberately omitted.

## Layer 3 UNVALIDATED research assumptions

All analysis settings in `config.yaml` are centralized, versioned **UNVALIDATED** research starting
points, not optimized parameters or evidence of profitability: EMA 20/50/200, RSI 14, MACD 12/26/9,
ATR 14, structural window 20, volatility-rank window 100, slope lookback 5, return horizons 1/5/20,
trend/range/setup thresholds, mean-deviation extreme and DAY/SWING persistence threshold. Layer 4 must
measure sensitivity and validate replacements; changing behavior requires a new parameter and/or
strategy version.

Feature definitions are: recursively seeded EMA; simple-window RSI gains/losses; EMA MACD and signal;
true-range mean ATR; population standard deviation of log returns; empirical ATR percentile; absolute
net movement divided by path length for directional efficiency; prior-window high/low and normalized
breakout distances; close location within that range; rolling-mean population z-score; and last-bar
body/wick/range ratios. Spread remains raw broker points. Tick volume is explicitly broker tick volume,
not centralized FX volume.

The provisional multidimensional regime retains continuous directional bias, trend/range strength,
volatility rank, momentum and structural breakout state even when it derives a descriptive label.
Candidate selection uses graded support and opposition, not indicator unanimity. Mild contrary evidence
is recorded rather than automatically vetoing. No frequency or expectancy claim is made.

London and New York sessions use IANA timezone/DST conversion (`Europe/London` and
`America/New_York`); Asia uses `Asia/Tokyo`. Session is metadata only. Relative macro data defaults to
explicitly unavailable, never neutral/zero/bullish/bearish, and missing macro neither penalizes nor
vetoes technical analysis. No synthetic macro/news data exists.

Layer 3 creates stable hooks for future automatic, multi-label, confidence-scored outcome attribution
and counterfactual analysis of both executed and rejected opportunities. Normal operation is designed
not to require manual loss labels. It cannot react to a few losses by blocking trades and cannot
self-modify live parameters; validated, versioned promotion is mandatory. Layer 3 itself implements no
backtester, optimizer, risk/fusion, LLM, execution, journal persistence, paper runtime, or learner.
