# Forex Operator — Layer 3 Analysis / Strategy

Layers 1–2 provide the verified read-only broker and market-data foundation. Layer 3 adds pure,
deterministic analysis and candidate generation; it still contains no risk sizing or order execution
and makes no claim of a validated trading edge.

## Windows demo setup and verification

From PowerShell, with 64-bit Python 3.12 or 3.13 and MetaTrader 5 logged into the configured demo:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mt5,dev]"
.\.venv\Scripts\forex.exe verify-foundation
.\.venv\Scripts\forex.exe verify-market-data
```

Put the demo trading password only in the ignored `.env` file. The market-data command verifies
fresh ticks and recent candles, then downloads every H1/H4 chunk currently exposed by MT5 into the
configured SQLite database. Success ends with:

```text
Layer 2 verification passed. Historical candles were saved; no order was sent.
```

Each series reports its actual earliest/latest UTC times, candle count, depth in days/years, expected
weekend gaps, and unexplained gaps. A warning below five years means later backtesting lacks its
desired depth; it is not filled, purchased, or fabricated. MT5 availability depends on the broker,
terminal cache, loaded charts, and **Tools → Options → Charts → Max bars in chart**. Increase that
setting, restart/load each chart, and rerun safely; SQLite upserts are idempotent and can update the
forming candle.

## Layer 3 analysis / strategy

Layer 3 is a read-only, broker-neutral deterministic analysis pipeline shared by future live, paper,
replay, walk-forward, and attribution callers. It does not connect to MT5: `forex verify-analysis`
loads the existing SQLite H1/H4 history, uses only bars satisfying `timestamp_utc + duration <=
evaluation_time`, and prints one analysis snapshot per configured pair. Actual normalized timestamps are
used, so H4 is never assumed to start at UTC multiples of four hours. If data is missing or stale, run
`forex verify-market-data`; analysis never silently fetches data and never sends an order.

H4 supplies graded direction, persistence, range, momentum, volatility-rank and structural-breakout
context. H1 supplies tactical continuation/pullback or range-reversion evidence. EMA relationships and
slope, multi-horizon returns, directional efficiency, RSI, MACD, ATR/price, realised volatility,
volatility rank, rolling levels, breakout distances, range position, mean deviation, body/wicks,
range expansion, follow-through, broker tick volume and broker spread points form the feature snapshot.
Tick volume is broker activity, **not centralized global FX volume**.

Every call returns an `AnalysisSnapshot`, including no-trade calls, with a deterministic evaluation ID,
versioned features/regime/setup measurements, last closed bars, supporting and opposing evidence,
no-candidate reason, session, volatility and macro availability. A coherent setup can additionally
produce a `TradeCandidate`; it contains analytical evidence and structural references but no size,
risk percentage, SL/TP, or broker order fields. Trend continuation is automatically DAY or SWING from
H4 persistence; range reversion is initially DAY. These rules and all thresholds are UNVALIDATED.

Macro is a provider-neutral relative base/quote contract. With no genuine provider it is explicitly
`UNAVAILABLE`: it supplies neither bullish nor bearish evidence, does not reduce technical strength,
and does not veto a candidate. No news, sentiment, probabilities, scenarios, or LLM output is invented.

```powershell
.\.venv\Scripts\forex.exe verify-analysis
```

Expected output includes evaluation UTC, latest closed H1/H4 timestamps, regime, directional and
volatility measurements, setup/style, evidence, candidate/direction, macro availability, and strategy
and parameter versions, ending with `Layer 3 analysis verification passed... no order was sent.`
