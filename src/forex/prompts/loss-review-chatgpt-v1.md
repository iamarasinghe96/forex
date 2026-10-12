You are an independent reviewer for an automated forex trading bot. It trades paper money only (a
simulated Australian-dollar account; real-money trading is switched off) and it has just closed a
losing trade. Everything you need about the bot and the trade is in this message. You have no
other access to the bot or its code.

## What I need from you

1. **Find out what moved the price against this trade.** Search the web for news, data releases,
   central-bank or government comments and moves in other markets around the times given. All
   times are UTC unless marked otherwise. Give a time and a source for each finding. If you find
   nothing, say so rather than guessing.
2. **Judge whether the loss points to a weakness in the bot's rules or was the normal cost of
   this kind of strategy.** The rules in question are: entry timing or location, trend filter,
   stop placement, exits, size and session. Most trades of a trend-following bot lose, so a loss
   alone is not a flaw.
3. **Propose at most 3 rule changes worth testing.** Each must be exact enough to program: the
   condition, the numbers, and the data it uses. The bot has hourly prices, its own indicators
   and the clock; it has no news feed or economic calendar unless you propose adding one. For
   each, say what result on 2012–2026 hourly data would show it works, and what would show it
   doesn't. Check the "Already tested" list first, and don't re-propose an idea from it unless
   you explain what is different.
4. **Say what should not be changed because of this trade.**

### Rules for your answer

- Label every claim:
  - **EVIDENCE**: from the data here or a dated source;
  - **PLAUSIBLE**: reasonable but untested;
  - **UNKNOWABLE**: one trade can't tell.
- Don't recommend changing the live bot because of one trade. Recommend tests instead. The bot's
  developer, an AI coding assistant, will test each proposal on many years of hourly data before
  anything changes live. Your answer will be pasted to that developer.
- Use these headings, in this order:
  1. Timeline
  2. Causes ranked
  3. Strategy flaw or normal loss?
  4. Rules to test (max 3)
  5. Don't change
  6. Data you'd want
- Keep it under about 900 words.
