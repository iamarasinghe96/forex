# Setup score and dynamic risk: specification (2026-10-03)

Operator idea: score every trade opportunity out of 100, like a test suite ("80/100 checks
passed"), learned from past situations. Higher-scoring setups get more risk. The score must
recognise the same pattern at any price level: a setup at 100 USD last year and 200 AUD this
year is the same setup if its shape and conditions match.

Industry terms: **expected-value-based position sizing**, also called **meta-labeling**
(López de Prado, *Advances in Financial Machine Learning*, 2018, ch. 3). A primary rule
proposes the trade; a second model estimates how good this particular instance is and sets the
bet size. Pattern matching uses **scale-invariant features**: everything measured in ATRs,
percentages, ranks or z-scores, never in raw prices.

## 0. Lesson already in the data (do not repeat it)

The bot already has a score. Conviction = (1 - uncertainty) x 100 in `src/forex/risk.py`
(`derive_conviction`, `risk_tier`), with risk tiers of 2 / 3.5 / 5%. It was hand-designed and
never validated.

Out of sample (2021-2025, all candidates, gross; `docs/EXTERNAL_REVIEW_HANDOVER.md` E2):

| Conviction band | Mean R | Candidates |
|---|---|---|
| Below minimum | +0.028 | 11,445 |
| LOW | -0.033 | 10,274 |
| MEDIUM | -0.121 | 3,175 |
| HIGH | -0.323 | 130 |

**The higher the score, the worse the trade.** Sizing by it would have bet the most on the
worst trades. That is why risk is now flat at 5%.

Rule: a score may change risk only after it passes the acceptance tests in section 4, out of
sample. Same data, factor "style": swing +0.096 R vs day -0.041 R, which supports testing
slower setups.

## 1. Trading definition

- **Opportunity:** a moment when an entry rule fires: today's trend rule, the swing-structure
  rule (`scripts/swing_structure.py`) or a future rule.
- **Score (0-100):** a calibrated estimate of this opportunity's expected net R. It is NOT a
  count of conditions met. 80 means "historically, setups like this landed in the top 20% of
  realised outcomes, out of sample".
- **Risk mapping (fractional Kelly):**
  - risk% = clip(k x mu(x) / sigma^2, min_risk, max_risk).
  - mu(x) = predicted mean net R; sigma^2 is about 1.1 R^2 (measured); k = 0.25-0.5.
  - Skip the trade if mu(x) <= 0.
  - Example: mu = 0.03 (today's average) gives full Kelly 2.7%, quarter Kelly 0.7%.
  - Example: mu = 0.20 in a strong bucket gives full Kelly 18%, capped at max_risk (5%).
- **Hard limits stay outside the score:** daily loss circuit, max concurrent risk, leverage,
  one position per pair.

## 2. Scale-invariant pattern features (computed only from data up to the decision bar)

| Group | Examples (unit) |
|---|---|
| Trend | EMA gaps and slopes in ATRs; directional efficiency (0-1); last 2 swing highs/lows rising? (Dow); bars since trend start |
| Structure | consolidation height / ATR; breakout distance / ATR; position in 20-bar range (0-1); distance to last swing low in ATRs |
| Momentum | returns over 1/5/20 bars in ATRs; RSI; MACD histogram / ATR |
| Volatility | ATR percentile over 100 bars; ATR(H1)/ATR(H4); range expansion of the last bar |
| Context | session (one-hot); day of week; H4 regime label; pair (one-hot or excluded for transfer to new pairs) |
| Cross-pair (optional) | USD strength = mean of signed returns of all USD pairs, in ATRs |

The existing `feature_state` in `src/forex/analysis.py` already produces most of these in ATR
units. Raw prices, raw ATR and account balance are forbidden as features.

## 3. Learning method (simple first)

1. **Dataset:** one row per opportunity, with features x, outcome y (net R under the exact live
   exit rules), timestamp and pair. Build it from the causal replay streams
   (`scripts/causal_replay.py` `analyse_pair` already computes every hour's features).
2. **Models, in this order; stop at the first that passes section 4:**
   - (a) Bucket table: 3-5 pre-chosen features, each in terciles; mean R per cell with
     shrinkage.
   - (b) L2-regularised linear/logistic model on standardized features.
   - (c) k-nearest-neighbour "analog" search: mean outcome of the k most similar past setups in
     standardized feature space. This is the literal "same pattern at a different price".
   - (d) Shallow gradient-boosted trees with monotone constraints.
3. **Calibration:** isotonic regression of predicted vs realised R on validation folds. The
   score is the percentile of calibrated mu within the training distribution.
4. **Validation:**
   - Walk-forward only: train on earlier years, test on later ones.
   - Embargo of at least the maximum trade length between folds (purged CV).
   - Final confirmation on pairs never used in training (AUDUSD, USDCAD, USDCHF, NZDUSD,
     EURJPY, GBPJPY).

## 4. Acceptance tests: the "N/N passed" scorecard

All must pass out of sample in both 2012-2018 and 2019-2026. Report it as a test-suite line,
e.g. `score-model v1: 7/7 passed`.

| # | Test | Pass condition |
|---|---|---|
| T1 | Monotonic | Mean realised R rises across score quintiles (Spearman > 0); top minus bottom quintile > 0 with bootstrap 95% CI excluding 0 |
| T2 | Top bucket profitable | Top quintile mean net R > 0 at 2x costs |
| T3 | Stable | T1 holds in each period and in at least 2 of 3 pairs |
| T4 | Sizing beats flat | Dynamic risk beats flat risk on log growth and on max drawdown, same trades, same max risk |
| T5 | Beats chance | Real scores beat 1,000 random permutations of the scores on T1's spread (p < 0.05) |
| T6 | Calibrated | Predicted vs realised R per decile within the bootstrap CI in at least 8 of 10 deciles |
| T7 | No leakage | Unit test: altering any bar after the decision time leaves the score unchanged; scaling all prices x2 leaves the score unchanged |

If any test fails, the score may be logged ("shadow mode") but must not change risk.

## 5. Code integration (for Claude Code to implement once a model passes)

| Piece | Where |
|---|---|
| Dataset export | new `scripts/export_setup_dataset.py`, reusing `causal_replay.analyse_pair`; CSV/Parquet of features + outcomes |
| Training and scorecard | new `scripts/train_setup_score.py`; writes `data/models/setup-score-vN.json` (feature list, scaler, coefficients or bucket table, calibration table, training window, scorecard results, SHA-256) |
| Runtime scoring | new `src/forex/scoring.py`: `SetupFeatures.from_snapshot(...)`, `ScoreModel.load(path)`, `score(x) -> ScoreResult(score_0_100, expected_r, band)`; pure, no I/O in `score` |
| Risk | `src/forex/risk.py`: replace the `risk_tier` conviction tiers with `risk_percent_for_score(expected_r, config)` when `scoring.enabled`; hard limits unchanged |
| Config | `config.yaml`: `scoring: {enabled: false, shadow: true, model_path, kelly_fraction: 0.25, min_risk_percent, max_risk_percent: 5, skip_below_expected_r: 0}` |
| Journal and learning | log score, expected_r and features on every candidate; learning buckets by score band; the model hash joins `strategy_version` |
| Rollout | shadow mode (score logged, flat size) for at least 4 weeks, then enable; Telegram shows "score 82/100, risk 3.1%" |
| Tests | scale invariance (prices x2 gives the same score), leakage, mapping bounds and monotonicity, model-file hash check |

## 6. Honest expectations

- Sizing can only amplify an edge that exists. With an average edge of about +0.03 R, dynamic
  risk helps only if the score separates setups well (e.g. a top quintile at +0.15 R or more).
- About 800 strategy trades over 13 years is a small training set. Simple models (a-c) and more
  pairs come before complex ones.
