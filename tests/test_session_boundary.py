from datetime import UTC, datetime, timedelta

import pytest

from forex.config import ExecutionConfig
from forex.runtime import paper_session_id


@pytest.mark.parametrize("boundary", [
    "2026-01-15T22:00:00", "2026-07-15T21:00:00",
    "2026-03-07T22:00:00", "2026-03-08T21:00:00",
    "2026-10-31T21:00:00", "2026-11-01T22:00:00",
])
def test_new_york_boundary_and_dst_transition_days(boundary: str) -> None:
    config = ExecutionConfig(session_rollover="new_york_close")
    moment = datetime.fromisoformat(boundary).replace(tzinfo=UTC)
    before = "PAPER:NY17:" + (moment.date() - timedelta(days=1)).isoformat()
    after = "PAPER:NY17:" + moment.date().isoformat()
    assert paper_session_id(moment - timedelta(seconds=1), config) == before
    assert paper_session_id(moment, config) == after
    assert paper_session_id(moment + timedelta(hours=1), config) == after
    # Midnight UTC does not create another session inside the same NY risk day.
    assert paper_session_id(moment + timedelta(hours=6), config) == after


def test_fixed_utc_compatibility_and_ambiguous_configuration() -> None:
    config = ExecutionConfig(session_rollover_hour_utc=22)
    assert paper_session_id(datetime(2026, 7, 15, 21, tzinfo=UTC), config) == "PAPER:2026-07-14"
    assert paper_session_id(datetime(2026, 7, 15, 22, tzinfo=UTC), config) == "PAPER:2026-07-15"
    with pytest.raises(ValueError, match="not both"):
        ExecutionConfig(session_rollover="new_york_close", session_rollover_hour_utc=22)
    assert not ExecutionConfig().rollover_configured
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        paper_session_id(datetime(2026, 7, 15, 21, tzinfo=UTC).replace(tzinfo=None), config)
