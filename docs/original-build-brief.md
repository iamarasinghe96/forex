# BUILD BRIEF — Production Automated Forex Trading System

You are building a production-grade automated Forex trading system from scratch. A working prototype exists (described below) but is being **replaced, not refactored**. Treat the prototype as a requirements document and a list of known failure modes, not as a codebase to preserve.

Read this entire brief before writing any code. Ask clarifying questions where the brief is genuinely ambiguous. Where the brief specifies *what* and not *how*, you choose the *how* — but state your choice and your reasoning before implementing it.

---

## 1. OPERATOR CONTEXT

The person running this system:

- Is based in Australia (NSW), trading in AUD, subject to ASIC retail rules
- Has **minimal programming knowledge**. They can run commands you give them, edit a config file, and read logs. They cannot debug your code.
- Will operate this on a Windows VPS they rent, unattended, 24/7
- Intends to trade **real money** on this system, starting small
- Has a working IC Markets MT5 demo account (login 23008397, server ICMarketsAU-Demo) and will open a live account later

Consequences for how you build:

- Every error message must state what went wrong **and what the operator should do about it**, in plain English
- All tunable values live in one config file, clearly labelled and commented. Nothing tunable is buried in code.
- The system must fail safe and fail loud. A silent failure that stops trading is acceptable. A silent failure that keeps trading on stale data is not.
- Assume the operator will not notice a problem for hours. Design for that.
- Write a `RUNBOOK.md` covering: first-time setup, daily operation, how to stop it immediately, what each alert means, and how to recover from each known failure mode.

---

## 2. WHAT THE PROTOTYPE DOES (requirements source)

Six Python modules, currently working end-to-end on demo:

1. **Data fetcher** — MT5 Python API, pulls 500 × H1 and H4 candles for EURUSD, GBPUSD, USDJPY every 4h to CSV
2. **Technical engine** — RSI(14), MACD(12/26/9), EMA50/200, ATR(14), support/resistance over 50 candles. Emits BUY/SELL/NEUTRAL with a score out of 8. ATR-based SL (1.5×) and TP (2.25×).
3. **News sentiment** — FinBERT (ProsusAI/finbert) over Yahoo Finance and Investing.com RSS, mapped to pairs by keyword, netted to a −1.0…+1.0 score per pair
4. **Scenario database** — matches upcoming economic calendar events (Forex Factory JSON feed) against a library of historical event archetypes, emits BULLISH/BEARISH/NEUTRAL + confidence
5. **Conviction engine** — weighted fusion (technical 50%, sentiment 25%, scenario 25%) into 0–100 score; approval rules; position sizing
6. **Executor** — places MT5 market orders, monitors every 15 min, moves SL to breakeven at 1:1 RR, logs closed trades to Google Sheets

### Trading profile to preserve

| Parameter | Value |
|---|---|
| Instruments | EURUSD, GBPUSD, USDJPY (majors). You may add other liquid majors/crosses if you justify it. |
| Timeframes | H1 and H4, with automatic day-trade vs swing-trade classification per setup (see §3.4) |
| Max leverage | 1:30 — **ASIC legal cap, not a preference. Hard limit, never exceed.** |
| Min reward:risk | 1.5:1 floor on every trade |
| Max concurrent positions | 4 |
| Max simultaneous risk | 20% of balance across all open positions |
| Daily loss circuit breaker | 12% of day-opening balance → flatten and halt until next session |
| Risk per trade | Conviction-scaled: 2% (55–69), 3.5% (70–84), 5% (85–100) |
| Entry threshold | Conviction ≥ 55, with no hard veto triggered (see §3.3) |
| Breakeven | Move SL to entry once 1:1 RR reached |
| Trailing stop | Implement, ATR-based, after breakeven — the operator wants upside captured, not just protected |
| Tax reserve | 32.5% of each closed profit, logged (AU: ordinary income, ATO TR 2014/1, no CGT discount) |

**Risk posture: aggressive by explicit instruction.** The operator accepts 10–20% drawdown months in pursuit of higher returns. Do not silently soften these numbers, and do not add extra caution layers that were not asked for. The circuit breaker, the RR floor, the leverage cap and the max-simultaneous-risk ceiling are the four controls that stay — everything else is tunable upward.

