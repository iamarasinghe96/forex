"""Commands intended for a non-programmer operator."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from forex.analysis import InsufficientDataError, analyse_market
from forex.backtest import (
    StrategyBaseline,
    build_walk_forward_folds,
    history_gate,
    monte_carlo,
    run_backtest,
    write_json_report,
)
from forex.broker.mt5 import MT5Broker
from forex.config import Secrets, load_config
from forex.domain import Timeframe
from forex.errors import OperatorError
from forex.history import import_csv, validate_research_database, verify_database
from forex.logging_setup import configure_logging
from forex.market_data import download_history, validate_candle_freshness, validate_tick_freshness
from forex.persistence import CandleStore, initialise_database
from forex.risk import DailyRiskState, PortfolioRiskState, decide_risk
from forex.risk_policy import policy_from_config


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


def verify_backtest(config_path: Path, *, formal: bool = False, database: Path | None = None) -> int:
    """Replay SQLite history without MT5, secrets, parameter mutation, or execution APIs."""
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.backtest")
    store = CandleStore(database or config.database.path)
    research_dataset = None
    if database is not None:
        research_dataset, _ = validate_research_database(
            database, config.broker.symbols, config.market_data
        )
    policy = policy_from_config(config.risk)
    gates = {}
    metrics = {}
    simulations = {}
    protocols = {}
    latest_closed = []
    for symbol in config.broker.symbols:
        h1 = store.load(symbol, Timeframe.H1)
        h4 = store.load(symbol, Timeframe.H4)
        if not h1 or not h4:
            raise OperatorError(
                f"Stored H1/H4 history for {symbol} is missing. Run `forex verify-market-data` "
                "on the VPS, then retry; Layer 4 never downloads or fabricates candles."
            )
        gate = history_gate(h1, h4, config.backtest.minimum_history_years)
        gates[symbol] = gate
        result = run_backtest(symbol, h1, h4, config.analysis, config.backtest, policy)
        metrics[symbol] = result.metrics
        simulations[symbol] = (monte_carlo(result.trades, config.backtest.monte_carlo_iterations,
                                           config.backtest.monte_carlo_seed)
                               if result.trades else None)
        if gate.earliest_utc is None or gate.latest_utc is None:
            raise OperatorError(f"Unable to determine stored history coverage for {symbol}.")
        protocols[symbol] = build_walk_forward_folds(
            gate.earliest_utc, gate.latest_utc, config.backtest
        )
        latest_closed.append(result.evaluations[-1].snapshot.evaluation_time_utc
                             if result.evaluations else h1[-1].timestamp_utc)
        log.info(
            "%s H1=%s H4=%s history_years=%.2f status=%s evaluations=%s "
            "raw_candidate_evaluations=%s setup_episodes=%s "
            "independent_simulated_outcomes=%s candidates/week=%.2f episodes/week=%.2f "
            "independent_outcomes/week=%.2f gross_expectancy_R=%s "
            "net_known_expectancy_R=%s",
            symbol, len(h1), len(h4), gate.available_years, gate.status,
            result.metrics.evaluation_count, result.metrics.candidate_count,
            result.metrics.setup_episode_count, result.metrics.trade_count,
            result.metrics.candidate_frequency_per_week,
            result.metrics.setup_episodes_per_week, result.metrics.trades_per_week,
            result.metrics.gross.expectancy_r,
            result.metrics.net_known_cost.expectancy_r,
        )
    eligible = all(gate.sufficient for gate in gates.values())
    status = "FORMAL_VALIDATION_ELIGIBLE_NOT_AUTOMATICALLY_VALIDATED" if eligible else \
        "INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION"
    warnings = (
        "Commission, slippage, swap and other broker fees are unavailable; net-known-cost results are incomplete.",
        "Candle spread points require captured instrument point metadata and are not tick execution spreads.",
        "All Layer 3 and Layer 4 parameters remain UNVALIDATED; no parameter was promoted.",
    )
    assumptions = {
        "entry": "next available H1 open",
        "ambiguity_policy": config.backtest.ambiguity_policy,
        "reward_risk": config.backtest.reward_risk,
        "breakeven_at_r": config.backtest.breakeven_at_r,
        "atr_trailing_multiple": config.backtest.atr_trailing_multiple,
        "forward_horizons_bars": tuple(config.backtest.forward_horizons_bars),
        "simulation_horizon_bars": config.backtest.simulation_horizon_bars,
        "trade_frequency_target": "3-8/week calibration only; never a veto",
        "counting_scope": (
            "Raw candidate evaluations, contiguous setup episodes, and independent candidate "
            "simulations are research measures; none is a future live-order count."
        ),
    }
    baseline = StrategyBaseline(
        max(latest_closed), status, gates, metrics, simulations, False, protocols, assumptions,
        warnings, asdict(research_dataset) if research_dataset else None,
    )
    report_name = (f"research-baseline-{research_dataset.fingerprint}.json"
                   if research_dataset else "strategy-baseline.json")
    report_path = config.backtest.report_directory / report_name
    write_json_report(report_path, baseline)
    for warning in warnings:
        log.warning("%s", warning)
    log.warning("%s", status)
    log.info("Layer 4 report written to %s. Stored data only; no order was sent.", report_path)
    if formal and not eligible:
        log.error("Formal validation refused: %s", status)
        return 3
    return 0


def full_validation(config_path: Path, database: Path | None = None) -> int:
    return verify_backtest(config_path, formal=True, database=database)


def verify_risk(config_path: Path) -> int:
    """Calculate Layer 5 ceilings from read-only inputs; no execution API exists here."""
    config = load_config(config_path)
    configure_logging(config)
    log = logging.getLogger("forex.risk")
    store = CandleStore(config.database.path)
    policy = policy_from_config(config.risk)
    broker: MT5Broker | None = None
    try:
        secrets = Secrets()
        broker = MT5Broker(config.broker, secrets.mt5_password)
        account = broker.connect()
        evaluation_time = datetime.now(UTC)
        log.info("PORTFOLIO CHECK: verification fixture — zero supplied open positions")
        log.info(
            "DAILY CIRCUIT-BREAKER CHECK: verification fixture — session opening balance set "
            "to current account balance; no production session latch is being inferred"
        )
        for symbol in config.broker.symbols:
            h1, h4 = store.load(symbol, Timeframe.H1), store.load(symbol, Timeframe.H4)
            if not h1 or not h4:
                raise OperatorError(f"Stored H1/H4 history for {symbol} is missing.")
            validate_candle_freshness(h1[-1], evaluation_time, config.market_data)
            validate_candle_freshness(h4[-1], evaluation_time, config.market_data)
            result = analyse_market(symbol, h1, h4, evaluation_time, config.analysis)
            if result.candidate is None:
                log.info("%s: no current Layer 3 candidate (%s)", symbol,
                         result.snapshot.no_candidate_reason)
                continue
            candidate = result.candidate
            spec = broker.resolve_symbol(symbol)
            tick = broker.tick(spec.broker_name)
            entry = tick.ask if candidate.side.value == "LONG" else tick.bid
            stop_key = "rolling_low" if candidate.side.value == "LONG" else "rolling_high"
            stop = Decimal(str(candidate.structural_reference_levels[stop_key]))
            decision = decide_risk(
                candidate, account, spec, entry, stop, None, PortfolioRiskState(()),
                DailyRiskState(evaluation_time.date().isoformat(), account.balance,
                               account.equity), policy,
            )
            plan = decision.permitted_position_plan
            log.info(
                "%s side=%s setup=%s style=%s conviction=%s band=%s risk_percent=%s "
                "balance=%s risk_budget=%s entry=%s structural_stop=%s objective_1_5R=%s "
                "volume=%s actual_risk=%s stop_valid=%s decision=%s reasons=%s",
                symbol, candidate.side.value, candidate.setup_type.value,
                candidate.trade_style.value, decision.conviction.final_conviction,
                decision.tier.band.value, decision.tier.risk_percent, account.balance,
                plan.requested_risk_amount if plan else "N/A", entry, stop,
                plan.minimum_objective if plan else "N/A", plan.volume if plan else "N/A",
                plan.actual_risk_amount if plan else "N/A", "YES" if plan else "NO",
                decision.status.value, ",".join(reason.value for reason in decision.reasons) or "NONE",
            )
        log.info("stored/current read-only data only; no order was sent.")
        return 0
    except ValidationError as exc:
        raise OperatorError(f"Required MT5 secrets are missing or invalid: {exc}") from exc
    finally:
        if broker is not None:
            broker.disconnect()


def verify_context(config_path: Path) -> int:
    """Verify local review configuration/schema without calling paid providers."""
    from forex.context import ReviewResponse

    config = load_config(config_path)
    prompt = config.context.prompt_file.read_text(encoding="utf-8")
    if not prompt.strip():
        raise OperatorError("Context prompt is empty. Restore the versioned prompt file.")
    ReviewResponse.model_validate_json(
        '{"verdict":"approve","volume_fraction":"1","rationale":"Offline schema check"}'
    )
    print(json.dumps({"layer": 6, "mode": config.mode.upper(),
                      "context_enabled": config.context.enabled,
                      "providers": [p.model_dump() for p in config.context.providers],
                      "external_provider_verification": "NOT_RUN",
                      "status": "LOCAL_CONFIGURATION_AND_SCHEMA_VERIFIED"}, indent=2))
    return 0


def verify_execution(config_path: Path) -> int:
    """Exercise durable reservation in a disposable fixture, without a broker connection."""
    from tempfile import TemporaryDirectory

    from forex.analysis import Side
    from forex.execution import ExecutionStore, OrderIntent

    config = load_config(config_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with TemporaryDirectory(prefix="forex-execution-check-") as directory:
        store = ExecutionStore(Path(directory) / "fixture.sqlite3")
        intent = OrderIntent("fx-offline-fixture", "fixture", "fixture", 1, "FIXTURE", Side.LONG,
                             Decimal(".01"), Decimal(1), Decimal(".9"), Decimal("1.2"), 1, now)
        if not store.reserve(intent) or store.reserve(intent):
            raise OperatorError("Execution reservation self-check failed. Do not enable execution.")
        store.update(intent.client_id, "UNKNOWN", None, "fixture ambiguous submission", now)
        reopened = ExecutionStore(store.path)
        if reopened.unresolved() != (intent.client_id,):
            raise OperatorError("Execution restart self-check failed. Do not enable execution.")
    print(json.dumps({"layer": 7, "mode": config.mode.upper(),
                      "status": "OFFLINE_RESERVATION_AND_RESTART_VERIFIED",
                      "broker_execution": "NOT_RUN", "real_money_execution": "DISABLED"}))
    return 0


def verify_journal(config_path: Path) -> int:
    """Check atomic local audit persistence in a disposable offline database."""
    from tempfile import TemporaryDirectory

    from forex.journal import JournalStore

    config = load_config(config_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with TemporaryDirectory(prefix="forex-journal-check-") as directory:
        journal = JournalStore(Path(directory) / "fixture.sqlite3")
        event = journal.append("PAPER", "no_trade", "offline-fixture", {"reason": "fixture"}, now)
        if journal.append("PAPER", "no_trade", "offline-fixture", event.payload, now) != event:
            raise OperatorError("Journal idempotency failed. Stop and preserve the database for review.")
        if len(journal.pending(now, 10)) != 1 or journal.summary("PAPER")["event_count"] != 1:
            raise OperatorError("Journal/outbox verification failed. Do not enable the runtime.")
    print(json.dumps({"layer": 8, "mode": config.mode.upper(),
                      "status": "LOCAL_JOURNAL_AND_OUTBOX_VERIFIED",
                      "cloud_enabled": config.cloud.enabled, "firestore_verification": "NOT_RUN"}))
    return 0


def sync_journal(config_path: Path) -> int:
    """Deliver one configured cloud batch; disabled configuration performs no network I/O."""
    from forex.cloud_sync import configured_worker
    from forex.journal import JournalStore

    config = load_config(config_path)
    worker = configured_worker(config.cloud, JournalStore(config.database.path))
    if worker is None:
        print("Cloud mirror disabled. Local records retained; no cloud request was made.")
        return 0
    result = worker.sync_once(datetime.now(UTC), config.cloud.batch_size)
    print(json.dumps(asdict(result)))
    return 2 if result.failed else 0


def verify_paper(config_path: Path) -> int:
    from tempfile import TemporaryDirectory

    from forex.journal import JournalStore
    from forex.operations import SingleWriter, backup_database
    from forex.runtime import RuntimeStore

    config = load_config(config_path)
    now = datetime.now(UTC)
    with TemporaryDirectory(prefix="forex-paper-check-") as directory:
        path = Path(directory) / "fixture.sqlite3"
        journal = JournalStore(path)
        journal.append("PAPER", "no_trade", "fixture", {"reason": "offline verification"}, now)
        store = RuntimeStore(path)
        if not store.claim("fixture", now) or RuntimeStore(path).claim("fixture", now):
            raise OperatorError("Paper restart identity check failed. Keep runtime disabled.")
        with SingleWriter(Path(directory) / "fixture.lock"):
            backup_database(path, Path(directory) / "backup.sqlite3")
    print(json.dumps({"layer": 10, "paper_enabled": config.paper.enabled,
                      "status": "OFFLINE_STATE_AND_BACKUP_VERIFIED", "elapsed_soak": "NOT_RUN",
                      "mt5": "NOT_CALLED"}))
    return 0


def run_paper(config_path: Path) -> int:
    from threading import Event

    from forex.context import ContextReviewer, ContextSecrets, ContextStore, HTTPContextProvider
    from forex.paper import PaperBroker
    from forex.runtime import PaperRuntime

    config = load_config(config_path)
    if (not config.paper.enabled or config.mode != "paper" or
            config.paper.starting_balance_aud is None or
            config.execution.session_rollover_hour_utc is None):
        raise OperatorError("Paper runtime is disabled or incomplete. Configure starting balance and daily rollover, then explicitly enable paper mode. No broker order was sent.")
    if config.paper.database.resolve() == config.database.path.resolve():
        raise OperatorError("Use a separate paper database so simulated risk latches cannot affect broker execution.")
    configure_logging(config)
    from forex.operations import SingleWriter

    with SingleWriter(config.paper.database.with_suffix(".lock")):
        feed = MT5Broker(config.broker, Secrets().mt5_password)
        try:
            account = feed.connect()
            feed.validate_server_clock(datetime.now(UTC), config.market_data.server_clock_tolerance_seconds)
            paper = PaperBroker(config.paper.database, feed, account,
                                Decimal(str(config.paper.starting_balance_aud)),
                                config.execution.maximum_quote_age_seconds,
                                Decimal(str(config.risk.tax_reserve_percent)))
            reviewer = ContextReviewer(config.context, HTTPContextProvider(config.context, ContextSecrets()),
                                       ContextStore(config.paper.database))
            runtime = PaperRuntime(config, feed, paper, reviewer)
            runtime.run(Event())
        except KeyboardInterrupt:
            logging.getLogger("forex.paper").info("Paper loop stopped by operator; positions retained for restart.")
        finally:
            feed.disconnect()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely verify the read-only Forex system")
    parser.add_argument(
        "command", choices=["verify-foundation", "verify-market-data", "verify-analysis",
                            "verify-backtest", "validate-backtest", "verify-risk",
                            "import-history", "verify-history", "verify-context", "verify-execution",
                            "verify-journal", "sync-journal", "run-paper", "verify-paper"]
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--research-database", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--dataset")
    parser.add_argument("--provider")
    parser.add_argument("--symbol")
    parser.add_argument("--price-type", choices=["bid", "ask", "midpoint", "ohlc"])
    parser.add_argument("--spread-available", action="store_true")
    parser.add_argument("--volume-semantics", default="unavailable")
    parser.add_argument("--h4-alignment-hour-utc", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "import-history":
            if not all((args.research_database, args.file, args.dataset, args.provider,
                        args.symbol, args.price_type)):
                parser.error("import-history requires --research-database, --file, --dataset, --provider, --symbol and --price-type")
            result = import_csv(args.file, args.research_database, dataset=args.dataset,
                                provider=args.provider, symbol=args.symbol, source_timezone="UTC",
                                price_type=args.price_type, spread_available=args.spread_available,
                                volume_semantics=args.volume_semantics,
                                h4_alignment_hour_utc=args.h4_alignment_hour_utc)
            print(json.dumps(asdict(result), default=str, indent=2))
            raise SystemExit(0)
        if args.command == "verify-history":
            if args.research_database is None:
                parser.error("verify-history requires --research-database")
            config = load_config(args.config)
            for report in verify_database(args.research_database, config.broker.symbols,
                                          config.market_data):
                print(json.dumps(asdict(report), default=str))
            raise SystemExit(0)
        commands = {
            "verify-foundation": verify,
            "verify-market-data": verify_market_data,
            "verify-analysis": verify_analysis,
            "verify-backtest": verify_backtest,
            "validate-backtest": full_validation,
            "verify-risk": verify_risk,
            "verify-context": verify_context,
            "verify-execution": verify_execution,
            "verify-journal": verify_journal,
            "sync-journal": sync_journal,
            "run-paper": run_paper,
            "verify-paper": verify_paper,
        }
        if args.command in {"verify-backtest", "validate-backtest"}:
            raise SystemExit(verify_backtest(args.config, formal=args.command == "validate-backtest",
                                             database=args.research_database))
        command = commands[args.command]
        raise SystemExit(command(args.config))
    except OperatorError as exc:
        logging.getLogger("forex").critical("%s", exc)
        raise SystemExit(2) from exc
