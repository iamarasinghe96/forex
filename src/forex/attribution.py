"""Evidence-backed observations, explicitly separate from causal/learning claims."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Attribution:
    label: str
    evidence_ids: tuple[str, ...]
    explanation: str
    claim_type: str = "OBSERVATION_NOT_CAUSAL_PROOF"
    causal_confidence: float | None = None


def attribute(evidence: Mapping[str, Mapping[str, Any]]) -> tuple[Attribution, ...]:
    """No fabricated probabilities, market labels or policy/parameter mutations."""
    result = []
    for identity, item in evidence.items():
        if item.get("kind") == "hard_risk_block":
            result.append(Attribution("HARD_RISK_BLOCK", (identity,), str(item.get("reason", "Risk block"))))
        if item.get("kind") in {"analysis_no_candidate", "no_trade"}:
            result.append(Attribution("ANALYTICAL_NO_CANDIDATE", (identity,),
                                       str(item.get("reason", "No candidate"))))
        if item.get("ambiguous") is True:
            result.append(Attribution("INTRABAR_PATH_AMBIGUOUS", (identity,),
                                       "OHLC cannot establish the event ordering."))
        exit_reason = item.get("exit_reason", item.get("reason") if item.get("kind") == "trade_closed" else None)
        if exit_reason in {"STOP", "AMBIGUOUS_STOP_FIRST"}:
            result.append(Attribution("PROTECTIVE_STOP_EXIT", (identity,),
                                       "Recorded outcome exited at the protective stop."))
        if item.get("kind") == "context_rejection":
            result.append(Attribution("CONTEXT_REJECTION", (identity,),
                                       "Structured context review withheld the permitted entry; inspect its cited evidence."))
        before, after = item.get("entry_regime"), item.get("exit_regime")
        if before is not None and after is not None and before != after:
            result.append(Attribution("OBSERVED_REGIME_CHANGE", (identity,),
                                       "Supplied entry/exit regime observations differ."))
        if item.get("costs_complete") is False:
            result.append(Attribution("COST_EVIDENCE_INCOMPLETE", (identity,),
                                       "Complete execution costs were not observed."))
    return tuple(result)
