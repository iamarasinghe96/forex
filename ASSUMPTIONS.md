# Assumptions and unvalidated values

Layers 1–4 contain no claimed strategy edge and no fabricated historical statistics.

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
# Layer 4 research assumptions and limitations

* Formal strategy validation requires at least five elapsed years in **both** H1 and H4 for every
  configured pair. The current real VPS exposes about 0.74 years; this is sufficient only to verify the
  engine. The gate is not weakened and data is never fabricated.
* Historical replay invokes Layer 3 `analyse_market` unchanged after each actual H1 close. Visibility is
  `timestamp + timeframe duration <= evaluation time`; actual stored H4 timestamps are used because IC
  Markets New-York-close H4 UTC alignment shifts with DST.
* A signal cannot fill on its decision bar. Research entry is the next available H1 open. Structural
  stop, 1.5R-or-greater target, 1R breakeven, ATR trailing, and time horizon are explicit UNVALIDATED
  research policies, not production instructions or account-risk sizing.
* OHLC has no path ordering. A bar touching stop and target is adverse stop-first in primary results;
  ambiguity is recorded. Stop adjustments activate after the complete bar that triggers them.
* Candle `spread` is broker points, not historical tick execution spread. It is used only with captured
  instrument `point` metadata and is labelled UNVALIDATED. Commission, slippage, swap, and other fees
  remain UNAVAILABLE unless empirical data is supplied. No values are invented, and the cost model is
  incomplete for final profitability validation.
* Forward return/MFE/MAE paths are labelled after decisions. For rejected states they describe market
  movement from the last closed price only; they are not hypothetical fills or automatically “missed
  trades.” Rejection counts permit later study of over-restrictive filters.
* Fold outcomes and forward paths stop at the fold boundary. Unresolved simulations are explicitly
  `WINDOW_BOUNDARY_CENSORED` and excluded from expectancy rather than closed at an invented price.
* Candidate and trade frequency are reported with expectancy. The 3–8 trades/week design target is a
  calibration target, never an acceptance filter. Fewer trades are not presumed safer.
* Raw hourly candidate states remain intact. Contiguous symbol/side/setup runs are additionally counted
  as setup episodes; these and independent candidate simulations are not future executable trade counts.
* Parameter experiments are explicit, bounded, stable-hashed research candidates. `unvalidated-v1`
  remains unchanged. No winner is written to operator configuration or promoted automatically.
* Walk-forward folds are deterministic train-then-test intervals. Parameter selection for a fold uses
  only its train result; subsequent tests remain OOS. A final holdout boundary is excluded from the
  loop and should not be repeatedly inspected. In-sample and aggregate OOS results remain distinct.
* Monte Carlo is seeded IID bootstrap resampling of completed normalized trade outcomes. It reports
  expectancy, cumulative R, drawdown, and win/loss streak distributions. Independence is questionable
  in regime-driven markets, it creates no fake price history, and it computes no account probability
  of ruin.
* Baselines segment direction, pair, setup, regime, session, style, plus candidate/rejection frequency;
  stored snapshots also retain volatility and feature context. This supports a future closed-loop
  comparison but implements no diagnosis, veto, recent-loss throttle, or strategy mutation.
* Layer 4 contains no balance-based sizing, portfolio controls, live execution, broker order calls,
  LLM/news inference, production journal/dashboard, paper daemon, or deployment implementation.

## Layer 5 operator policy and limitations

- `layer5-fusion-v1-unvalidated` maps the existing Layer 3 score via
  `(1 - uncertainty) * 100`; it introduces no indicator reweighting and no 50/25/25 fusion.
  Unavailable macro/news/context is excluded. Available future deterministic context can be
  confidence-weighted without requiring unanimity; no external-provider veto threshold exists.
- Score boundaries 55/70/85 are provisional operator policy, not empirical validation. Exact
  risks are 2%, 3.5%, and 5%; below 55 produces no proposal. There is no Kelly sizing,
  loss-streak penalty, drawdown scaling, pair/setup suppression, or learning veto.
  These values have one operator source: validated `config.yaml` fields converted through
  `Decimal(str(value))` into an immutable pure-engine policy.
- Broker tick size/value and stop distance determine loss per lot. Decimal volume always rounds
  down. Invalid stop side, broker minimum stop distance, unaffordable minimum volume, leverage
  above 1:30, objective below 1.5R, four existing positions, or total risk above 20% is a hard
  policy block.
- The daily limit is 12% of supplied session-opening balance versus current equity and is
  latched transactionally in SQLite. The kill switch is independently persisted. Both emit
  flatten intent only; no order API is present.
- Breakeven becomes eligible at +1R. ATR trailing follows breakeven and is monotonic, but its
  multiplier is currently unvalidated/not configured. Correlated USD exposure is diagnostic
  metadata only and adds no invented ceiling.
- Layer 5 is the structural maximum for Layer 6: later review can reduce or veto, never enlarge
  exposure, loosen a stop, reduce the directional 1.5R objective, or weaken a hard control.
  Non-eligible and blocked decisions expose no permitted plan. Layer 4 reports normalized R;
  the short history cannot validate five years or honestly reconstruct missing historical
  conversion metadata. The 3–8/week target applies only to future executed trades.

## External research-history assumptions

- Imports are isolated in an operator-selected SQLite database and retain provider/release, file hash,
  price/volume/spread semantics, UTC, coverage, count, import time and transformation provenance. No
  provider is endorsed until independently verified.
- Input is strict UTC H1. Research H4 uses complete four-hour groups under an explicit fixed UTC
  alignment hour (0–3); incomplete groups remain gaps. It is not IC Markets broker-native H4.
- Unavailable spread/volume maps to the legacy candle model's zero while provenance marks it
  unavailable. This is not a zero transaction-cost or genuine-volume claim.
- Candle and provenance writes share one transaction. A research database is homogeneous in provider,
  release, price/time/alignment, spread and volume semantics; incompatible sources require another
  database. Research reports include a deterministic provenance fingerprint and use a distinct file.

## Layer 6 operational assumptions

Context timeout (15s), retry count (2), backoff (1s exponential), and output token cap (1500)
are configurable UNVALIDATED operational defaults, not observed market/strategy constants.
All providers/models/credentials are unverified until configured. Missing cost reporting is
UNAVAILABLE, not free usage. Context input must contain genuine evidence; no news is fabricated.
