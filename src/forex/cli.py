"""Commands intended for a non-programmer operator."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from forex.broker.mt5 import MT5Broker
from forex.analysis import InsufficientDataError, analyse_market
from forex.config import Secrets, load_config
from forex.domain import Timeframe
from forex.errors import OperatorError
from forex.logging_setup import configure_logging
from forex.market_data import download_history, validate_candle_freshness, validate_tick_freshness
from forex.persistence import CandleStore, initialise_database


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
    """Verify and persist all market history exposed by MT5 without trading."""
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.market_data")
    broker: MT5Broker | None = None
    try:
        secrets = Secrets()
        store = CandleStore(config.database.path)
        broker = MT5Broker(config.broker, secrets.mt5_password)
        broker.connect()
        for symbol in config.broker.symbols:
            spec = broker.resolve_symbol(symbol)
            tick = broker.tick(spec.broker_name)
            validation_now = datetime.now(UTC)
            broker.validate_server_clock(
                validation_now, config.market_data.server_clock_tolerance_seconds
            )
            validate_tick_freshness(tick, validation_now, config.market_data)
            for timeframe in Timeframe:
                request_end = datetime.now(UTC)
                recent = broker.candles(
                    symbol, timeframe, request_end - timedelta(days=7), request_end
                )
                validate_candle_freshness(recent[-1], datetime.now(UTC), config.market_data)
                store.upsert(recent)
                report = download_history(
                    broker, store, symbol, timeframe, config.market_data, end=datetime.now(UTC)
                )
                log.info(
                    "%s %s earliest=%s latest=%s candle_count=%s depth_days=%.1f "
                    "approximate_years=%.2f expected_weekend_gaps=%s unexplained_gaps=%s",
                    report.symbol, timeframe.value, report.earliest_utc.isoformat(),
                    report.latest_utc.isoformat(), report.candle_count, report.depth_days,
                    report.approximate_years, report.gaps.expected_weekend_gaps,
                    len(report.gaps.unexplained_gaps),
                )
                if report.approximate_years < 5:
                    log.warning(
                        "%s %s history is %.2f years, short of the later five-year backtesting "
                        "requirement by %.2f years; no missing data was fabricated.",
                        symbol, timeframe.value, report.approximate_years,
                        5 - report.approximate_years,
                    )
        log.info("Layer 2 verification passed. Historical candles were saved; no order was sent.")
        return 0
    except ValidationError as exc:
        raise OperatorError(
            f"Required secrets are missing or invalid: {exc}. Check the local .env and retry; "
            "never paste .env into chat."
        ) from exc
    finally:
        if broker is not None:
            broker.disconnect()


def verify_analysis(config_path: Path) -> int:
    """Analyse stored closed candles only; never connects to MT5 or execution code."""
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.analysis")
    store = CandleStore(config.database.path)
    evaluation_time = datetime.now(UTC)
    for symbol in config.broker.symbols:
        h1 = store.load(symbol, Timeframe.H1)
        h4 = store.load(symbol, Timeframe.H4)
        if not h1 or not h4:
            raise OperatorError(
                f"Stored H1/H4 history for {symbol} is missing. Run `forex verify-market-data` "
                "while MT5 is connected, then retry; analysis did not fetch or trade."
            )
        validate_candle_freshness(h1[-1], evaluation_time, config.market_data)
        validate_candle_freshness(h4[-1], evaluation_time, config.market_data)
        try:
            result = analyse_market(symbol, h1, h4, evaluation_time, config.analysis)
        except InsufficientDataError as exc:
            raise OperatorError(
                f"Stored history for {symbol} cannot support configured analysis windows: {exc}. "
                "Run `forex verify-market-data`, then retry; no data was fabricated."
            ) from exc
        snapshot = result.snapshot
        log.info(
            "%s evaluation=%s last_closed_h1=%s last_closed_h4=%s regime=%s "
            "directional=%.3f volatility=%.3f setup=%s style=%s candidate=%s direction=%s "
            "macro=%s strategy=%s parameters=%s",
            symbol, snapshot.evaluation_time_utc.isoformat(),
            snapshot.last_closed_h1_utc.isoformat(), snapshot.last_closed_h4_utc.isoformat(),
            snapshot.regime.label.value, snapshot.regime.directional_bias,
            snapshot.volatility_state,
            snapshot.setup_type.value if snapshot.setup_type else "NONE",
            snapshot.trade_style.value if snapshot.trade_style else "NONE",
            "YES" if snapshot.candidate_generated else "NO",
            snapshot.direction.value if snapshot.direction else "NONE",
            snapshot.macro_context.availability.value, snapshot.strategy_version,
            snapshot.parameter_version,
        )
        if snapshot.supporting_evidence:
            log.info("%s supporting=%s", symbol, ", ".join(
                f"{item.code}({item.strength:.2f})" for item in snapshot.supporting_evidence))
        if snapshot.opposing_evidence:
            log.info("%s opposing=%s", symbol, ", ".join(
                f"{item.code}({item.strength:.2f})" for item in snapshot.opposing_evidence))
        if snapshot.no_candidate_reason:
            log.info("%s no-candidate reason=%s", symbol, snapshot.no_candidate_reason)
    log.info("Layer 3 analysis verification passed. Stored data only; no order was sent.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely verify the read-only Forex system")
    parser.add_argument(
        "command", choices=["verify-foundation", "verify-market-data", "verify-analysis"]
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    try:
        commands = {
            "verify-foundation": verify,
            "verify-market-data": verify_market_data,
            "verify-analysis": verify_analysis,
        }
        command = commands[args.command]
        raise SystemExit(command(args.config))
    except OperatorError as exc:
        logging.getLogger("forex").critical("%s", exc)
        raise SystemExit(2) from exc
