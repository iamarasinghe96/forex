# Strategy workbench

Since 17 October 2026 the bot has **no entry strategy** (`paper.entry_strategy: none`). The account
had fallen to about A$955, and the operator is designing a new strategy. Nothing was deleted:
- the old trend strategy (`trend-v1`);
- its research;
- the learning scores;
- the review prompts.

The old strategy now runs only as a set of **scoring tools**, measured every hour and never traded.

## What runs now

- **Every hour, for each pair,** the bot measures everything the old strategy used and publishes a
  scorecard:
  - Telegram: `/scorecard`;
  - dashboard: the "Scoring tools" section;
  - journal: `scorecard` events, for later analysis.
- **`/levels` in Telegram** runs the previous-day high/low study (below) on the hourly prices the
  bot has stored, about the last year, and sends the full report as a file.
- **The strategy lab** (`tools\strategy-lab.bat`, on the PC) tests strategies on 2012–2026 under the
  paper rules and keeps every run (see "Testing on history" below).
- **When the old rules would have traded,** the hour is recorded as "Scoring only: no entry
  strategy is active (the old trend rules would buy/sell)". These records show what the old strategy
  would have done, so a new strategy can be compared against it.
- **Trades opened earlier** keep their stops, break-even and trailing exits until they close.
- **The rest keeps working:** risk limits, the 10% US-dollar cap, `/loss`, `/lookback` and the
  daily recap. The weekly "no fills" alert is off while no strategy trades.
- **To turn the old strategy back on,** set `paper.entry_strategy: trend-v1` and restart.

## The scoring tools and what the research found about each

| Tool (scorecard field) | What it measures | Research verdict (2012–2026 hourly data, costs included) |
|---|---|---|
| **4-hour trend:** regime, direction, strength | Direction combines the EMA 20/50 gap, the 20 EMA's slope and the last 5 bars' up/down count. Strength = 0.45 × \|direction\| + 0.55 × efficiency. Regime is TREND_UP/DOWN at strength ≥ 0.55, otherwise RANGE, TRANSITION and so on. | The only part with any value. Trading in the trend's direction gave a small profit (+0.055 R per trade, 2021–2025), mostly USDJPY buys. It was about break-even in the latest year. |
| **Efficiency** (4-hour) | Net move ÷ total distance travelled over 10 bars: how clean the trend is | Part of trend strength. Faster detection (10 bars) changed results by period. |
| **Volatility rank** (4-hour and 1-hour) | Where the current ATR sits among the last 100 bars (1 = most volatile) | Blocking trends in the top 10% of volatility had unstable effects. |
| **Place in the 20-hour range** | 0 = at the 20-hour low, 1 = at the high. It can go past 0 or 1 after a breakout. | The old rules bought near 1 and sold near 0, i.e. chased. Never tested on its own as a filter; pullback entries (0.4–0.7) are queued. |
| **Distance from the 20 EMA** | How far price has run from its 1-hour average, in ATRs | Part of "pullback coherence". No standalone test yet. |
| **RSI, MACD** (1-hour) | Momentum | Inside the setup score; no standalone edge found. |
| **Hourly ATR** | Typical hourly movement in pips | The basis for stops and the trailing exit. |
| **Old setup score** and its 4 parts | The old entry gate: the average of trend, momentum, structure and pullback | **No skill.** Random entries in the same trend did better (+0.087 R against +0.055 R). Higher scores did worse. |
| **Old strategy would BUY/SELL, and its stop** | The old rules' full decision; the stop is the 20-hour low or high | See above. Its stops were often 4–9 × ATR wide. |
| **Previous day's high and low** (`day_levels`) | The previous forex day's high and low (17:00–17:00 New York) and the type of day it was (inside, single or double break). Also the distance from price to each level in ATRs, and what today has done so far: which level it has run, and whether London and New York opened inside the range. | Being measured: `/levels`. On computer-made random prices the study finds the video's day-type split too (see below). |

**Ideas already rejected, so start from a different base:**
- range mean reversion: buying lows and selling highs inside a range, against no trend;
- confidence floors;
- confirmation entries;
- textbook swing breakouts;
- slow 1–12-month momentum.

**Ideas already queued:** see `docs/LOSS_LESSONS.md`. They include pullback entries, no chasing,
session filters, stop buffers, exit variants and event filters. Validated swing lows (break of
structure) are another idea worth adding as a tool.

## The previous day's high and low (idea from a trading video, 17 Oct)

The video (Nasdaq futures, about 200 days) says price is drawn to the previous day's high and low,
where stop orders sit. Its figures:
- 11% of days run neither level, 77% one, 12% both;
- opening inside the previous range, the level is run in the morning session 80% of the time;
- opening outside, price comes back to the level about 56% of the time;
- price often reverses after running the level.

`src/forex/day_levels.py` measures the same things on our pairs, with forex definitions:
- a day runs from 17:00 to 17:00 New York time;
- the London and New York opens are at 08:00 local time, and "the morning" is the next 4 hours.

Each result sits beside the same measurement on an ordinary level the same distance away on the other
side ("mirrored"). Price reaches nearby levels often by chance, so only a difference from the
mirrored level counts as an edge.

