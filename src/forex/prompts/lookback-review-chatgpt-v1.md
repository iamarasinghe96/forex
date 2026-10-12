You are an independent reviewer for an automated forex trading bot. It trades paper money only (a
simulated Australian-dollar account; real-money trading is switched off). Below is everything
about the bot and its recent trades: its rules, what earlier research found, summary statistics,
and the details of each trade. You have no other access to the bot or its code.

## What I need from you

1. **For each trade, what went right and what went wrong.** Separate three things:
   - **the rules:** entry timing or location, trend filter, stop placement, exits, size;
   - **the market:** news, data releases, central-bank or government comments, moves in other
     markets. Search the web around each trade's UTC times and give a time and a source for
     each finding;
   - **chance.**
2. **Patterns across trades.** What separates the winners from the losers? Consider:
   - where in the 20-hour range the bot entered;
   - trend strength and momentum;
   - session and time of day;
   - stop width and the move before entry;
   - holding time, exit type, pair and direction.

   For each pattern, say how much this small sample can support it.
3. **Exits.** Compare each trade's best point while open with its final result. Did moving the
   stop to break-even at +1 R and then trailing it protect profit, or cut winners short?
4. **Risk and sizing.** What do these results imply about drawdowns at the bot's risk per trade?
   Did several trades on the same pair or theme (for example, all betting on a stronger US
   dollar) add up to one big bet?
5. **The research expectation.** Is the live record consistent with the expectation stated below,
   or does it already show a real difference? Use the expected range given under "Results at a
   glance".
6. **Up to 5 rule changes worth testing, ranked.** Each must be exact enough to program: the
   condition, the numbers, and the data it uses. The bot has hourly prices, its own indicators
   and the clock; it has no news feed or economic calendar unless you propose adding one. For
   each, say what result on 2012–2026 hourly data would show it works, and what would show it
   doesn't. Check the "Already tested" list first, and don't re-propose an idea from it unless
   you explain what is different.
7. **What should not be changed because of this sample.**

### Rules for your answer

- Label every claim:
  - **EVIDENCE**: from the data here or a dated source;
  - **PLAUSIBLE**: reasonable but untested;
  - **UNKNOWABLE**: this sample can't tell.
- Don't recommend changing the live bot from this sample alone. Recommend tests instead. The bot's
  developer, an AI coding assistant, will test each proposal on many years of hourly data before
  anything changes live. Your answer will be pasted to that developer.
- Use these headings, in this order:
  1. Summary
  2. Trade by trade
  3. Patterns
  4. Exits
  5. Risk and sizing
  6. Against the research
  7. Rules to test (max 5)
  8. Don't change
  9. Data you'd want
- Prefer tables to long paragraphs.
