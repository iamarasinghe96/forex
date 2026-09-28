"""Commands intended for a non-programmer operator."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pydantic import ValidationError

from forex.broker.mt5 import MT5Broker
from forex.config import Secrets, load_config
from forex.errors import OperatorError
from forex.logging_setup import configure_logging
from forex.persistence import initialise_database


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely verify the Forex system foundation")
    parser.add_argument("command", choices=["verify-foundation"])
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    try:
        raise SystemExit(verify(args.config))
    except OperatorError as exc:
        logging.getLogger("forex").critical("%s", exc)
        raise SystemExit(2) from exc
