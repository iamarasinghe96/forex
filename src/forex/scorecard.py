"""Hourly scorecard: the old trend strategy's measurements, kept as independent scoring tools.

The operator switched the old entry strategy off (``paper.entry_strategy: none``) to design a new
one. The analysis still runs every hour, and its readings are published per pair:
- the H4 trend: direction, strength, efficiency, volatility;
- the H1 picture: range position, EMA distance, RSI, MACD, ATR;
- the four setup-score parts;
- what the old strategy would have done, with its stop.

The scorecard is a ``scorecard`` journal event, mirrored to the dashboard. It is sent by
``/scorecard`` in Telegram, and it never places a trade.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from forex.analysis import AnalysisResult
from forex.config import AnalysisConfig


def _num(value: Any, digits: int = 2) -> float | None:
    try:
        return None if value is None else round(float(value), digits)
    except (TypeError, ValueError):
        return None


def pip_size(symbol: str) -> Decimal:
    return Decimal("0.01") if symbol.upper().endswith("JPY") else Decimal("0.0001")


def scorecard_entry(symbol: str, result: AnalysisResult, config: AnalysisConfig) -> dict[str, Any]:
    """One pair's readings at the last closed H1 bar (plain numbers; the analysis is unchanged)."""
    snap, candidate = result.snapshot, result.candidate
    f = snap.feature_snapshot
    pip = float(pip_size(symbol))
    atr = float(f.get("h1_atr") or 0)
    parts = {name: _num(value) for name, value in snap.setup_measurements.items()}
    trend_parts = {"h4_trend", "h1_momentum", "structure", "pullback_coherence"}
    score = round(sum(v for v in parts.values() if v is not None) / len(parts), 2) if parts and set(parts) == trend_parts else None
    verdict, stop = "none", None
    if candidate is not None:
        verdict = "BUY" if candidate.side.value == "LONG" else "SELL"
        stop = candidate.structural_reference_levels["rolling_low" if verdict == "BUY" else "rolling_high"]
    close = float(f.get("h1_close") or 0)
    return {
        "symbol": symbol.upper(), "h1_bar_utc": snap.last_closed_h1_utc.isoformat(),
        "sessions": list(snap.session_context),
        "h4": {"regime": snap.regime.label.value, "direction": _num(snap.regime.directional_bias),
               "strength": _num(snap.regime.trend_strength), "efficiency": _num(f.get("h4_directional_efficiency")),
               "volatility_rank": _num(snap.regime.volatility_state),
               "ema_gap_atr": _num(f.get("h4_ema_fast_slow_atr")), "ema_slope_atr": _num(f.get("h4_ema_slope_atr"))},
        "h1": {"close": _num(close, 5), "range_position": _num(f.get("h1_range_position")),
               "high_20": _num(f.get("h1_rolling_high"), 5), "low_20": _num(f.get("h1_rolling_low"), 5),
               "ema20_distance_atr": _num(f.get("h1_distance_fast_atr")), "rsi": _num(f.get("h1_rsi"), 1),
               "macd_hist_atr": _num(float(f.get("h1_macd_histogram") or 0) / atr if atr else None),
               "atr_pips": _num(atr / pip, 1), "volatility_rank": _num(f.get("h1_volatility_rank"))},
        "setup": {"parts": parts, "score": score, "threshold": config.setup_score_threshold},
        "old_strategy": {"verdict": verdict, "reason": snap.no_candidate_reason,
                         "stop": _num(stop, 5), "stop_pips": _num(abs(close - stop) / pip, 1) if stop else None,
                         "stop_atr": _num(abs(close - stop) / atr) if stop and atr else None},
    }


def _fmt(value: Any, spec: str = ".2f") -> str:
    return "–" if value is None else format(value, spec)


def scorecard_text(payload: Mapping[str, Any]) -> str:
    """The latest scorecard as a short Telegram message."""
    lines = [(f"Scoring tools at {str(payload.get('generated_at_utc', ''))[:16]} UTC. The old trend strategy is "
             "measured, not traded.")]
    for entry in payload.get("pairs") or []:
        h4, h1, setup, old = entry["h4"], entry["h1"], entry["setup"], entry["old_strategy"]
        verdict = (f"would {old['verdict']}, stop {old['stop']} ({_fmt(old['stop_pips'], '.0f')} pips, "
                   f"{_fmt(old['stop_atr'], '.1f')} ATR)" if old["verdict"] != "none" else f"no signal: {old['reason']}")
        lines += ["",
                  (f"{entry['symbol']}: H4 {h4['regime']}, strength {_fmt(h4['strength'])}, direction "
                  f"{_fmt(h4['direction'], '+.2f')}, volatility {_fmt(h4['volatility_rank'])}"),
                  (f"H1: range position {_fmt(h1['range_position'])}, {_fmt(h1['ema20_distance_atr'], '+.2f')} ATR from "
                  f"the 20 EMA, RSI {_fmt(h1['rsi'], '.0f')}, MACD {_fmt(h1['macd_hist_atr'], '+.2f')} ATR, ATR "
                  f"{_fmt(h1['atr_pips'], '.1f')} pips"),
                  f"Setup score {_fmt(setup['score'])} (old threshold {setup['threshold']}); old strategy {verdict}"]
    return "\n".join(lines)
