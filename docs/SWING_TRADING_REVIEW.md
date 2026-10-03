# Swing-trading theory vs the bot (2026-10-03)

## What the textbook rules say

The operator's chart (Investopedia, cup-and-handle / rectangle example) shows the classic swing
rules:

1. Trade with the larger trend: higher swing highs and higher swing lows (Dow theory).
2. Wait for a tight consolidation (rectangle or "handle") inside that trend.
3. Buy when price closes above the consolidation.
4. Put the stop just below the consolidation (the handle's low, not the cup's low).
5. Exit when price drops below a prior swing low.
6. Use daily-type bars: holds of days to weeks.

Practitioner write-ups agree on points 3-5 ([LuxAlgo](https://www.luxalgo.com/blog/cup-and-handle-swing-trading-strategy-guide/),
[TrendSpider](https://trendspider.com/learning-center/chart-patterns-cup-and-handle/),
[Trade That Swing](https://tradethatswing.com/the-cup-and-handle-swing-trading-strategy-explosive-consistent-price-moves/)).
These are teaching material, not evidence of profit.

## What the research says (peer-reviewed or central-bank work)

- Lo, Mamaysky & Wang (2000), US stocks 1962-1996: algorithmically detected chart patterns carry
  some incremental information. [JF paper](https://web.mit.edu/people/wangj/pap/LoMamayskyWang00.pdf)
- Brock, Lakonishok & LeBaron (1992): moving-average and trading-range-breakout rules beat cash
  on the Dow. [JF](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x)
- Sullivan, Timmermann & White (1999): after correcting for data snooping, the best rule worked
  in-sample but not in the next 10 years. [JF](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00163)
- Chang & Osler (NY Fed): head-and-shoulders was profitable for USD/DEM and USD/JPY, not for four
  other dollar pairs. [Staff report](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr42.pdf)
- Neely, Weller & Ulrich: FX technical-rule profits in the 1970s-80s were real, then declined
  (adaptive markets). [St. Louis Fed WP](https://files.stlouisfed.org/files/htdocs/wp/2006/2006-046.pdf)

Summary: pattern and breakout rules have shown value in some markets and decades. The value is
unstable and has shrunk since the 1990s in FX. They must be tested out of sample with the
rules fixed in advance.

## How the bot differs (checked in src/forex/analysis.py)

| Swing rule | The bot today |
|---|---|
| Trend = higher highs and higher lows | Trend = H4 indicator score (EMA 20/50 gap and slope, MACD, efficiency). No swing points. |
| Wait for a tight consolidation | No consolidation check. |
| Enter on a close above the consolidation | No breakout check. Despite the name "breakout/pullback", it enters on any H1 close where the trend score and a setup score pass. A component rewards price near the top of its 20-hour range. |
| Stop below the consolidation | Stop at the 20-bar **H1** low (about one day of bars). |
| Exit below a prior swing low | Break-even at +1R, then 3 x H1 ATR trail, 10R target. |
| Daily/H4 bars, holds of days to weeks | H1 decisions; most trades last hours to a few days. |

So the operator's impression is correct: the bot does not implement these swing rules. It is
an hourly trend-following entry with indicator-based trend detection.

## Test

`scripts/swing_structure.py` implements rules 1-5 exactly (details in its docstring), one trade
per pair, gap fills at the open, and costs of 0.9/1.2/1.0 pips. It is compared with 1,000
matched random entries in the same trend state with the same stop and exit. Checks done before
any real data:
- Hand-built series: entry, stop and trail land where they should (tests/test_swing_structure.py).
- Random-walk prices: neither the pattern nor the controls show a profit beyond costs, and the
  pattern never beats the controls (no look-ahead).

Pre-registration and results: BUILD_PROGRESS.md, "Pre-registration 4".
