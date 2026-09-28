# Forex Operator — Layer 1 Foundation

This repository currently provides the safe foundation and MT5 read-only verification command.
It **cannot place, change, or close an order**. Later layers must not be assumed to exist.

## Windows demo verification

1. Install 64-bit Python 3.12 and MetaTrader 5, then log into the demo account in MT5.
2. Open PowerShell in this folder and run `py -3.12 -m venv .venv`.
3. Run `.venv\Scripts\python -m pip install -e ".[mt5,dev]"`.
4. Copy `.env.example` to `.env`; put the demo trading password only in that local file.
5. Confirm `config.yaml` contains the correct login, server, and expected account currency.
6. Enable the **Algo Trading** toolbar button. Layer 1 sends no orders, but checking this now catches
   the exact client condition that later produces MT5 retcode 10027.
7. Run `.venv\Scripts\forex verify-foundation`.

Success prints the account facts and the broker-resolved name, pip size, runtime AUD pip value,
tick properties, and filling mode for every configured pair. It ends with **No order was sent**.
