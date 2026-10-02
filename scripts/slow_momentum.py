"""Slow time-series momentum benchmark (RESEARCH_TEST_SPEC section 3; research only).

Usage:
  python scripts/slow_momentum.py --research-database data/dukascopy-2012-2018.sqlite3 \
      --research-database data/dukascopy-research.sqlite3 [--cost-scale 2] [--financing-debit 0.02]

Rules (fixed in advance, no tuning):
- Daily close = last H1 close of each UTC weekday (Dukascopy BID; the spec asks for midpoint,
  which this data cannot provide - declared limitation).
- At each month-end, signal per pair = mean(sign of price change over 3, 6, 12 months).
- Weight = signal x 0.10 / (3 x annualised stdev of the last 252 daily returns); total |weight|
  capped at 1 by proportional scaling. Needs 12 months of history and 252 returns.
- Rebalance at the next day's close and hold to the next month-end. No stops, no filters.
- Costs: assumed round-trip pips (0.9/1.2/1.0) charged on traded notional at each rebalance;
  financing is unknown (bid-only data): base case 0, stress via --financing-debit (annual rate
  charged on gross exposure, no credits).
Comparators: flat, and constant-long with the same volatility scaling, caps and costs.
Output: annual return, volatility, Sharpe, max drawdown, by year, by pair, and a block-bootstrap
confidence interval for the monthly excess return over the constant-long comparator.
"""
from __future__ import annotations

import argparse
import itertools
import math
import random
import statistics
from collections import defaultdict
from datetime import date

COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
TARGET_VOL, LOOKBACKS = 0.10, (3, 6, 12)


def daily_closes(databases: list[str], symbol: str) -> dict[date, float]:
    from research_db import load_candles

    from forex.domain import Timeframe

    closes: dict[date, tuple[str, float]] = {}
    for database in databases:
        candles = load_candles(database, symbol, Timeframe.H1)
        print(f"  {symbol} {database}: {len(candles)} H1 rows", flush=True)
        for candle in candles:
            day = candle.timestamp_utc.date()
            if day.weekday() >= 5:
                continue
            key = candle.timestamp_utc.isoformat()
            if day not in closes or key > closes[day][0]:
                closes[day] = (key, float(candle.close))
    return {d: v for d, (_, v) in sorted(closes.items())}


def month_ends(days: list[date]) -> list[date]:
    ends = []
    for a, b in itertools.pairwise(days):
        if (a.year, a.month) != (b.year, b.month):
            ends.append(a)
    return ends


def simulate(prices: dict[str, dict[date, float]], mode: str, cost_scale: float,
             financing: float) -> tuple[list[date], list[float], dict[str, float]]:
    """Daily portfolio returns for mode 'momentum' or 'long'."""
    days = sorted(set.intersection(*(set(p) for p in prices.values())))
    index = {d: i for i, d in enumerate(days)}
    rets = {s: [0.0] + [p[days[i]] / p[days[i - 1]] - 1 for i in range(1, len(days))] for s, p in prices.items()}
    ends = set(month_ends(days))
    weights = {s: 0.0 for s in prices}
    pending: dict[str, float] | None = None
    out_days, out_rets, contribution = [], [], defaultdict(float)
    for i, d in enumerate(days):
        if i == 0:
            continue
        day_ret = sum(weights[s] * rets[s][i] for s in prices)
        for s in prices:
            contribution[s] += weights[s] * rets[s][i]
        day_ret -= financing / 252 * sum(abs(w) for w in weights.values())
        if pending is not None:  # Rebalance at this day's close (first close after month-end).
            for s in prices:
                turnover = abs(pending[s] - weights[s])
                cost = COST_PIPS[s] * (0.01 if s.endswith("JPY") else 0.0001) * cost_scale / prices[s][d]
                day_ret -= turnover * cost
                contribution[s] -= turnover * cost
            weights, pending = pending, None
        out_days.append(d)
        out_rets.append(day_ret)
        if d in ends:
            target = {}
            for s, p in prices.items():
                k = index[d]
                if k < 253:
                    target[s] = 0.0
                    continue
                vol = statistics.pstdev(rets[s][k - 251:k + 1]) * math.sqrt(252)
                past = [_months_back(days, p, d, m) for m in LOOKBACKS]
                if vol <= 0 or any(x is None for x in past):
                    target[s] = 0.0
                    continue
                signal = (1.0 if mode == "long" else
                          sum((p[d] > x) - (p[d] < x) for x in past if x is not None) / len(LOOKBACKS))
                target[s] = signal * TARGET_VOL / (len(prices) * vol)
            gross = sum(abs(w) for w in target.values())
            if gross > 1:
                target = {s: w / gross for s, w in target.items()}
            pending = target
    return out_days, out_rets, dict(contribution)


