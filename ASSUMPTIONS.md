# Assumptions and unvalidated values

Layers 1–2 contain no claimed strategy edge and no fabricated historical statistics.

The following operator choices are **unvalidated** rather than empirical strategy parameters:

- The risk limits and tax reserve in `config.yaml` reproduce the build brief. The reserve is an
  accounting estimate, not tax advice.
- `magic_number` is merely a namespace chosen for this bot; it has no market significance.
- Logging sizes, connection timeout, and Telegram timeout are operational defaults. They do not
  influence trade selection or position size.
- H1/H4 stale limits and the configured Friday/Sunday UTC closure hours are operational defaults.
  The closure approximation prevents routine weekend gaps from becoming failures, but historical
  broker sessions and DST transitions have not yet been validated.
- Five years is a later backtesting depth target, not an assertion that MT5 exposes five years.
  Layer 2 records and reports only the terminal's actual history.
- A conventional Forex pip is defined as 0.0001, or 0.01 for three-decimal JPY quoting. The code
  derives this as ten MT5 points for symbols with 3 or 5 digits and one point otherwise, and prints
  the derivation during verification.

Strategy indicators, weights, thresholds, ATR multipliers, and fusion parameters will be added
only after Layer 4 measurement. The fabricated prototype scenario library is deliberately omitted.
