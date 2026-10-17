**Changes to the live bot since this paper account started**

Judge each trade by the rules in force when it was opened. All times are UTC.

- **1 Oct 2026, 00:28:** a fresh A$1,000 paper account started.
- **1 Oct, before 09:00:** the current aggressive profile took effect:
  - 5% risk on every trade, with no confidence floor;
  - the volatility block off, and faster trend detection (10 H4 bars);
  - a 10 R target, break-even at +1 R, then a 3 × ATR trailing stop.

  The learning loop also started. It changes size only after 10 or more trades in a group, so it
  has not acted yet.
- **1 Oct, 14:26: limit of one open trade per pair.** It was added because four EURUSD sells had
  opened one per hour from 09:00 to 12:00 that day, as no such limit existed. Those four are the
  only stacked trades in this account; no pair has had two open trades since.
- **4 Oct:**
  - **Margin cap:** a trade is cut to what free margin allows at 30:1 leverage.
  - **H4 bars:** built from H1 bars at fixed UTC hours (00/04/08/12/16/20) instead of the broker's
    day boundary. Settings version 4977cb76 dates from this change, so earlier trades show another
    version.
  - **Shadow setup score:** recorded only, never used.
- **5–13 Oct:** dashboard charts and the review prompts. No change to trading.
- **From the update installed after 13 Oct: US-dollar direction cap of 10%.** A new trade is
  blocked if open risk betting the same way on the US dollar, plus its own risk, would exceed 10% of
  the balance; trades already at break-even count as 0. In practice that means at most two full 5%
  trades betting the same way on the dollar. Blocked setups appear as "US-dollar direction risk cap
  reached".
- **From the update installed after 17 Oct: no entry strategy (scoring only).** The account had
  fallen to about A$955, and the operator switched the old trend strategy off to design a new one.
  - The hourly analysis still runs; its readings are published as scoring tools.
  - Trades opened earlier keep their stops and exits until they close.
  - No new trades open until a new strategy is switched on.
- **From the update installed after 17 Oct: previous-day high/low tool (scoring only).**
  - Each hourly scorecard also shows the previous forex day's high and low (17:00–17:00 New York),
    the type of day it was, the distance to each in ATRs, and what today has done around them.
  - `/levels` measures how price behaved around these levels over the stored history.
  - It does not trade.

**Sizing note.** Trades are sized in steps of 0.01 lots, always rounded down so the risk never
exceeds the budget. On a A$1,000 account with wide stops this can cut the planned 5% a lot. For
example, 0.029 lots becomes 0.02, about a third less risk. Wider stops therefore often mean less
than 5% at risk.