Note the arithmetic so it is explicit in config comments: at 5% per trade, an 8-trade losing streak is roughly a 34% drawdown. Streaks of that length occur in any strategy with a sub-60% win rate. The RR floor and the trailing stop are what make this survivable, which is why they are non-negotiable.

---

## 3. KNOWN DEFECTS — MUST NOT BE CARRIED FORWARD

These are not style issues. They are correctness failures in the prototype that you must fix by construction.

### 3.1 Fabricated constants

The prototype's scenario library contains values presented as historical measurements that were **invented, not measured**:

```
"avg_pip_24h": 55, "avg_pip_48h": 70, "win_rate": 71, "occurrences": 56
```

A source comment in that file claims derivation from Federal Reserve, BLS and academic data. That claim is false. Every number in it is fictional. The 90%-confidence signals the prototype produces are arithmetic performed on invented inputs.

Likewise, the position-sizing pip-value table:

```
PIP_VALUE_PER_MICRO_LOT_AUD = {"EURUSD": 0.13, "GBPUSD": 0.16, "USDJPY": 0.10}
```

These were guessed. They are the direct multiplier on every lot size the system calculates, so all sizing to date is wrong by an unknown factor.

**Requirements:**

- Do not port any numeric constant from the prototype without deriving or verifying it.
- Pip/tick value **must** be computed at runtime from MT5 symbol properties (`trade_tick_value`, `trade_tick_size`, `trade_contract_size`, `currency_profit`) and converted to account currency using the live cross rate. Never hardcode.
- The scenario module either (a) computes event statistics from real historical price data you fetch and process, showing sample size and methodology, or (b) is **omitted entirely** and its 25% weight redistributed. Choose one and say which. Do not ship a third option that looks like (a) but is (b).
- Any constant you cannot source must be labelled `# UNVALIDATED —` in code and listed in a `ASSUMPTIONS.md`. The operator must be able to see, in one place, every number the system's behaviour depends on that has no evidence behind it.

### 3.2 Unvalidated strategy — and your discretion to replace it

The prototype's indicator weights (RSI oversold = +2, golden cross = +1, threshold 5/8) and fusion weights (50/25/25) were chosen because they sounded plausible. No historical simulation has ever been run against them.

**You are not required to keep any of it.** The operator's instruction is explicit: you have deeper knowledge of trading system design than the prototype reflects, and you should choose the strategy. The list below is the *idea*, not the specification:

> Multi-signal confluence across technical structure, news sentiment and macro event context, fused into a single conviction score that scales position size, with ATR-derived stops and a hard reward:risk floor.

Within that idea, you decide everything: which indicators or price-action constructs, whether to use regime filters, mean-reversion vs trend-following vs a regime-switched blend, how to detect and avoid chop, session filtering, correlation handling between the three USD-quoted pairs, and how the layers combine. If you think a materially better approach exists — order-flow proxies, volatility regime models, breakout systems, whatever your judgement says — build that instead and explain why.

**Constraint on that freedom:** whatever you choose, its parameters must come from measurement, not intuition. Build it, backtest it (§6), report the numbers, tune from the numbers. This is *not* a caution requirement — it is how you find the high-return configuration the operator is asking for. Guessing weights is how the prototype ended up with an unmeasured edge.

### 3.3 Over-conservatism — the prototype took zero trades

Across a full week of live demo operation, the prototype approved **zero** trades. This is a defect and the operator wants it fixed.

Root causes, in order of severity:

1. **A fabricated layer polluted the fusion.** The scenario module (§3.1) returned 90%-confidence signals derived from invented data, which dragged the composite score away from the technical signal. Fixing §3.1 fixes much of this.
2. **A rigid unanimity rule.** The prototype required technical, sentiment and scenario to all agree. Three independent signals rarely agree, so the gate almost never opened.
3. **A threshold set without reference to the score distribution.** 65/100 was picked arbitrarily and happened to sit above where most scores land.

**Requirements:**

