"""Strategy lab menu: ``python -m forex.lab`` (or ``run``, ``study``, ``list`` for the .bat files).

Research only: it reads price databases, never the broker, and changes nothing in the live bot.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, time
from pathlib import Path

from forex.config import load_config
from forex.day_levels import levels_report
from forex.lab.data import History, load_history
from forex.lab.engine import comparison, run_strategy, save
from forex.lab.settings import DEFAULT_FILE, LabSettings, load_settings
from forex.lab.strategies import STRATEGIES, Context

REPORTS = Path("reports/strategy-lab")


def show(path: Path) -> None:
    """Open a file or folder on Windows (Notepad/Explorer); elsewhere just name it."""
    if sys.platform == "win32":
        os.startfile(path.resolve())  # type: ignore[attr-defined]
    else:
        print(f"Open: {path}")


def history_for(settings: LabSettings) -> History:
    data = settings.data
    print("Loading hourly prices...", flush=True)
    history = load_history(data.databases, data.fallback_databases, data.pairs)
    print(history.describe(), flush=True)
    return history


def enabled(settings: LabSettings) -> list[str]:
    return [n for n in STRATEGIES if n not in settings.strategies or settings.strategies[n].enabled]


def run(names: list[str], open_after: bool = False) -> int:
    settings = load_settings()
    unknown = [n for n in names if n not in STRATEGIES]
    if unknown:
        print(f"Unknown strategy: {', '.join(unknown)}. Available: {', '.join(STRATEGIES)}")
        return 2
    chosen = names or enabled(settings)
    started = datetime.now(UTC).astimezone()
    history = history_for(settings)
    ctx = Context(load_config(Path("config.yaml")).analysis.model_dump_json(), Path("data/lab-cache"),
                  settings.workers, datetime.combine(settings.data.start, time(), UTC))
    results = [run_strategy(name, history, settings, ctx) for name in chosen]
    label = "+".join(chosen) if len(chosen) <= 2 else "all"
    settings_text = DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.is_file() else "# defaults\n"
    path = save(results, history, settings_text, REPORTS / f"{started:%Y-%m-%d_%H%M}_{label}",
                REPORTS / "ledger.csv", started)
    (REPORTS / "latest.txt").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print("\n" + comparison(results))
    print(f"\nFull report: {path}\nEvery run is also listed in {REPORTS / 'ledger.csv'}")
    if open_after:
        show(path)
    return 0


def study(open_after: bool = False) -> int:
    settings = load_settings()
    started, history = datetime.now(UTC).astimezone(), history_for(settings)
    start = datetime.combine(settings.data.start, time(), UTC)
    summary, full = levels_report({p: [b for b in s.bars if b.timestamp_utc >= start]
                                   for p, s in history.series.items()})
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{started:%Y-%m-%d_%H%M}_previous-day-study.txt"
    path.write_text(history.describe() + "\n\n" + full + "\n", encoding="utf-8")
    print("\n" + summary + f"\n\nFull report with each pair: {path}")
    if open_after:
        show(path)
    return 0


def listing() -> int:
    settings = load_settings()
    on = enabled(settings)
    for name, strategy in STRATEGIES.items():
        entry = settings.strategies.get(name)
        params = {**strategy.defaults, **(entry.parameters() if entry else {})}
        print(f"\n{name} ({'on' if name in on else 'off'}): {strategy.title}\n  {strategy.describe(params)}")
    print(f"\nChange settings or switch strategies on/off in {DEFAULT_FILE}.")
    return 0


MENU = """
STRATEGY LAB - research only: nothing is traded and the live bot is not touched.
Settings: strategy-lab.yaml    Results: reports\\strategy-lab\\
  1  Test every strategy that is on, and compare them
  2  Test one strategy
  3  Previous-day high/low study (the video's numbers on our pairs)
  4  List the strategies and their settings
  5  Open the results folder
  6  Open the settings file
  0  Exit"""


def menu() -> int:
    while True:
        print(MENU)
        choice = input("Choose a number: ").strip()
        if choice == "1":
            run([], open_after=True)
        elif choice == "2":
            names = list(STRATEGIES)
            for number, name in enumerate(names, start=1):
                print(f"  {number}  {name}: {STRATEGIES[name].title}")
            pick = input("Which one? ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(names):
                run([names[int(pick) - 1]], open_after=True)
        elif choice == "3":
            study(open_after=True)
        elif choice == "4":
            listing()
        elif choice == "5":
            REPORTS.mkdir(parents=True, exist_ok=True)
            show(REPORTS.resolve())
        elif choice == "6":
            show(DEFAULT_FILE.resolve())
        elif choice in {"0", ""}:
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy lab (research only)")
    parser.add_argument("command", nargs="?", choices=["menu", "run", "study", "list", "get-history"],
                        default="menu")
    parser.add_argument("strategies", nargs="*", help="Strategy names for 'run' (default: every one that is on)")
    parser.add_argument("--open", action="store_true", help="Open the report when done (Windows)")
    args = parser.parse_args()
    if args.command == "run":
        return run(args.strategies, args.open)
    if args.command == "study":
        return study(args.open)
    if args.command == "list":
        return listing()
    if args.command == "get-history":
        from forex.lab.get_history import get_history
        return get_history()
    return menu()


if __name__ == "__main__":
    sys.exit(main())
