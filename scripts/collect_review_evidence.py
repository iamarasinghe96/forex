"""Read-only, standard-library paper-bot evidence collector. Never imports the bot."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

MAX_FILE = 2_000_000
MAX_JSON = 262_144
TABLES = set("journal_events journal_outbox journal_summaries tax_reserve_ledger paper_account "
             "paper_positions learning_trades learning_scores learning_cursor strategy_patches "
             "telegram_cursor runtime_evaluations execution_intents candles risk_sessions "
             "context_calls context_reviews".split())
NUMBERS = set("entry exit stop target volume tick_size tick_value initial_stop initial_risk_price "
              "initial_risk_amount remaining_risk_amount unrealized_pnl_aud pnl_aud pips balance equity "
              "starting_balance_aud poll_seconds history_days target_reward_risk atr_trailing_multiple "
              "max_positions_per_pair max_leverage minimum_reward_risk max_concurrent_positions "
              "max_simultaneous_risk_percent daily_loss_percent prior_trades min_trades min_factor "
              "skip_below_r trend_threshold range_threshold setup_score_threshold swing_trend_threshold "
              "trend_efficiency_window structure_window atr_period low medium high minimum "
              "maximum_quote_age_seconds maximum_decision_age_seconds session_rollover_hour_utc "
              "risk_percent_per_trade latest_balance latest_equity realized_pnl_aud positive_pnl_aud "
              "negative_pnl_aud reserve_aud event_count closed_trades wins losses".split())
BOOLEANS = set("enabled demo_enabled apply_to_sizing high_volatility_blocks_trend costs_complete".split())
ENUMS = {
    "mode": {"paper", "PAPER", "demo", "DEMO", "live", "LIVE", "verify", "research"},
    "side": {"LONG", "SHORT"}, "direction": {"LONG", "SHORT"},
    "reason": {"STOP", "TARGET", "FLATTEN", "TIME", "AMBIGUOUS_STOP_FIRST", "AMBIGUOUS_UNRESOLVED"},
    "status": {"RUNNING", "HALTED", "STARTING", "FAILED", "ERROR", "PENDING", "APPLIED", "REJECTED", "ROLLED_BACK"},
    "connection": {"MARKET_DATA_OBSERVED"}, "currency": {"AUD"},
    "session_rollover": {"new_york_close"},
    "pnl_basis": {"simulated_incomplete_costs", "simulated", "broker_realized"},
}
SETUPS = {"TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"}
CONFIG = {
    "": {"mode"},
    "broker": {"symbols", "symbol_overrides"},
    "analysis": {"trend_threshold", "range_threshold", "setup_score_threshold", "swing_trend_threshold",
                 "trend_efficiency_window", "high_volatility_blocks_trend", "allowed_setups", "structure_window", "atr_period"},
    "risk": {"max_leverage", "minimum_reward_risk", "max_concurrent_positions", "max_simultaneous_risk_percent",
             "daily_loss_percent", "conviction_risk_percent", "conviction_thresholds"},
    "execution": {"demo_enabled", "maximum_quote_age_seconds", "maximum_decision_age_seconds",
                  "session_rollover", "session_rollover_hour_utc"},
    "paper": {"enabled", "starting_balance_aud", "poll_seconds", "history_days", "target_reward_risk",
              "atr_trailing_multiple", "max_positions_per_pair"},
    "learning": {"enabled", "apply_to_sizing", "prior_trades", "min_trades", "min_factor", "skip_below_r", "disabled_pairs"},
    "exits": {"target_reward_risk", "atr_trailing_multiple"},
}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and abs(parsed) <= 1e18 else None
    except (ValueError, TypeError, OverflowError):
        return None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def pair(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]{6}(?:\.[A-Za-z0-9]{1,8})?", value) else None


def safe(key, value):
    if value is None:
        return None
    if key in NUMBERS:
        return number(value)
    if key in BOOLEANS:
        return value if isinstance(value, bool) else None
    if key in ENUMS:
        return value if isinstance(value, str) and value in ENUMS[key] else None
    if key.endswith("_at_utc") or key in {"observed_at_utc", "opened_at", "closed_at"}:
        return timestamp(value)
    if key in {"config_fingerprint", "code_fingerprint"}:
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None
    if key in {"symbol", "broker_symbol"}:
        return pair(value)
    if key in {"symbols", "disabled_pairs", "entry_blocked_symbols"}:
        return [p for v in value[:20] if (p := pair(v))] if isinstance(value, list) else None
    if key == "allowed_setups":
        return [v for v in value[:10] if isinstance(v, str) and v in SETUPS] if isinstance(value, list) else None
    if key == "symbol_overrides" and isinstance(value, dict):
        return {k: v for k, v in value.items() if pair(k) and pair(v)}
    if key in {"conviction_risk_percent", "conviction_thresholds"} and isinstance(value, dict):
        keys = {"low", "medium", "high"} if key.endswith("percent") else {"minimum", "medium", "high"}
        return {k: number(v) for k, v in value.items() if k in keys and number(v) is not None}
    return None


def select(data, keys):
    if not isinstance(data, dict):
        return {}
    return {key: clean for key in sorted(keys) if key in data
            and ((clean := safe(key, data[key])) is not None or data[key] is None)}


def bounded_read(path, root):
    resolved = path.resolve(strict=True)
    if (resolved.name == ".env" or resolved.name.startswith(".env.")
            or not resolved.is_relative_to(root) or not resolved.is_file() or resolved.stat().st_size > MAX_FILE):
        raise ValueError("Unsupported evidence file")
    with resolved.open("rb") as handle:
        data = handle.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError("Evidence file exceeds limit")
    return data


def json_object(raw):
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_JSON:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, RecursionError):
        return {}


def yaml_scalar(text):
    """Deliberately narrow scalar/flow subset; tags, aliases and expressions are unsupported."""
    text = text.strip()
    if text in {"null", "~"}:
        return None
    if text in {"true", "false"}:
        return text == "true"
    if text.startswith("[") and text.endswith("]"):
        return [yaml_scalar(v) for v in text[1:-1].split(",") if v.strip()]
    if text.startswith("{") and text.endswith("}"):
        result = {}
        for entry in text[1:-1].split(","):
            key, separator, value = entry.partition(":")
            if separator:
                result[key.strip()] = yaml_scalar(value)
        return result
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
        return number(text)
    return text.strip("\"'")


def configuration(root, db_path):
    result = {"interpretation": "Selected disk fields only; not proof of runtime activation. Missing/default/unsupported YAML fields are not reconstructed."}
    selected = {}
    path = root / "config.yaml"
    if path.is_file():
        raw = bounded_read(path, root)
        result["base_sha256"] = hashlib.sha256(raw).hexdigest()
        stack = []
        for line in raw.decode("utf-8-sig").splitlines():
            clean = line.split("#", 1)[0].rstrip()
            if not clean.strip() or "\t" in clean:
                continue
            match = re.match(r"^( *)([a-z_]+):(?:\s*(.*))?$", clean)
            if not match:
                continue
            indent, key, value = len(match[1]), match[2], match[3] or ""
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parts = [item[1] for item in stack] + [key]
            if not value:
                stack.append((indent, key))
                continue
            section, field = ("", key) if len(parts) == 1 else (parts[0], parts[1])
            if field not in CONFIG.get(section, set()):
                continue
            parsed = yaml_scalar(value)
            if len(parts) == 3 and field in {"conviction_risk_percent", "conviction_thresholds", "symbol_overrides"}:
                current = selected.setdefault(section, {}).setdefault(field, {})
                current.update(safe(field, {parts[2]: parsed}) or {})
            elif len(parts) <= 2:
                checked = safe(field, parsed)
                if checked is not None or parsed is None:
                    selected.setdefault(section, {})[field] = checked
    result["base_selected"] = selected
    effective = json.loads(json.dumps(selected))
    overlay = db_path.with_name(db_path.stem + ".strategy-overlay.json")
    result["overlay"] = {"exists": overlay.is_file()}
    if overlay.is_file():
        raw = bounded_read(overlay, root)
        data = json_object(raw)
        result["overlay"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        changes = {section: select(data.get(section), fields) for section, fields in CONFIG.items()
                   if section in {"analysis", "exits", "learning"} and isinstance(data.get(section), dict)}
        if isinstance(data.get("risk"), dict):
            changes["risk"] = select(data["risk"], {"risk_percent_per_trade"})
        if "disabled_pairs" in data:
            changes["disabled_pairs"] = safe("disabled_pairs", data["disabled_pairs"])
        result["overlay"]["selected_changes"] = changes
        for section in {"analysis", "learning"}:
            effective.setdefault(section, {}).update(changes.get(section, {}))
        effective.setdefault("paper", {}).update(changes.get("exits", {}))
        risk = changes.get("risk", {}).get("risk_percent_per_trade")
        if risk is not None:
            effective.setdefault("risk", {})["conviction_risk_percent"] = dict.fromkeys(("low", "medium", "high"), risk)
        if changes.get("disabled_pairs") is not None:
            effective.setdefault("learning", {})["disabled_pairs"] = changes["disabled_pairs"]
    result["disk_inferred_selected"] = effective
    return result


def git_evidence(root):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    def run(*args):
        proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
                              cwd=root, env=env, capture_output=True, text=True, timeout=10, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    try:
        head = run("rev-parse", "HEAD") or ""
        branch = run("symbolic-ref", "--quiet", "--short", "HEAD") or ""
        status = run("status", "--porcelain=v1", "--untracked-files=no")
        return {"head": head if re.fullmatch(r"[0-9a-f]{40,64}", head) else None,
                "branch": branch if re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", branch) else None,
                "detached_or_branch_unavailable": not bool(branch),
                "status_available": status is not None,
                "tracked_change_count": len(status.splitlines()) if status is not None else None,
                "untracked_files": "not inspected", "status_paths": "omitted"}
    except (OSError, subprocess.SubprocessError):
        return {"available": False}


def source_evidence(root):
    sources = {}
    for name in ("runtime", "paper", "learning", "risk", "backtest"):
        path = root / "src" / "forex" / (name + ".py")
        if path.is_file():
            raw = bounded_read(path, root)
            sources[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            text = raw.decode("utf-8-sig")
            if name == "runtime":
                sources[name]["plain_symbol_atr_key_pattern"] = "self.trailing_atr[symbol.upper()]" in text
            if name == "paper":
                sources[name]["position_symbol_atr_lookup_pattern"] = "(atr_by_symbol or {}).get(p.symbol," in text
            if name == "learning":
                sources[name]["reversed_short_best_pattern"] = "best = max((float(c.high) if sign > 0 else float(c.low))" in text
                sources[name]["reversed_short_worst_pattern"] = "worst = min((float(c.low) if sign > 0 else float(c.high))" in text
    return {"files": sources, "diagnostic_scope": "Exact known source patterns only; absent pattern does not prove correctness or deployment activation."}


POSITION_FIELDS = set("symbol side entry stop target volume tick_size tick_value unrealized_pnl_aud pnl_basis".split())
SUMMARY_FIELDS = set("event_count closed_trades wins losses realized_pnl_aud reserve_aud positive_pnl_aud negative_pnl_aud "
                     "costs_complete latest_balance latest_equity balance_at_utc first_event_at_utc last_event_at_utc health_at_utc".split())


def identity(raw):
    return hashlib.sha256(str(raw).encode()).hexdigest()[:20]


def trade_payload(data):
    out = select(data, POSITION_FIELDS | {"exit", "pnl_aud", "pips", "balance", "reason", "direction", "costs_complete", "opened_at_utc", "closed_at_utc"})
    if isinstance(data.get("position"), dict):
        out["position"] = select(data["position"], POSITION_FIELDS)
    intent = data.get("intent")
    if isinstance(intent, dict):
        out["initial_intent"] = select(intent, {"entry", "stop", "target", "volume", "side", "symbol"})
    return out


def database_evidence(path, *, limit=200, deadline_seconds=8, summary_only=False):
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
        raise FileNotFoundError("Existing database required")
    result = {"file_name": path.name, "read_mode": "SQLite URI mode=ro; query_only; bounded BEGIN/ROLLBACK snapshot", "limit": limit}
    started = time.monotonic()
    def check_time():
        if time.monotonic() - started > deadline_seconds:
            raise sqlite3.OperationalError("Snapshot time limit")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2, isolation_level=None)
    db.set_progress_handler(lambda: int(time.monotonic() - started > deadline_seconds), 1000)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        result["unrecognized_table_count"] = len(names - TABLES)
        result["table_counts"] = {}
        for name in sorted(names & TABLES):
            check_time()
            result["table_counts"][name] = db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
        if "paper_account" in names:
            row = db.execute("SELECT currency,balance FROM paper_account WHERE id=1").fetchone()
            result["account"] = select(dict(zip(("currency", "balance"), row)), {"currency", "balance"}) if row else {}
        if "journal_summaries" in names:
            row = db.execute("SELECT substr(summary_json,1,?) FROM journal_summaries WHERE mode='PAPER' AND bucket='all'", (MAX_JSON + 1,)).fetchone()
            result["summary"] = select(json_object(row[0]), SUMMARY_FIELDS) if row else {}
        if summary_only:
            result["snapshot_complete"] = True
            return result
        if "paper_positions" in names:
            rows = db.execute("SELECT client_id,substr(payload,1,?),initial_stop,opened_at,closed_at,substr(close_payload,1,?) "
                              "FROM paper_positions ORDER BY (closed_at IS NULL) DESC,opened_at DESC LIMIT ?", (MAX_JSON + 1, MAX_JSON + 1, limit))
            result["positions"] = []
            for key, raw, initial, opened, closed, close_raw in rows:
                check_time()
                p = select(json_object(raw), POSITION_FIELDS)
                p.update(identity_hash=identity(key), initial_stop=number(initial), opened_at=timestamp(opened), closed_at=timestamp(closed))
                if close_raw:
                    p["closed_result"] = trade_payload(json_object(close_raw))
                entry, stop, initial_stop = number(p.get("entry")), number(p.get("stop")), number(initial)
                volume, tick_size, tick_value = (number(p.get(k)) for k in ("volume", "tick_size", "tick_value"))
                if (all(v is not None for v in (entry, stop, initial_stop, volume, tick_size, tick_value))
                        and tick_size > 0 and tick_value > 0 and volume >= 0 and p.get("side") in {"LONG", "SHORT"}):
                    p["initial_risk_price"] = abs(entry - initial_stop)
                    p["initial_risk_amount_approx"] = abs(entry - initial_stop) / tick_size * tick_value * volume
                    adverse = entry - stop if p.get("side") == "LONG" else stop - entry
                    p["remaining_risk_amount_approx"] = max(0, adverse) / tick_size * tick_value * volume
                result["positions"].append(p)
        if "journal_events" in names:
            result["journal"] = {}
            for kind in ("trade_opened", "trade_closed", "balance", "health"):
                check_time()
                take = limit if kind.startswith("trade_") else 1
                rows = db.execute("SELECT sequence,entity_id,observed_at_utc,substr(payload_json,1,?) FROM journal_events "
                                  "WHERE mode='PAPER' AND kind=? ORDER BY sequence DESC LIMIT ?", (MAX_JSON + 1, kind, take))
                events = []
                for seq, key, observed, raw in rows:
                    check_time()
                    data = json_object(raw)
                    if kind == "health":
                        payload = select(data, {"status", "connection", "mode", "observed_at_utc", "started_at_utc", "config_fingerprint", "code_fingerprint", "entry_blocked_symbols"})
                        payload["position_count"] = len(data["positions"]) if isinstance(data.get("positions"), list) else None
                    elif kind == "balance":
                        payload = select(data, {"balance", "equity"})
                    else:
                        payload = trade_payload(data)
                    events.append({"sequence": seq, "identity_hash": identity(key), "observed_at_utc": timestamp(observed), "data": payload})
                result["journal"][kind] = events
        if "strategy_patches" in names:
            check_time()
            rows = db.execute("SELECT id,status,created_at_utc,decided_at_utc FROM strategy_patches ORDER BY id DESC LIMIT ?", (min(limit, 20),))
            result["patch_decisions"] = [{"id": row[0], **select(dict(zip(("status", "created_at_utc", "decided_at_utc"), row[1:])), {"status", "created_at_utc", "decided_at_utc"})} for row in rows]
        result["snapshot_complete"] = True
    except sqlite3.Error as exc:
        result["snapshot_complete"] = False
        result["error_type"] = type(exc).__name__
        result["time_limit_reached"] = time.monotonic() - started > deadline_seconds
    finally:
        db.set_progress_handler(None, 0)
        if db.in_transaction:
            db.execute("ROLLBACK")
        db.close()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def collect(root, database, limit=200):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Existing project directory required")
    database = database.resolve(strict=True)
    if (database.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}
            or not database.is_relative_to(root) or not database.is_file()):
        raise ValueError("Database must be an existing file inside the project")
    report = {"collector_version": 1, "collected_at_utc": datetime.now(UTC).isoformat(),
              "git": git_evidence(root), "sources": source_evidence(root),
              "configuration": configuration(root, database),
              "current_account": database_evidence(database, limit=limit),
              "limitations": ["Disk/git/config and database evidence are not one atomic snapshot.",
                              "No MT5 connection or live price lookup; no runtime process inspection.",
                              "Source pattern diagnostics do not prove which code the process loaded.",
                              "Amounts use stored tick values; costs and unrealized mark-to-market paths remain incomplete."]}
    previous = root / "data" / "paper.sqlite3"
    if previous.is_file() and previous.resolve() != database:
        if not previous.resolve().is_relative_to(root):
            raise ValueError("Previous database is outside project")
        report["previous_account"] = database_evidence(previous, limit=limit, summary_only=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(r"C:\forex"))
    parser.add_argument("--database", type=Path, default=Path("data/paper-a1000.sqlite3"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=200, choices=range(1, 1001), metavar="1..1000")
    args = parser.parse_args(argv)
    try:
        root = args.repo.resolve(strict=True)
        database = args.database if args.database.is_absolute() else root / args.database
        database = database.resolve(strict=True)  # Missing databases are never created.
        output = args.output or root / "work" / "external-review" / (datetime.now(UTC).strftime("evidence-%Y%m%dT%H%M%S%fZ") + ".json")
        output = output.absolute()
        if output.suffix.lower() != ".json":
            raise ValueError("Output must be a new JSON file")
        resolved_output = output.resolve()
        if resolved_output.is_relative_to(root) and not resolved_output.is_relative_to(root / "work" / "external-review"):
            raise ValueError("Within-project output must stay under work/external-review")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Output already exists")
        report = collect(root, database, args.limit)
        encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
        print("Evidence written to the new output file.")
        return 0
    except (OSError, ValueError, UnicodeError, sqlite3.Error, RecursionError) as exc:
        print("Collection failed safely (" + type(exc).__name__ + "); no deployment/configuration/database writes were requested.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
