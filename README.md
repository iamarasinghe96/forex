# Forex Operator — Layer 2 Market Data

Layer 2 adds read-only, broker-neutral H1/H4 candle collection for EURUSD, GBPUSD, and USDJPY,
SQLite storage, stale-feed protection, and gap reporting. It contains no indicators, strategy,
risk sizing, or order execution and makes no claim of a trading edge.

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
