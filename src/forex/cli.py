"""Commands intended for a non-programmer operator."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from pydantic import ValidationError

from forex.broker.mt5 import MT5Broker
from forex.config import Secrets, load_config
from forex.errors import OperatorError
from forex.logging_setup import configure_logging
from forex.market_data import (
    CandleRepository,
    GapKind,
    HistoryDepth,
    assert_fresh,
    detect_gaps,
    validate_candle_order,
)
from forex.persistence import initialise_database
from forex.domain import Timeframe


def verify(config_path: Path) -> int:
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.verify")
    try:
        secrets = Secrets()
        initialise_database(config.database.path)
        broker = MT5Broker(config.broker, secrets.mt5_password)
        account = broker.connect()
        log.info("Connected: account=%s currency=%s balance=%s equity=%s leverage=1:%s mode=%s", account.login, account.currency, account.balance, account.equity, account.leverage, account.mode.value)
        for requested in config.broker.symbols:
            spec = broker.resolve_symbol(requested)
            value = broker.pip_value_per_lot(spec, account.currency)
            log.info("Resolved %s -> %s; pip=%s; pip value per standard lot=%s %s; tick_size=%s tick_value=%s contract_size=%s filling_mode=%s", requested, spec.broker_name, spec.pip_size, value.quantize(spec.point), account.currency, spec.tick_size, spec.tick_value, spec.contract_size, spec.filling_mode)
        broker.disconnect()
        log.info("Layer 1 verification passed. No order was sent.")
        return 0
    except ValidationError as exc:
        raise OperatorError(
            f"Required secrets are missing or invalid: {exc}. Copy .env.example to .env, enter the "
            "MT5 demo trading password locally, and retry. Never paste .env into chat."
        ) from exc


def verify_market_data(config_path: Path) -> int:
    """Download and verify the actual MT5 history without sending an order."""
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.market_data.verify")
    broker: MT5Broker | None = None
    try:
        secrets = Secrets()
        initialise_database(config.database.path)
        repository = CandleRepository(config.database.path)
        broker = MT5Broker(config.broker, secrets.mt5_password)
        account = broker.connect()
        now = datetime.now(timezone.utc)
        log.info(
            "Connected read-only to account=%s currency=%s. Beginning Layer 2 verification.",
            account.login,
            account.currency,
        )
        for requested in config.broker.symbols:
            spec = broker.resolve_symbol(requested)
            tick = broker.tick(spec.broker_name)
            assert_fresh(
                tick.time_utc,
                now,
                timedelta(minutes=config.market_data.stale_after_minutes["H1"]),
                f"{requested} tick",
                config.market_data.weekend_close_utc_hour,
                config.market_data.weekend_open_utc_hour,
            )
            for timeframe_name in config.market_data.timeframes:
                timeframe = Timeframe(timeframe_name)
                recent_start = now - timedelta(
                    seconds=timeframe.seconds * config.market_data.recent_candle_count
                )
                recent = broker.candles(requested, timeframe, recent_start, now)
                validate_candle_order(recent)
                assert_fresh(
                    recent[-1].time_utc,
                    now,
                    timedelta(minutes=config.market_data.stale_after_minutes[timeframe.value]),
                    f"{requested} {timeframe.value} latest candle",
                    config.market_data.weekend_close_utc_hour,
                    config.market_data.weekend_open_utc_hour,
                )
                repository.upsert(recent)
                reloaded = repository.load(requested, timeframe)
                if not {c.time_utc for c in recent}.issubset({c.time_utc for c in reloaded}):
                    raise OperatorError(
                        f"SQLite verification failed for {requested} {timeframe.value}. Stop here, "
                        "check that the VPS disk has free space, and rerun verification."
                    )
                history = broker.all_candles(
                    requested,
                    timeframe,
                    config.market_data.history_chunk_size,
                    config.market_data.mt5_retry_attempts,
                    config.market_data.mt5_retry_delay_seconds,
                )
                validate_candle_order(history)
                repository.upsert(history)
                stored = repository.load(requested, timeframe)
                validate_candle_order(stored)
                if not stored:
                    raise OperatorError(
                        f"No {requested} {timeframe.value} candles survived persistence. Check the "
                        "VPS disk and database permissions, then retry."
                    )
                depth = HistoryDepth(
                    requested, timeframe, history[0].time_utc, history[-1].time_utc, len(history)
                )
                gaps = detect_gaps(
                    history,
                    config.market_data.weekend_close_utc_hour,
                    config.market_data.weekend_open_utc_hour,
                )
                unexplained = [gap for gap in gaps if gap.kind is GapKind.UNEXPLAINED]
                expected = len(gaps) - len(unexplained)
                log.info(
                    "%s (%s) %s: %s candles; earliest=%s; latest=%s; depth_days=%s; "
                    "expected_weekend_gaps=%s; unexplained_gaps=%s",
                    requested,
                    spec.broker_name,
                    timeframe.value,
                    depth.candle_count,
                    depth.earliest_utc.isoformat(),
                    depth.latest_utc.isoformat(),
                    depth.days,
                    expected,
                    len(unexplained),
                )
                if depth.latest_utc - depth.earliest_utc < timedelta(days=1_826):
                    shortfall = 1_826 - depth.days
                    log.warning(
                        "%s %s history is shorter than the later five-year backtest requirement "
                        "by approximately %s days. No external provider has been added.",
                        requested,
                        timeframe.value,
                        shortfall,
                    )
                for gap in unexplained:
                    log.warning(
                        "Unexplained %s %s gap: %s missing bars between %s and %s. Open the chart "
                        "in MT5 to refresh it, then rerun verification.",
                        requested,
                        timeframe.value,
                        gap.missing_bars,
                        gap.previous_open_utc.isoformat(),
                        gap.next_open_utc.isoformat(),
                    )
        log.info("Layer 2 verification passed. Historical candles were saved; no order was sent.")
        return 0
    except ValidationError as exc:
        raise OperatorError(
            f"Required secrets are missing or invalid: {exc}. Keep the existing local .env file "
            "and correct it on the VPS; never paste it into chat."
        ) from exc
    finally:
        if broker is not None:
            broker.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely verify the Forex system")
    parser.add_argument("command", choices=["verify-foundation", "verify-market-data"])
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    try:
        command = verify if args.command == "verify-foundation" else verify_market_data
        raise SystemExit(command(args.config))
    except OperatorError as exc:
        logging.getLogger("forex").critical("%s", exc)
        raise SystemExit(2) from exc
