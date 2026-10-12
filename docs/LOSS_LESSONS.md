# Lessons from losses (ledger)

One entry per losing trade, with the outside review and what was checked. Patterns that recur
across entries become pre-registered tests; see [LOSS_REVIEWS.md](LOSS_REVIEWS.md) for the process.

Status values:
- **open:** recorded, not yet tested;
- **testing:** a pre-registered test is running;
- **passed** or **failed:** the test result;
- **dropped:** not worth testing, or contradicted by the data.

## 1. USDJPY Buy, 7 Oct 2026: −1.04 R (A$−53.70)

**Trade:**
- entry 158.427 at 04:00 UTC (Tokyo afternoon);
- stop 157.913, 51.4 pips = 4.5 × H1 ATR, so not a tight stop;
- stopped at 08:15 UTC, filled at 157.89 (2.3 pips of slippage).

**Market cause** (ChatGPT; checked against Reuters and Euronext reports of that week's French bond
stress):
- renewed selling of French government bonds led to euro selling, which spilled into yen buying;
- USDJPY fell to about 157.85 at 08:14–08:15 UTC, then bounced back above 158.

This is EVIDENCE for this trade's final move. No intervention or broker price error was found.

**Bot-side facts** (from its own record):
- it bought at 0.82 of the 20-hour range, after a rise of about 0.7 R during Asian hours;
- H1 momentum was weak, at 0.23;
- the H4 trend was 0.673, just below the 0.68 swing threshold.

**Ruled out for this trade:**
- **A stop buffer.** At 0.25 × ATR the stop would have been 157.884, and at 0.5 × ATR 157.856.
  The low was about 157.85, so both would have been hit.

**Hypotheses raised:**
- **H1, entry location:** entering at the range extreme after an extended move. Status: open,
  recurs in entry 2.
- **H2, Asian-session entries exposed to the European open:** status open.
- **H3, Tokyo-fix seasonality:** status dropped as a cause here. The effect is about 5 pips in
  the literature, far smaller than a 51-pip stop.
- **H4, yen intervention-zone risk cap:** status open. This is a risk rule needed before any real
  money, not a fix for this trade.

## 2. EURUSD Sell, opened 7 Oct 2026 13:00 UTC: still open when last seen

**Recorded from the dashboard on 9 Oct:**
- 0.04 lots;
- entry 1.11750;
- stop 1.12653, 90 pips: the 20-hour high, set before the drop;
- target 1.02588;
- −0.58 R (A$−30.04) at 1.12274.

**What happened, read from the dashboard chart** (hourly bars, approximate):
- the euro slid from about 1.1260;
- it then dropped sharply during the European morning of 7 Oct, the same French-bond selling as
  entry 1;
- it reached about 1.1175, and the bot sold there, at the bottom of the 20-hour range;
- the price then chopped for about a day and rallied back to about 1.1227.

If this trade closes at a loss, the bot writes its review prompt automatically.

**Update from the 13 Oct lookback:**
- still open, at +0.23 R;
- worst point −0.75 R;
- the entry was extreme: RSI 9, 3.43 ATR beyond the 20 EMA, and range position 1.08, i.e. sold below
  the 20-hour low just after a sharp fall.

## 3. GBPUSD Sell, 8 Oct 2026 01:00 UTC: −1.00 R (A$−53.18)

**Trade** (from the 13 Oct lookback):
- entry 1.32083;
- stop 1.32546 (4 × H1 ATR);
- best point +0.51 R at 10:00 on 8 Oct, then reversed;
- stopped out on 12 Oct at 06:28 UTC, with minimal slippage.

**Entry:**
- H4 strength 0.70;
- H1 momentum pointed against the sell, so that setup part scored 0 while the other three still
  passed the threshold;
- range position 0.72.

**Market** (ChatGPT, dated Reuters reports): sterling was supported by Bank of England rate
expectations. On 8 Oct more than 80% odds of a November rise were priced. On 9 Oct the dollar
weakened as oil and yields eased. No specific news was found for the 06:28 stop-out.

## Lookback review, 29 Sep – 13 Oct (ChatGPT, checked by Claude Code)

**Record:** 6 closed trades, +2.51 R, A$+57.35, +0.42 R per trade. That is inside the range the
research expectation allows for 6 trades (−0.85 to +0.93 R). The four EURUSD wins were really one
market episode, so the true sample is about 3 independent outcomes.

