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

## Patterns so far (2 trades: not evidence yet)

**Both entries came after the move, at the extreme of the 20-hour range.** The bot bought the top
after a rally and sold the bottom after a fall. This is by design: the setup score's "structure"
part rewards buying at the top of the range and selling at the bottom. The research already
found that random entries in the same trend did better than the bot's chosen entries:
+0.087 R per trade against +0.055 R, 2021–2025. Entry location is therefore the first idea to
test.

## Candidate tests

These are drafts. Each will be pre-registered with exact numbers before any data is run.

| # | Idea | Rule (draft) | Status |
|---|---|---|---|
| C1 | Pullback entries | Uptrend: buy only when the H1 close is in the lower half of the 20-hour range or within 0.5 ATR of the 20 EMA. Downtrend: the mirror image. Stop and exits as now. | open |
| C2 | No chasing | Skip an entry when price moved more than X × ATR in the trade's direction over the previous 24 hours. | open |
| C3 | Session | Compare entries at 03:00–06:00 UTC (the Asia-to-Europe hand-over) with other hours. | open |
| C4 | Scheduled news | Skip new entries for N hours around high-impact releases for the pair's currencies. Needs a source of past economic-calendar data. | open |
| C5 | Yen intervention risk | Cap risk on USDJPY buys while the price is in a recent intervention zone. A risk rule, before real money. | open |

**Pass bar for C1–C4** (to be fixed per test before running):
- better net R than the current rules in both 2012–2018 and 2019–2026;
- positive at double costs;
- not dependent on USDJPY alone;
- better than matched random entries.
