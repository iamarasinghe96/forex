# Learning from losses (paper only)

After every losing trade, the bot writes a complete briefing for ChatGPT. You paste it into
ChatGPT and bring the answer to Claude Code. Claude Code checks the answer, records it in
[LOSS_LESSONS.md](LOSS_LESSONS.md), and tests any proposed rule on historical data before
anything changes live.

## What the bot does after a loss

About an hour after a losing trade closes, the bot writes the prompt. The delay lets it include
the exit hour's price bar. The prompt contains:

**Static parts.** These come from `src/forex/prompts/loss-review-chatgpt-v1.md`:
- how to answer: label each claim EVIDENCE, PLAUSIBLE or UNKNOWABLE; give at most 3 testable rules;
  use fixed headings;
- what the research has already tested and found.

**Generated parts:**
- **The bot's current rules,** with every number taken from the live settings:
  - entry: the trend filter and the four-part setup score;
  - stop, exits and size;
  - the AI pre-trade check, which sees only the bot's own numbers and no news;
  - how paper fills work.
- **The trade:**
  - times in UTC and in Sydney, Tokyo, London and New York;
  - entry, first stop, exit and target, in prices and pips;
  - the result in R and A$;
  - planned risk and slippage.
- **The bot's own record of why it entered:**
  - the H4 trend, the setup-score parts and the position in the 20-hour range;
  - its indicators;
  - its sessions and warnings;
  - the AI check's verdict;
  - the spread it paid.
- **Hourly prices** from a day before entry to the exit, in R. The hour that set the stop and the
  entry and exit hours are marked.
- **The market clock:**
  - the Tokyo fix, plus "gotobi" settlement days for yen pairs;
  - the Frankfurt, London and New York opens;
  - the usual US data time;
  - the London 4 pm fix;
  - the New York close (daily rollover).
- **The account:** closed trades with balances, and any other trades open at the time.

The prompt carries no account number, password or key.

**Delivery:**
- **Telegram:** a file named `loss-review-<PAIR>-<date>.txt`. Send `/loss` to get the latest one
  again.
- **Dashboard:** the "Learn from losses" section has **Copy prompt for ChatGPT** and **Download as
  a file** buttons, with the prompt shown underneath.

Nothing is sent to ChatGPT or any other AI service automatically, and trading does not change.

## What you do

1. Open the Telegram file and copy all the text, or share the file to the ChatGPT app. You can also
   tap **Copy** on the dashboard.
2. Paste it into ChatGPT and send.
3. Paste ChatGPT's whole answer into Claude Code.

## What Claude Code does with the answer

1. **Fact-checks it.** Claude Code checks each claim against the bot's code, its records and the
   research results, and removes anything wrong. Example: for the 7 Oct USDJPY loss, ChatGPT's
   news finding held up, and its own numbers showed that a stop buffer would not have saved the
   trade.
2. **Records it** in [LOSS_LESSONS.md](LOSS_LESSONS.md) as causes and rule proposals, each with a
   status. A cause that recurs across losses moves up the list.
3. **Pre-registers a test for each worthwhile rule.** The exact rule and the pass bar are written
   down before any result is seen. The test runs on 2012–2018 and 2019–2026 hourly data, at double
   costs, with and without USDJPY, and against random entries in the same trend.
4. **Only a passed test comes to you for approval** before the paper bot changes.

**Why there is no change after each loss:** a trend-following bot loses most of its trades, so a
rule tuned to one loss mostly fits noise. Every idea in the research list that looked good on the
data it was found in failed on fresh data.

**Data access:** running these tests from Claude Code needs the Dukascopy price server
(`datafeed.dukascopy.com`). This cloud environment's network policy currently blocks it. Allow
it under the environment's Network access settings, or run the test scripts on the PC.

## Looking back over all recent trades

Send `/lookback` to the Telegram bot. It sends back one file, `lookback-<date>-14d.txt`, reviewing
every trade of the last 14 days, winners as well as losers. Send `/lookback 30` for 30 days (up to
90). Paste it into ChatGPT (Deep Research works well), then paste the answer to Claude Code.

The file contains:
- **The instructions:** what went right and wrong per trade; patterns across trades; exits; risk
  and sizing; the comparison with the research; at most 5 testable rules.
- **The research so far and the bot's current rules.**
- **Results at a glance:** wins, losses and break-evens, total and average R, A$, win rate,
  profit factor, the largest fall from a balance high and the longest losing run.
- **The expected range:** what the research expectation allows for this many trades. For
  example, after 10 trades an average anywhere between about −0.65 R and +0.73 R is normal, so
  a few trades rarely prove anything.
- **Breakdowns** by pair, direction, session, exit, trend strength, entry location in the
  20-hour range and stop width.
- **Winners against losers** on what the bot measured at entry.
- **Trades open at the same time,** and how many were bets on a stronger US dollar.
- **One row per trade.** The latest 20 trades also get details: why the bot entered, the move
  before entry, the best and worst points while open, how much was given back, what happened
  after the exit, and a 4-hour price path.
- **The open trades now** and the market clock for the period, including daylight-saving changes.

Without the bot running: `python scripts/lookback_prompt.py --days 14` writes the same file
next to the paper database.

## Keeping the prompt accurate

- The rules section is generated from the live settings on every loss, so it stays current.
- The research section lives in `src/forex/prompts/research-so-far.md`, shared by the loss and
  lookback prompts. Claude Code updates it whenever a research result changes, so ChatGPT never
  re-proposes an idea that has already failed.

## Settings

`learning.loss_prompts: true` in `config.yaml`; set it to `false` to stop the prompts.

Prompts are written for losing trades that closed in the last 14 days. So after an update,
recent losses that have no prompt yet also get one.
