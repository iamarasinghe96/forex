"""Write the lookback review prompt (every recent trade, for ChatGPT) to a text file.

Usage: python scripts/lookback_prompt.py [--days 14] [--db PATH] [--out PATH]

The same prompt is available from the running bot: send /lookback (or /lookback 30) in Telegram.
Uses the live settings, including any approved learning changes, and reads the bot's records only.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from forex.config import load_config
from forex.domain import Timeframe
from forex.journal import JournalStore
from forex.learning import apply_overlay, overlay_path, read_overlay
from forex.lookback import DEFAULT_DAYS, build_lookback_prompt
from forex.persistence import CandleStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--db", type=Path, default=None, help="Default: paper.database in the config")
    parser.add_argument("--out", type=Path, default=None, help="Default: data/lookback-<date>-<days>d.txt")
    args = parser.parse_args()
    base = load_config(args.config)
    db = args.db or base.paper.database
    if not db.is_file():
        print(f"No paper database at {db}.")
        return 1
    config = apply_overlay(base, read_overlay(overlay_path(db)))
    now = datetime.now(UTC)
    candles = CandleStore(db)
    text, closed, still_open = build_lookback_prompt(config, JournalStore(db),
                                                     lambda symbol: candles.load(symbol, Timeframe.H1), args.days, now)
    out = args.out or db.parent / f"lookback-{now:%Y-%m-%d}-{args.days}d.txt"
    out.write_text(text, encoding="utf-8")
    print(f"{closed} closed and {still_open} open trades; {len(text):,} characters written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