- Replace unanimity with **graded agreement**: partial agreement is tradeable at reduced size; only a strong, high-confidence *opposing* signal constitutes a veto. Conflicting-but-weak signals should shrink size, not block the trade.
- Keep the hard vetoes short and justify each one. Reasonable candidates: stale data, market closed or close-only, circuit breaker active, RR floor unmet, max exposure reached, spread abnormally wide. Signal disagreement is **not** on that list.
- **Calibrate the threshold against the actual score distribution**, don't pick a round number. Run your scoring over historical data, look at where scores actually fall, and set the entry threshold to produce a target trade frequency. Make the target frequency a config value; start it around 3–8 trades per week across the three pairs and let the operator tune it.
- Report, in the backtest output, how many signals each individual gate rejected. If any gate is rejecting more than ~40% of otherwise-valid setups, flag it as miscalibrated rather than leaving it in place.

### 3.4 Automatic day-trade vs swing-trade classification

Both styles are traded, and the system decides which per setup — the operator does not choose. At minimum the classifier determines: which timeframe's signal drives the entry, stop and target distances (ATR multiples should differ by style), expected hold duration, whether the position is allowed to carry overnight or over a weekend, and how the trailing stop behaves.

You design the classifier. An H4/Daily-driven signal with wide structure implies a swing hold of days to weeks; an H1-driven signal with tight structure implies an intraday hold. Handle the case where both timeframes signal simultaneously — decide whether that is one high-conviction trade or two independent positions, and justify it against the correlation rules.

### 3.5 Fragile state

The prototype tracks open positions in a JSON file that can desynchronise from MT5 on any crash or restart, and can double-place orders. See §7.3.

---

## 4. ARCHITECTURE

Layered, with hard interfaces between layers. Each layer independently testable with the layers below it mocked.

```
  L0  Infrastructure   config, secrets, logging, persistence, alerting, scheduler
  L1  Broker Adapter   abstract interface; MT5 implementation
  L2  Market Data      candles, ticks, symbol specs, calendar, news
  L3  Analysis         indicators, sentiment, (scenario), regime detection
  L4  Reasoning        LLM rationale + decision review
  L5  Fusion           conviction scoring
  L6  Risk             sizing, exposure, circuit breakers, kill switch
  L7  Execution        order placement, position management, reconciliation
  L8  Journal          trade log, tax reserve, performance reporting
  L9  Backtest         historical replay of L2→L7 against the same code paths
```

**Non-negotiable:** the backtester must exercise the *same* strategy, fusion and risk code as live trading. If backtest and live have separate implementations of the decision logic, the backtest is worthless. Design L3–L6 as pure functions over a market-state object so both drivers can call them.

### 4.1 Broker adapter

Even though the deployment target is MT5, define an abstract broker interface (connect, symbol spec, candles, tick, place order, modify, close, open positions, account state, history) and implement MT5 behind it. Rationale: MT5 is Windows-only, and if the operator later moves to a REST-API broker for cheaper Linux hosting, only the adapter changes.

### 4.2 Language and stack

Python is effectively mandatory — the MetaTrader5 binding is Python-only and Windows-only. Beyond that, you choose: dependency management, typing strategy, async vs threaded, data layer, test framework. State your choices and why. Bias toward boring, well-supported libraries over clever ones; the operator cannot debug an exotic stack.

---

## 5. LLM REASONING LAYER

The LLM performs **full trade rationale and decision review**.

### 5.1 Role

For each candidate trade, given a structured market-state payload (indicator values, sentiment scores, calendar context, account state, proposed entry/SL/TP/size), the LLM:

1. Produces a written rationale for the trade in plain English
2. Independently reviews the proposal and returns a structured verdict: `approve` / `reject` / `reduce_size`, with reasons
3. Flags any inconsistency it detects between layers (e.g. technicals bullish while sentiment and calendar are bearish — the exact conflict the prototype hit)

### 5.2 Constraint on LLM authority

The LLM may **veto or reduce**. It may **not increase** position size beyond the deterministic calculation, loosen a stop, or widen a risk limit. Enforce structurally: the risk engine takes the *minimum* of deterministic and LLM-adjusted size.

