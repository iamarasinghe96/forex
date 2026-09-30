# Learning resources (researched 2026-09-30)

A study path for the operator, chosen for reputation among traders, relevance to this bot's
methods, and honesty about risk. Ratings are quoted only where a source was checked; "widely
recommended" means it appears repeatedly on practitioner reading lists. None of these resources
is paid by or connected to this project.

## Reality check first

- **Australian regulator data:** ASIC's reviews (2017, 2019, 2020) found only **32% of retail
  CFD clients made money after fees**, and only **19%** of the most active (50+ trades a month).
  ASIC's 2021 product intervention (lower leverage and related protections) cut aggregate retail
  losses by about 91%. Source: ASIC media releases 21-060MR and 22-082MR; FX News Group summary.
- **Costs matter more than entries for small accounts:** Robert Carver reports that a large UK CFD
  and spread-betting provider earned about US$1,379 revenue per customer while customers averaged
  about US$500 on deposit - the broker's revenue is the customer's cost. Source: *Leveraged Trading*
  reviews (Goodreads, followingthetrend.com).

## Suggested order

| Step | Resource | Why it matters for you / this bot | Reputation (checked) |
|---|---|---|---|
| 1. Basics | **BabyPips "School of Pipsology"** (free, online) | Forex vocabulary, pips, lots, leverage, orders, sessions; useful calculators. | Widely called the best free starting point. Caveats: beginner level only; text-heavy; funded by broker affiliate links. |
| 2. Chart reading | **John J. Murphy, *Technical Analysis of the Financial Markets*** | The standard reference for trends, support/resistance, moving averages, oscillators - every term in Journal entries 1-3. | Classic; on most technical-analysis reading lists. |
| 3. Multi-timeframe | **Brian Shannon, *Technical Analysis Using Multiple Timeframes*** (2008) | Exactly the topic of Journal entries 1-3: trend context on higher timeframes, entries on lower ones, market structure. | Reviewers call it a clear, practical "real trader" book; intermediate level. |
| 4. Candles | **Steve Nison, *Japanese Candlestick Charting Techniques*** | Background for entry triggers (engulfing, hammer-type candles; idea J3-a). | The original Western candlestick reference; on professional lists. |
| 5. Risk and expectancy | **Van K. Tharp, *Trade Your Way to Financial Freedom*** | R-multiples, expectancy, position sizing - the language all our test results use. | Reviews highlight its rigorous case that sizing and expectancy matter more than entries. |
| 6. Trend following | **Andreas F. Clenow, *Following the Trend*** (2nd ed. covers 2002-2021) | Honest year-by-year view of a diversified trend-following strategy, including bad years; explains why simple rules plus diversification, not clever entries, carry the results. | Praised as written by a practitioner, not a theorist. Note: its backtests are on many futures markets, not three FX pairs. |
| 7. Small leveraged accounts | **Robert Carver, *Leveraged Trading*** (FX, CFDs, spread bets) | The most directly relevant book for a small IC Markets CFD account: realistic returns, costs, leverage, simple systems. | Described by a reviewing author as the only good book on leveraged trading of small portfolios. |
| 8. Testing honestly | **David Aronson, *Evidence-Based Technical Analysis*** | Scientific testing, data-mining bias and out-of-sample checks - the method we used when ideas failed. Finds that many profitable-looking rules were data-mining artefacts. | Academic-level; author is a Chartered Market Technician and adjunct professor. |
| 9. Psychology | **Mark Douglas, *Trading in the Zone*** | Discipline, thinking in probabilities, accepting losses; matters once you trade yourself. | Goodreads 4.31 average from about 10,400 ratings. |
| 10. Inspiration and variety | **Jack Schwager, *Market Wizards*** series | Interviews with successful traders across very different styles; common themes are risk control and discipline. | Goodreads 4.28 (about 10,800 ratings) for the original; series books 4.26-4.37. Survivorship caveat: these are the winners. |

## Reference material (look things up as needed)

- **Perry J. Kaufman, *Trading Systems and Methods*** - encyclopedic reference; source of the
  **Efficiency Ratio** (net move divided by total path travelled; 1 = straight line, near 0 =
  choppy) and **KAMA**. Our bot's "directional efficiency" is the same idea.
- **Moskowitz, Ooi and Pedersen, "Time Series Momentum"**, *Journal of Financial Economics* 104(2),
  2012 (free PDFs via AQR / NYU Stern). The key academic evidence for trend following: across 58
  futures markets including currencies, returns persisted over **1 to 12 months**, then partly
  reversed. Note the horizon: months, not the hours our bot trades.
- **Curtis Faith, *Way of the Turtle*** - the Turtle traders' breakout rules and their
  position-sizing logic; the classic example of a fully mechanical trend-following system.
- **Michael Covel, *Trend Following*** - popular history of trend-following funds. Read with care:
  promotional in tone.
- **Carry trade / yen funding currency** - explanations from brokers and research notes (e.g.
  AMRO analytical note, Dec 2024). Explains why USDJPY can trend for long periods when US rates are
  well above Japanese rates, and why those trends can reverse suddenly when the carry unwinds.

## Things to avoid

Courses, signal groups or bots that promise weekly or monthly percentage returns; "secret"
indicators; anything that shows only winning examples. Every credible resource above spends much
of its length on losses, costs and risk.

## Sources checked

- ASIC: https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2021-releases/21-060mr-asic-s-cfd-product-intervention-order-takes-effect/
- ASIC: https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2022-releases/22-082mr-asic-s-cfd-product-intervention-order-extended-for-five-years/
- FX News Group: https://fxnewsgroup.com/forex-news/regulatory/asic-extends-cfd-trading-restrictions-for-five-years-as-retail-losses-reduced-91/
- BabyPips reviews: https://takeprofitapp.com/en/learn/babypips-school-of-pipsology-review , https://learntotrades.com/course-reviews/babypips-review/
- Reading lists: https://tradingengineered.substack.com/p/the-best-trading-books-for-new-traders , https://samirdash.substack.com/p/best-resources-to-learn-trading
- Shannon: https://seekingalpha.com/article/134296-book-review-brian-shannons-technical-analysis-using-multiple-timeframes
- Tharp: https://traderlion.com/trading-books/trade-your-way-to-financial-freedom/ , https://www.earnforex.com/guides/book-review-trade-your-way-to-financial-freedom-by-van-k-tharp/
- Clenow: https://www.followingthetrend.com/the-book/ , https://tradermarkus.com/andreas-f-clenow-following-the-trend-review/
- Carver: https://www.followingthetrend.com/2019/12/leveraged-trading/ , https://www.goodreads.com/book/show/48611879-leveraged-trading
- Aronson: https://www.wiley.com/en-us/Evidence-Based+Technical+Analysis:+Applying+the+Scientific+Method+and+Statistical+Inference+to+Trading+Signals-p-9781118268315 , https://strategyquant.com/blog/short-review-of-the-book-evidence-based-technical-analysis-and-its-possible-implications-for-sq-x-strategy-development/
- Douglas: https://www.goodreads.com/book/show/253516.Trading_in_the_Zone
- Schwager: https://www.goodreads.com/series/353625-market-wizards
- Kaufman: https://ta-lib.org/functions/er.html , https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama
- Time series momentum: https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum , https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Carry trade: https://www.amro-asia.org/wp-content/uploads/2024/12/20241219-Analytical_Note_Carry_Trade.pdf , https://www.tastyfx.com/news/what-is-a-carry-trade-usd-jpy-carry-trade-explained/
