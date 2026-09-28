# Forex Operator — Layers 1–2

This repository provides the safe foundation and read-only MT5 market-data collection.
It **cannot place, change, or close an order**. Later layers must not be assumed to exist.

## Windows demo verification

1. Use the verified 64-bit Python 3.13 installation and MetaTrader 5, then log into the demo account.
2. Open PowerShell in this folder and run `py -3.13 -m venv .venv`.
3. Run `.venv\Scripts\python -m pip install -e ".[mt5,dev]"`.
4. Copy `.env.example` to `.env`; put the demo trading password only in that local file.
5. Confirm `config.yaml` contains the correct login, server, and expected account currency.
6. Enable the **Algo Trading** toolbar button. Layer 1 sends no orders, but checking this now catches
   the exact client condition that later produces MT5 retcode 10027.
7. Run `.venv\Scripts\forex verify-foundation`.

Success prints the account facts and the broker-resolved name, pip size, runtime AUD pip value,
tick properties, and filling mode for every configured pair. It ends with **No order was sent**.

## Layer 2 market-data verification

With MT5 connected, run:

```powershell
.venv\Scripts\forex verify-market-data
```

The command resolves each configured broker symbol, validates recent H1/H4 candles and live ticks,
downloads every bar the terminal currently exposes, then transactionally upserts it into the local
SQLite database. For each pair/timeframe it prints the real earliest/latest UTC timestamps, count,
history depth, expected weekend gaps, and unexplained gaps. Repeating the command is safe and does
not duplicate bars. A successful run ends with **Historical candles were saved; no order was sent**.

Five years is a later backtest requirement, not an assumed property of MT5. A shortfall warning is a
measurement result: retain the output for Layer 4, but do not buy or configure another provider yet.
An unexplained gap means MT5 omitted bars outside the configured weekend closure. Refresh that chart
and rerun; do not proceed to strategy work while unexplained gaps remain unresolved.