This is deliberately narrow and costs nothing in return terms — the deterministic sizing is already aggressive (up to 5%), so the ceiling is high. The reason for the constraint is reproducibility, not caution: LLM output varies run to run, so if it sat on the path that can *enlarge* exposure, no two identical market states would risk the same amount and the backtest would tell you nothing about live behaviour. Vetoes and reductions are safe because they only ever move toward a smaller, knowable bound.

The LLM's veto should also be used sparingly — see §3.3. Prompt it to reject only on clear, articulable grounds, not on general unease. An LLM asked "is this trade risky?" will say yes to almost anything; ask it instead to identify specific disqualifying conditions.

### 5.3 Provider redundancy

Three providers with automatic failover. Suggested ordering — verify current pricing and free-tier limits yourself rather than trusting any figures quoted to you, as they change frequently:

- **Groq** — fastest inference, cheapest at volume; good primary for high-frequency classification
- **Google Gemini** — strong reasoning, generous free tier; good primary for review/rationale
- **OpenRouter** — gateway to many models behind one key; good as failover tier since it can route around a single provider outage

Requirements:

- Single internal interface; providers are pluggable and ordered by config
- Failover on timeout, rate limit, 5xx, malformed output, or schema validation failure
- **All LLM output is structured JSON validated against a schema.** Reject and retry on validation failure; after N failures, fail over; after all providers fail, fall back to deterministic-only mode and alert the operator. Never parse free text with regex.
- Per-call and cumulative cost tracking, logged and reported daily
- Response caching keyed on a hash of the input payload (identical market state should not be re-billed)
- Prompt templates versioned in the repo, not inline strings. A prompt change is a strategy change and must be traceable in the trade journal.
- Record which provider and model produced each decision, in the journal

### 5.4 Sentiment

Replace or retain FinBERT at your discretion. FinBERT is free, local, deterministic and purpose-trained for financial text; an LLM call is more flexible but costs money per headline and is non-deterministic. Consider FinBERT for bulk headline scoring with the LLM reserved for the review layer. Justify whichever you pick. Note the ~2 GB RAM cost if you keep FinBERT — it must fit the VPS.

---

## 6. BACKTESTING AND VALIDATION

Build this properly even though it does not gate execution.

- Replay ≥ 5 years of historical H1/H4 data through the identical L3–L6 code path
- Model costs realistically: spread (variable, not fixed), commission, slippage, swap/rollover on overnight holds
- Bar-level fill logic that does not look ahead. If SL and TP are both inside one bar, resolve pessimistically.
- Walk-forward analysis: optimise on in-sample windows, evaluate on out-of-sample, roll forward. Report both.
- Metrics: total return, CAGR, win rate, profit factor, expectancy per trade, max drawdown (depth and duration), Sharpe, Sortino, longest losing streak, trade count, average hold time — reported per pair and per timeframe as well as aggregate
- Monte Carlo trade-order shuffling to show the drawdown distribution, not just the single realised path
- Output a readable HTML or Markdown report with an equity curve
- The LLM layer cannot be backtested faithfully (no historical model outputs). Run backtests deterministic-only and state clearly in the report that live results will differ because of it.

Also implement a **paper mode**: full live data, full decision path, orders simulated not sent. This must be a single config flag, and the mode must be printed prominently in every log line header and every alert so the operator can never be unsure which mode is running.

---

## 7. OPERATIONAL RESILIENCE

The prototype broke repeatedly on operational issues, not strategy issues. These are the real ones encountered — handle every one explicitly.

### 7.1 MT5 quirks (all hit in testing)