def _months_back(days: list[date], prices: dict[date, float], d: date, months: int) -> float | None:
    year, month = d.year, d.month - months
    while month <= 0:
        year, month = year - 1, month + 12
    candidates = [x for x in days if (x.year, x.month) == (year, month)]
    return prices[candidates[-1]] if candidates else None


def stats(days: list[date], rets: list[float], start: int) -> dict[str, float]:
    r = rets[start:]
    if not r:
        return {}
    equity, peak, drawdown = 1.0, 1.0, 0.0
    for x in r:
        equity *= 1 + x
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    years = len(r) / 252
    vol = statistics.pstdev(r) * math.sqrt(252)
    annual = equity ** (1 / years) - 1 if years > 0 else 0.0
    return {"from": str(days[start]), "to": str(days[-1]), "annual_return": round(annual, 4),
            "annual_vol": round(vol, 4), "sharpe": round(statistics.fmean(r) * 252 / vol, 3) if vol else 0.0,
            "max_drawdown": round(drawdown, 4), "total_return": round(equity - 1, 4)}


def monthly(days: list[date], rets: list[float]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = defaultdict(lambda: 1.0)
    for d, x in zip(days, rets, strict=True):
        out[(d.year, d.month)] *= 1 + x
    return {k: v - 1 for k, v in out.items()}


def block_bootstrap(diffs: list[float], block: int, draws: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        sample: list[float] = []
        while len(sample) < len(diffs):
            start = rng.randrange(0, max(1, len(diffs) - block + 1))
            sample += diffs[start:start + block]
        means.append(statistics.fmean(sample[:len(diffs)]))
    means.sort()
    return means[int(0.025 * draws)], means[int(0.975 * draws)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--research-database", action="append", required=True)
    parser.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY")
    parser.add_argument("--cost-scale", type=float, default=1.0)
    parser.add_argument("--financing-debit", type=float, default=0.0, help="Annual rate on gross exposure (stress)")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    prices = {s: daily_closes(args.research_database, s) for s in symbols}
    for s, p in prices.items():
        if not p:
            raise SystemExit(f"No {s} prices loaded; check the database paths.")
        print(f"  {s}: {len(p)} daily closes {min(p)} .. {max(p)}", flush=True)
    results = {}
    for mode in ("momentum", "long"):
        days, rets, contribution = simulate(prices, mode, args.cost_scale, args.financing_debit)
        first = next((i for i, x in enumerate(rets) if x != 0), len(rets))
        results[mode] = (days, rets, contribution, first)
    start = max(results["momentum"][3], results["long"][3])
    print(f"Pairs {symbols}; cost x{args.cost_scale}; financing debit {args.financing_debit:.1%}/yr on gross exposure")
    for mode, (days, rets, contribution, _) in results.items():
        print(f"\n{mode.upper()}: {stats(days, rets, start)}")
        print("  contribution by pair (sum of daily weighted returns): "
              + ", ".join(f"{s} {v:+.3f}" for s, v in contribution.items()))
        by_year: dict[int, float] = defaultdict(lambda: 1.0)
        for d, x in zip(days[start:], rets[start:], strict=True):
            by_year[d.year] *= 1 + x
        print("  by year: " + " | ".join(f"{y} {v - 1:+.1%}" for y, v in sorted(by_year.items())))
    m_days, m_rets = results["momentum"][0], results["momentum"][1]
    l_days, l_rets = results["long"][0], results["long"][1]
    mm, ml = monthly(m_days[start:], m_rets[start:]), monthly(l_days[start:], l_rets[start:])
    months = sorted(set(mm) & set(ml))
    diffs = [mm[k] - ml[k] for k in months]
    mom = [mm[k] for k in months]
    for label, series in (("momentum monthly return", mom), ("momentum minus constant-long", diffs)):
        if len(series) > 12:
            for block in (1, 3, 6):
                low, high = block_bootstrap(series, block, 5000, 2026100200)
                print(f"{label}: mean {statistics.fmean(series):+.4%}/month, 95% CI [{low:+.4%}, {high:+.4%}] "
                      f"(block {block} months, n={len(series)})")
    print("\nPass mark (spec): positive net return AND positive paired improvement vs constant-long, with the CI "
          "lower bound above zero; otherwise inconclusive or fail. Data: Dukascopy bid, costs assumed, financing not observed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
