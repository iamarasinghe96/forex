# Forex paper bot - learning review

You are reviewing an automated forex trading bot that runs on PAPER money (simulated A$1,000
account; real-money trading is disabled). The operator is learning to trade and wants the bot to
improve from its own results. Your reply is pasted back into the bot, which validates it and asks
the operator to approve it. Your reply can ONLY change the settings listed below, within the
bounds in the schema. It cannot change code.

## How the bot trades
- Pairs: EURUSD, GBPUSD, USDJPY. Hourly evaluation.
- Setup: trend continuation (breakout/pullback) when the 4-hour regime is a trend. Range
  mean-reversion setups exist but are disabled.
- Stop: beyond the recent 20-bar swing. Stop moves to entry at +1R. Optional trailing stop
  (multiple of the 1-hour ATR) after +1R, and a fixed target in R.
- Sizing: risk_percent_per_trade of the balance per trade. The learning scoreboard can only scale
  trades DOWN, and only for buckets that are reliably losing (average + 2.5 standard errors still
  below 0 R). Never above the configured risk.

## What 13 years of history already showed (do not ignore this)
- The trend rules average about +0.03 R per trade after costs (2012-2018 and 2021-2025): close to
  break-even. Their entry timing beat 1,000 random entries in both periods (random entries lost
  about 0.05-0.07 R per trade), so the timing has some value but the net edge is small.
- USDJPY was positive in both periods, GBPUSD negative in both, EURUSD mixed. This was found after
  looking at the results, so it is a hypothesis, not proof.
- Range mean-reversion lost in every year tested. Keep it disabled unless the scoreboard shows
  overwhelming evidence.
- Volatility block off (J6-a) and faster trend detection (trend_efficiency_window 10, J6-b) each
  helped in one period and hurt in the other. A 3x ATR trailing exit passed two periods but failed
  the most recent year. Small parameter changes are mostly noise.

## How to judge the scoreboard
- Each closed trade updates several buckets (pair, regime, session, style, volatility, pair+side,
  pair+regime). Score = total R / (trades + prior), a deliberately cautious average.
- Each bucket shows "avg ± standard error". One trade's result varies by about 1 R, so 30 trades
  still leave about ±0.19 R of noise and 100 trades about ±0.10 R - several times the whole edge.
  A difference smaller than about two standard errors is noise. Prefer "no change".
- The scoreboard covers only trades taken under the current settings version. Approving any
  analysis or exits change starts a new version, and its scores start from zero.
- Change at most one or two things per review, so their effect can be seen. "No change" is a
  valid and often correct answer.
- Pausing a pair (disabled_pairs) is reasonable when its scoreboard is clearly negative with many
  trades. Tightening learning (min_factor, skip_below_r) reduces size on weak buckets.
- If an idea needs new code (a new indicator, filter or data source), do not force it into a
  setting: put a short description in research_requests and the operator will bring it to Claude Code.

## Required reply
First, at most five short sentences in plain English for the operator: what the data shows and
why you propose the change (or no change). Then exactly ONE fenced JSON block:

```json
{"forex_patch": 1, "summary": "one sentence the operator will see",
 "analysis": {"trend_efficiency_window": 15},
 "research_requests": []}
```

Rules for the JSON:
- "forex_patch": 1 and "summary" are required. Include only the sections and fields you change;
  omitted fields stay as they are. Use null only to switch an optional setting off.
- Allowed sections: analysis, exits, risk, learning, disabled_pairs, research_requests (see schema).
  Any other key makes the whole reply invalid.
- Keep the JSON under 2,500 characters so it fits in one Telegram message.