- **Retcode 10027** `AutoTrading disabled by client` — the Algo Trading toggle in the MT5 UI is off. Detect at startup, refuse to run, tell the operator exactly which button to press.
- **Retcode 10030** `Unsupported filling mode` — filling mode varies by symbol and server. Read `symbol_info.filling_mode` and select correctly; fall back through FOK/IOC/RETURN. Do not hardcode.
- **Retcode 10044** `Only position closing is allowed` — broker-side close-only state. Detect, halt new entries, alert, retry on a backoff. Distinguish this from a code fault in the alert text so the operator does not go hunting through Python.
- **Minimum stop distance** — `symbol_info.trade_stops_level` and `trade_freeze_level`. Reject or adjust SL/TP that violate it *before* sending, rather than eating a rejection.
- **Symbol naming** — brokers append suffixes (`EURUSD.a`, `EURUSD-ECN`). Resolve symbol names dynamically; never assume the bare name exists. Call `symbol_select()` before use.
- **Volume constraints** — respect `volume_min`, `volume_max`, `volume_step`. Round down, never up.
- **Hedging vs netting** — this account is Hedge mode. Handle both; detect from account info.

### 7.2 Time

The prototype had timezone bugs. Handle rigorously:

- Broker server time ≠ UTC ≠ Sydney local. Store everything in UTC internally; convert only at display.
- Use timezone-aware datetimes throughout (`datetime.now(timezone.utc)`). The deprecated `utcnow()` must not appear anywhere.
- Handle daily rollover, weekend closure, market holidays, and the Sunday open gap. Do not trade into a known closure. Do not treat a weekend candle gap as a signal.
- DST shifts on both the broker server and the operator's local time

### 7.3 State and idempotency

- The MT5 terminal is the **single source of truth** for open positions. Local state is a cache, never authoritative.
- Reconcile against MT5 on every startup and on a schedule. Any divergence: trust MT5, log loudly, alert.
- Tag every bot order with a magic number and a deterministic client-side identifier so a restart mid-placement cannot double-fill.
- Persist to something transactional (SQLite is sufficient and dependency-free), not a JSON file that can be half-written when the process dies.
- A crash and restart must resume cleanly: positions still tracked, breakeven logic still armed, circuit-breaker day state intact.

### 7.4 Failure handling

