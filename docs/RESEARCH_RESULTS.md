# Completed fixed-baseline walk-forward research

Nine folds per pair; 730-day training windows, 180-day testing windows and 180-day steps.
The same baseline parameter version `research-e64814bf57401dd5` was used in every fold.
No parameter optimization or promotion was performed. Test windows span 2021-01-01 through
2025-06-09 UTC. The final reserved holdout starts 2025-09-28 at 16:00 UTC and was not evaluated
by these runs. The residual period after the last full test window is not an additional fold.

| Pair | Completed independent simulations | Gross expectancy R | Gross profit factor |
|---|---:|---:|---:|
| EURUSD | 8,024 | -0.03967421 | 0.923877 |
| GBPUSD | 8,176 | -0.05885054 | 0.889211 |
| USDJPY | 8,824 | 0.04080980 | 1.085538 |

These aggregates cover candidate simulations, including below-minimum-conviction candidates.
They are not executed portfolio returns, independent trade samples or account drawdowns.
Bid-only history has incomplete costs, and fixed UTC H4 is not verified against broker H4.
All reports explicitly retain strategy_validated=false, costs_complete=false and
broker_h4_alignment_verified=false. Positive USDJPY gross expectancy does not establish
profitability after realistic costs. The EURUSD and GBPUSD gross aggregates are negative.

## Artifact integrity

Full reports stay local under ignored reports/backtest and in the delivered outputs folder.
The compact JSON summary includes dataset provenance, fold boundaries and aggregate metrics.

- EURUSD: `walk-forward-EURUSD-185c5a2aa8772f0fc863437b3f80b057d449085df03702b9ea1dfe09497e12ab.json`
  SHA256 `a62e70667dee80239ddbc19263b186c1534dee5e9cb79e5f704351fe1df7f7a7`
- GBPUSD: `walk-forward-GBPUSD-185c5a2aa8772f0fc863437b3f80b057d449085df03702b9ea1dfe09497e12ab.json`
  SHA256 `0ab617d0f97af83f706a819afa81d261cd9ce898133788edfc0a005de5b6b696`
- USDJPY: `walk-forward-USDJPY-185c5a2aa8772f0fc863437b3f80b057d449085df03702b9ea1dfe09497e12ab.json`
  SHA256 `0cef5c3c2875e2d080fa6e5a350c236a22c9e780e3660eb8417b3b2fb8b38814`