| ChatGPT finding | Check | Action |
|---|---|---|
| "Critical: four EURUSD trades broke the one-trade-per-pair rule" | **Wrong.** The rule was added on 1 Oct at 14:26 UTC because of those four trades (opened 09:00–12:00 UTC). No pair has had two open trades since. The prompt listed only today's rules. | Prompts now include a dated change history (`prompts/bot-changes.md`). |
| "The AI check approved the USDJPY buy although a BOJ interview was public" | **True, and structural.** The AI check is given no news at all, only the bot's own numbers, and is told missing news is neutral. The bot has no news awareness. | Descriptions corrected everywhere. Real event data stays test C4. |
| Trades #1–4 risked 2.6–4.8%, not 5% | Most likely the 0.01-lot rounding. With wide stops on A$1,000, 0.029 lots becomes 0.02; the widest stops show the lowest risk. | Prompts now show each trade's sizing steps: requested → after rounding and margin → AI → learning. |
| "structure = 1.17 exceeds its intended range" | **True.** The part is not capped at 1, so breakout closes score higher. | Documented in the prompts; capping is test C7. |
| All 8 trades bet on a stronger US dollar | **True.** All three pairs contain USD, so they are one bet. | US-dollar direction cap added and switched **on at 10%** (operator decision, 13 Oct); portfolio test C8. |
| Rejected signals and the AI's verdicts were missing | **True.** | The lookback now counts setups not traded, by reason, and the AI verdicts. |

## Patterns so far (3 losses and 4 related wins: still not evidence)

- **Entries come after the move.** Both the losers and the winners mostly entered at the 20-hour
  extreme, which is the design: the "structure" part rewards it, and without a cap. The research
  found random entries in the same trend did better than the bot's chosen entries: +0.087 R per
  trade against +0.055 R, 2021–2025.
- **Every trade so far was a bet on a stronger US dollar.** The bot follows the H4 trend, so in a
  dollar trend all three pairs point the same way.
- **The AI check adds no protection against news.** It has none to work with.

## Candidate tests

Each will be pre-registered with exact numbers before any data is run. The definitions marked (G)
are ChatGPT's, from the 13 Oct review.

| # | Idea | Rule | Status |
|---|---|---|---|
| C1 | Pullback and re-acceleration (G) | Keep the H4 trend filter. Enter only when the range position in the trade's direction is 0.40–0.70, the signed H1 MACD histogram is positive, and the last close moved the trade's way. This replaces the setup-score gate; stop and exits stay the same. | open |
| C2 | No chasing | Skip an entry when price moved more than X × ATR the trade's way in the previous 24 hours, or is more than Y ATR beyond the 20 EMA. | open |
| C3 | Session (G) | No new entries from 00:00 to 06:00 UTC. Report by pair and direction too. | open |
| C4 | Event risk (G) | No new entries from 2 hours before to 1 hour after high-impact releases or central-bank speeches for either currency. For USDJPY, also block for 12 hours after a timestamped BOJ or Ministry of Finance rate or FX headline. Needs point-in-time calendar and news history. | open: data source needed |
| C5 | Yen intervention risk | Cap risk on USDJPY buys while the price is in a recent intervention zone. A risk rule, needed before real money. | open |
| C6 | Stop buffer (G) | Stop at the 20-hour extreme ± 0.5 × ATR (0.25 and 1.0 as fixed sensitivity checks), with the size cut to keep the same A$ risk. | open |
| C7 | Cap "structure" at 1 | The same rules with the structure part capped at 1. | open |
| C8 | US-dollar direction cap (G) | Block a new trade if open risk in its US-dollar direction would exceed 8–10% of the balance. Built as `risk.max_usd_direction_risk_percent`, off. Pass: the 95th-percentile drawdown falls by at least 25% without hurting risk-adjusted growth. | **on at 10%** (operator decision, 13 Oct); the portfolio test is still owed |
| C9 | Exit variants (G) | Same entries; compare the current exit, a fixed 2 R target, and a 2 R or 4 R ATR trail. | open |

**Pass bar for C1–C3, C6, C7 and C9** (to be fixed per test before running):
- better net R than the current rules in both 2012–2018 and 2019–2026;
- positive at double costs;
- not dependent on USDJPY alone;
- better than matched random entries;
- confidence intervals clustered by market episode.

**Testing from Claude Code needs the Dukascopy price server.** This cloud environment's network
policy blocks `datafeed.dukascopy.com`.