- MT5 disconnect: exponential backoff reconnect, halt trading while disconnected, alert if down beyond a threshold
- Stale data guard: refuse to act on candles older than a configurable age. A stalled feed must never produce a trade.
- News/calendar feed failure: degrade gracefully to remaining signals, do not crash (Reuters RSS already fails in the operator's environment — DNS resolution failure — treat feed sources as individually optional)
- API rate limits: backoff and failover
- VPS reboot: the system must start automatically on boot (Windows Task Scheduler or NSSM service) and self-recover with no operator action

### 7.5 Kill switch

An out-of-band mechanism — a sentinel file, or a Telegram command — that halts new entries immediately, independent of the running process's health, with an option to flatten existing positions. The operator must be able to stop the system from their phone without remote-desktopping into the VPS.

---

## 8. OBSERVABILITY

- Structured logging (JSON lines), rotated, with human-readable console output in parallel
- Every trade decision — taken *and* rejected — persisted with full inputs, the deterministic score, the LLM verdict and rationale, and the reason for the outcome. The operator must be able to reconstruct any decision after the fact.
- Push alerts to the operator's phone (Telegram bot is simplest and free) for: trade opened, trade closed, circuit breaker fired, close-only state detected, MT5 disconnected, all LLM providers down, stale data halt, unhandled exception
- Daily summary: trades, P&L, running balance, tax reserve accrued, LLM spend, errors
- Health endpoint or heartbeat so a watchdog can detect a hung process, not just a crashed one
- Alert when the bot takes **no trades for longer than a configured window** — given §3.3, silence is a symptom, not success

---

## 8A. DATA BACKEND AND DASHBOARD

Google Sheets is **removed**. Replace with Firestore as the system of record and a hosted web dashboard as the operator's interface.

### 8A.1 Write path

```
  Bot (Windows VPS)
        │  Firebase Admin SDK, service account
        ▼
  Local SQLite  ──async sync──►  Firestore
   (authoritative,                (cloud mirror,
    survives outage)               powers dashboard)
```

- **Write locally first, always.** A Firestore outage or network drop must never block a trade or lose a record. Queue and replay on reconnect.
- Reconciliation job to detect and repair local/cloud divergence
- The bot uses the Firebase Admin SDK with a service account. That credential is a full-access key — VPS only, never in the repo, never in the browser bundle.

### 8A.2 Firestore structure

Design the schema, but it must support: every trade (open and closed) with full decision provenance; every *rejected* signal with its reason; daily and cumulative performance aggregates; account balance history; LLM cost tracking; system health and error events; and the tax reserve ledger.

Precompute aggregates on write rather than having the dashboard scan the trade collection — Firestore bills per document read and a dashboard that re-aggregates on every page load gets expensive fast. Add composite indexes for the queries the dashboard actually issues.

Trade records retain the full prototype field set: dates opened/closed, pair, direction, timeframe, trade style (day/swing), entry, exit, lots, pips, P&L AUD, running balance, tax reserve @32.5%, conviction score and component breakdown, LLM verdict and rationale, provider/model used, and rejection reason where applicable. This doubles as the ATO evidence trail, so it must be exportable to CSV.

### 8A.3 Dashboard

Static web app, hosted free on **GitHub Pages**. Built for a non-programmer: this is how the operator checks the bot from their phone, so mobile-first, no jargon, and the important numbers visible without scrolling.

Must show:

- **Now** — bot running or stopped, live/paper mode, MT5 connection state, open positions with live P&L, current balance and equity
- **Performance** — equity curve, cumulative P&L, win rate, profit factor, average win vs average loss, max drawdown, current streak. Filterable by pair, timeframe, trade style and date range.
- **Trade history** — sortable, searchable table; tap a trade to see the full rationale, conviction breakdown and LLM verdict that produced it
- **Rejected signals** — what the bot *didn't* trade and why. This is the operator's main tool for diagnosing over-conservatism (§3.3), so make it prominent, not buried.
- **Tax** — accrued reserve, financial-year totals, CSV export
- **Health** — recent errors, LLM spend, alert history
- **Controls** — kill switch (halt new entries; flatten all) exposed as a button, gated behind auth and a confirmation step. This must work from a phone without remote-desktopping into the VPS.

Framework is your choice. Prefer a static build that deploys to GitHub Pages via GitHub Actions on push. Firebase Auth restricts access to the operator's account only — this is financial data on a public URL, so Firestore security rules must deny all client reads by default and grant only to that authenticated UID. Never ship the Admin SDK or any service-account key to the browser.

### 8A.4 Vercel

Use Vercel serverless functions for anything that must not run client-side: operations needing elevated privilege, any third-party API call whose key must stay secret, and the kill-switch endpoint (which the bot polls or subscribes to). Keep the split clear — if a thing can be done safely with Firestore security rules and the client SDK, do it there; reach for Vercel only when a secret or elevated privilege is genuinely involved.

---

## 8B. CREDENTIALS AND INPUTS REQUIRED FROM THE OPERATOR

**Your first task after the architecture discussion is to ask the operator for these, one group at a time, in the order you need them.** Do not ask for all of it upfront — request each group at the layer that consumes it, explain what it is for, and give click-by-click instructions for obtaining it. The operator is not a programmer and has not used most of these consoles.

Required:

| Group | Items | Where it comes from |
|---|---|---|
| **Broker** | MT5 login, password, server name, account currency, hedging/netting mode | IC Markets account (demo held; live to follow) |
| **LLM providers** | Groq API key, Google Gemini API key, OpenRouter API key | Each provider's console; all three, for failover |
| **Firebase** | Project ID, Admin SDK service-account JSON (for the VPS bot), Web app config object (for the dashboard client) | Firebase console → Project settings |
| **Auth** | The operator's Google account email, for the dashboard's allowed-user rule | — |
| **Alerting** | Telegram bot token + chat ID | @BotFather in Telegram |
| **Deployment** | GitHub repo name, GitHub Pages settings, Vercel project + token | GitHub and Vercel |
| **Config choices** | Starting capital, live vs paper on first run, target trade frequency, risk tier confirmation | Operator decides |

Optional, ask only if your design needs it: a historical data source beyond MT5's own history (MT5 candle depth varies by broker and may be insufficient for a 5-year backtest — check first and tell the operator what you found before asking them to buy anything), and an economic calendar feed if you improve on the free Forex Factory JSON endpoint.

**Handling rules.** Everything above goes in `.env` or a secrets manager, never in code and never in the repo — `.gitignore` before the first commit. The Firebase Admin service-account JSON is the single most dangerous credential here: it grants full database access and belongs only on the VPS. The operator has previously pasted a service-account private key into a chat window, so state this explicitly when you request it, and include key rotation in the runbook.

---

## 9. DEPLOYMENT TARGET

Windows VPS (~AU$45/month tier, 2 vCPU / 4 GB RAM / 100 GB, Sydney region for latency to IC Markets' AU servers).

Deliver:

- Setup script or precise step-by-step for a non-programmer: Python install, dependency install, MT5 install and login, credentials configuration, service registration
- Auto-start on boot, auto-restart on crash
- Log rotation so the disk does not fill
- Backup of the database and journal
- Secrets in environment/.env, never in code, never in the repo. `.gitignore` from the first commit. Note: the operator has previously pasted a Google service-account private key into a chat — include a short section in the runbook on what must never be shared and how to rotate a leaked key.
- Update procedure that does not require the operator to understand git

---

## 10. ENGINEERING STANDARDS

- Clear repo structure with separated concerns; no 8000-line files
- Type hints throughout; mypy or equivalent in CI
- Tests: unit tests for indicators (against known-good fixtures), risk math, and sizing; integration tests against a mocked broker; a full backtest as a regression test. Position sizing and circuit-breaker logic need the heaviest coverage — they are what stands between a bad signal and a large loss.
- Docstrings written for a non-programmer, per the prototype's convention
- Deterministic where possible: given identical inputs, the non-LLM path must produce identical outputs
- No secrets, no fabricated data, no silent exception swallowing

---

## 11. BUILD SEQUENCE

Do not build everything at once. Deliver in layers, each independently runnable and verifiable by the operator before you proceed. Explain each layer in plain English **before** you build it, and tell the operator what success looks like and how to check it.

1. **Foundation** — repo, config, secrets, logging, local persistence, Telegram alerting, broker interface + MT5 adapter, symbol spec resolution, correct tick-value computation. Verification: connect, read account, resolve all three symbols, print correct pip value per lot in AUD.
2. **Market data** — candles, gap handling, staleness detection, historical download for backtesting. Report actual available history depth before proceeding.
3. **Strategy** — your chosen approach (§3.2) as pure functions with fixture tests; sentiment; regime detection; day/swing classifier
4. **Backtest engine** — replay layer 3 through the risk layer, produce the metrics report, calibrate thresholds against the score distribution (§3.3). *This is where the strategy's parameters get set from data instead of guesswork.*
5. **Fusion + risk** — conviction scoring, aggressive sizing tiers, exposure limits, circuit breakers, trailing stops, kill switch
6. **LLM layer** — provider abstraction, three-way failover, schema validation, review constraints, cost tracking
7. **Execution** — order placement with full retcode handling, position management, breakeven, trailing, reconciliation
8. **Firestore + journal** — schema, local-first write path, async sync, aggregates, reconciliation
9. **Dashboard** — static app, Firebase Auth, security rules, GitHub Actions deploy to Pages, Vercel functions, kill-switch control
10. **Paper mode soak** — end-to-end on live data with simulated fills; confirm trade frequency is in the target band before going live
11. **Deployment** — VPS, service registration, auto-restart, runbook

At the end of each layer, stop and report: what was built, what was verified, what remains unvalidated, and what the operator should check before you continue.

---

## 12. FIRST RESPONSE

Before writing code, respond with:

1. **Your proposed trading strategy** (§3.2) — what you would build and why, given that the operator wants high returns and accepts 10–20% drawdown months. Be specific and be opinionated; this is the part of the brief where your judgement is explicitly wanted over the operator's.
2. Your stack and architecture choices, with reasoning
3. Anything in this brief you think is wrong, risky or internally inconsistent. Say so directly and once — the operator has already considered and rejected a more conservative posture, so make your case on engineering grounds rather than repeating a caution they have heard. Do not build something you think is broken just because it was specified.
4. Your open questions
5. Your proposed structure for Layer 1, and which credentials from §8B you need to start

Then build Layer 1 only, and stop.
