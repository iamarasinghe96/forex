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
  - the AI news check;
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
  - the AI news check's verdict;
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

## Keeping the prompt accurate

- The rules section is generated from the live settings on every loss, so it stays current.
- The research section lives in the prompt file. Claude Code updates it whenever a research
  result changes, so ChatGPT never re-proposes an idea that has already failed.

## Settings

`learning.loss_prompts: true` in `config.yaml`; set it to `false` to stop the prompts.

Prompts are written for losing trades that closed in the last 14 days. So after an update,
recent losses that have no prompt yet also get one.