**Checked on computer-made random prices**, which have no edge by construction:
- the day types came out at 11% / 79% / 10%, nearly the video's split;
- the previous high or low was run as often as its mirrored level;
- after a level was run, price moved 1 ATR back first about 50% of the time.

So the video's headline numbers are what chance alone produces. Its "80%" also counts only days that
turned out one-sided, which is known only when the day ends. Whether real forex prices beat chance is
what `/levels` shows on the bot's stored year. On the PC, the strategy lab's study
(`tools\previous-day-study.bat`) runs it on 2012–2026.

## Testing on history: the strategy lab

The strategy lab runs on the PC, where the 2012–2026 Dukascopy hourly databases are stored. It tests
entry ideas under the paper bot's own rules and saves every run. It is research only: it never
contacts the broker and changes nothing in the live bot.

**Double-click files** (in `C:\Users\Indika\Desktop\forex\tools\`):

| File | What it does |
|---|---|
| `strategy-lab.bat` | A menu: test all strategies or one, run the previous-day study, list the strategies, open the results folder or the settings. |
| `test-all-strategies.bat` | Tests every strategy that is switched on, compares them, saves the results and opens the summary. |
| `previous-day-study.bat` | The video's previous-day high/low numbers on our pairs, 2012–2026, with the mirrored-level checks. |

**Settings:** `strategy-lab.yaml` in the repository folder. It holds:
- the databases, pairs and dates;
- the assumed costs (0.9 / 1.2 / 1.0 pips round trip);
- the rules: 5% risk, one trade per pair, the 10% US-dollar cap, break-even at +1R, a 3 × ATR trail
  and a 10R target, as on paper;
- each strategy's on/off switch, its settings, and any exit overrides.

Change a number, run again, and compare the runs in the ledger.

**Results:** each run goes in its own folder under `reports\strategy-lab\`:
- `summary.txt`: a comparison table, then each strategy in detail;
- `<strategy>-trades.csv`: every trade, for Excel;
- `settings-used.yaml`: the settings as they were for that run.

`ledger.csv` lists every run, one line per strategy, and `latest.txt` is the newest summary.

**How a trade is simulated** (the same conventions as the earlier research):
- **Entry:** at the close of the hour that gives the signal.
- **Costs:** subtracted from every trade.
- **Exits:** the stop, the target, break-even and the trail, with the live bot's stop rule.
- **Stop moves** apply from the next hour.
- **When the stop and target are both touched in one hour,** the stop is assumed.
- **An hour that opens beyond the stop** fills at that open.
- **Trades cannot cross a data hole.**

**The pass bar** is the one pre-registered above. Each line is checked and printed as PASS or FAIL:
- a profit before 2019 and from 2019;
- a profit at double costs;
- a profit without USDJPY;
- at least 100 trades;
- better than 95% of 200 random-direction runs.

The random runs use the same moments, stops and exits, with one coin flip per run of signals. On
computer-made random prices this check passed 1 time in 36, close to the 5% chance level.

**Strategies included:**
- **`trend-v1`, the old strategy, as the reference to beat.** It replays the live analysis hour by
  hour, which takes 10–30 minutes the first time; the result is cached in `data\lab-cache\`.
- **`pd-sweep`:** previous-day sweep reversal (video 10:37).
- **`pd-breakout`:** previous-day breakout (video 9:19).
- **`pd-magnet`:** trade towards the nearer previous-day level from the London or New York open
  (video 4:00–5:23).

`list` in the menu describes each one with its current settings.

## Designing a strategy: fill in each line

Write it in plain words with numbers. If a reading isn't in the scorecard yet, describe it, and
Claude Code will add it as a new tool.

1. **Pairs and timeframe:** which pairs, and on which bar close it decides (e.g. every 1-hour close).
2. **Direction filter:** when buys are allowed and when sells are (e.g. only in the 4-hour trend).
3. **Entry trigger:** the exact condition on the bar that opens a trade.
4. **Stop:** where it goes and why (a level, or a number of ATRs).
5. **Exits:** a target, break-even, trailing, a time limit, or an opposite signal.
6. **Size:** risk per trade (currently 5%, set by the operator), and any limits.
7. **Filters:** sessions, news or events, the US-dollar exposure cap.
8. **What would prove it wrong:** the result on 2012–2026 data that would make you drop it.

## From design to live

1. **Rules in.** Send the filled-in template to Claude Code. It becomes a new named strategy (e.g.
   `operator-v1`) beside `trend-v1`; nothing old is removed.
2. **Pre-register, then test.** The pass bar is written down before any results are seen: both
   2012–2018 and 2019–2026, at double costs, without depending on USDJPY alone, and against random
   entries.
   - The new strategy is added to the strategy lab. Running `tools\test-all-strategies.bat` on the
     PC prints PASS or FAIL against this bar.
   - Claude Code can't run it in the cloud, because `datafeed.dukascopy.com` is blocked there.
3. **Paper.** If it passes, `paper.entry_strategy` is set to the new name. It then runs on paper
   with the same scorecards, loss reviews and lookbacks.
