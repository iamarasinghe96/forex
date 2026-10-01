# Learning loop (paper only)

The bot learns from its own closed paper trades and improves through changes you approve in
Telegram. No VPS login and no code editing are needed. Real-money trading stays disabled.

## What happens automatically

1. **Every closed trade is scored.** It is added to several "decision buckets": pair, H4 regime,
   session, trade style, volatility, pair + direction, pair + regime.
   - Score = total R / (trades + 20). The 20 imaginary break-even trades mean a bucket only
     becomes confident with many real trades; a few lucky wins cannot inflate it.
   - Confidence = trades / (trades + 20), so 20 trades is 50% and 80 trades is 80%.
2. **Every closed trade is explained.** The AI provider (Groq/Gemini/OpenRouter, the same ones
   used for news checks) writes why it won or lost and a lesson. Telegram receives:
   `Trade review: EURUSD SHORT WIN +1.45 R ... Why: ... Lesson: ... Score EURUSD|TREND_DOWN: 12 trades ...`
   If no provider answers, the score is still updated.
3. **Weak buckets trade smaller.** Once a bucket has 10+ trades and a negative score, new trades
   in it are scaled down (to as little as 25% of normal size). Strong buckets trade at full size.
   The learning loop never trades bigger than your configured risk: that stays the ceiling.

## Changing the strategy (you approve every change)

| Step | You do | The bot does |
|---|---|---|
| 1 | Send `/review` to the Telegram bot | Sends a file, `forex-learning-prompt.txt`, with the scoreboard, recent trade reviews, current settings and the rules for a valid reply |
| 2 | Open Claude, attach or paste the file, send it | - |
| 3 | Copy Claude's JSON block and paste it to the Telegram bot | Checks it against the allowed settings and bounds, then replies with "Change set #N" and the exact changes (e.g. `analysis.trend_efficiency_window: 10 -> 15`) |
| 4 | Send `/approve N` (or `/reject N`) | Saves the change; the running bot loads it within a minute and confirms "Strategy updated and running: ..." |
| 5 | If results get worse, send `/rollback` | Restores the previous settings |

Other commands: `/scores` (strongest and weakest buckets), `/settings` (current values),
`/help`.

## What a change set can and cannot do

**It can change, within fixed bounds:**
- trend and setup thresholds
- the volatility block and trend-detection speed
- which setups are allowed
- the exit target and trailing stop
- risk per trade (at most 5%)
- the learning settings
- paused pairs

**It cannot:**
- run code
- touch real-money or demo execution, credentials, the account or files
- change anything not listed above

Anything else makes the whole reply invalid.

Ideas that need new code (a new indicator or data source) go in `research_requests`. The bot
shows them to you but does not apply them. Bring them to Claude Code to implement and test.

**Why the reply is a settings change set and not code:** pasted Python would run on the VPS that
holds your MT5, Telegram and Firebase credentials. Anyone who got hold of the bot token, or a
single malformed reply, could then do anything there. A validated settings change set covers what
the learning loop needs: strengthening, weakening or pausing decisions.

## Security

- Only messages from your own Telegram chat (`FOREX_TELEGRAM_CHAT_ID` in `.env`) are read.
  Messages from anyone else are ignored.
- Approved settings are stored beside the paper account
  (`data/paper-a1000.strategy-overlay.json`), on top of `config.yaml`. A new paper account starts
  fresh.
- To switch the loop off, set `learning.enabled: false` in `config.yaml` and restart the bot.

## Reading the results honestly

One trade's explanation is a story, not evidence. The score is what changes behaviour, and it
needs dozens of trades per bucket to mean much. At about 2-3 trades a week, expect the first
buckets to pass 10 trades after a month or two. Prefer reviews that change one thing at a time,
so you can see what helped.
