# Paper operation and evidence

`forex run-paper` is disabled until `paper.enabled`, starting AUD balance and the daily
UTC risk-rollover hour are explicitly configured. It requires a working read-only MT5
market-data connection; no MT5 order method is called. A separate paper SQLite database
prevents simulated account state from sharing real-broker risk latches. A process lock
rejects duplicate local runtimes.

The loop consumes closed H1/H4 broker bars, persists market evidence, uses the existing
analysis/risk/context/execution services and rechecks risk after context latency. Each
bar identity is attempted once. If a crash interrupts a decision, its claim remains
incomplete and is not blindly retried; inspect `runtime_evaluations` and journal evidence.
Execution reservations and durable simulated positions reconcile on restart.

Simulation uses observed bid/ask quotes and an account-currency tick-value approximation.
Polling can miss intra-poll excursions. Commissions, swap and slippage remain unavailable;
these are explicitly incomplete-cost outcomes, not validated execution performance.
Break-even and exits survive restart. ATR trailing defaults unconfigured and requires a
validated choice; a protective stop never loosens. No paper result authorizes live trading.

Create `data/HALT_PAPER` to halt entries and flatten simulated positions on the next healthy
quote. The latch persists across daily boundaries and restarts. During a data outage, retain
positions and report uncertainty; do not invent a successful flatten. Review the reason and
positions before manually removing the latch. This local control is separate from the
read-only dashboard; authenticated phone control is not yet deployed.

`scripts/start-paper.ps1` is suitable for an operator-created Windows Scheduled Task running
under the same interactive user as MT5. Configure restart-on-failure and use the process lock
to prevent overlap. Windows Session 0 services may not share the terminal desktop; verify
the chosen task/session on the actual VPS before relying on it. No scheduled task/service is
installed by this build. Keep terminal/password/service-account files on the VPS only.

Run `scripts/paper-watchdog.ps1` from a separately configured scheduled task. Missing/stale
heartbeats create the halt latch and fail; they do not blindly restart or kill MT5. The
script uses the documented default paths; adapt them if your configured paths differ.
The 120-second stale threshold is an operational starting point requiring soak calibration.

Use `forex.operations.backup_database` for a consistent SQLite backup (including committed
WAL records), not a raw copy of an active database. Store versioned backups outside Git,
verify integrity, and test restoration to a separate paper database. Stop the runtime before
updates; record the current Git SHA, back up SQLite/config, install the reviewed version,
run verification, then restart. Roll back code only with schema compatibility confirmed;
never overwrite more recent trading evidence with an old backup.

Telegram delivery runs independently when explicitly enabled. Failed deliveries retain the
cursor and retry; delivery is at-least-once, so a crash after sending may duplicate a message.
Trade opens/closes, errors, halts, context outages, daily summaries and prolonged no-fill
periods generate local evidence even with phone/cloud delivery disabled. A daily summary
uses a UTC journal day, which is labelled separately from the chosen risk session boundary.

Actual multi-day live-data soak remains NOT_RUN. Record start/end UTC, code/config versions,
actual uptime, heartbeats, disconnect/stale-data incidents, restarts, missing data, provider
and cloud outages and operator actions. Offline fast-forward tests are not elapsed soak.
Review evidence before configuring demo execution or claiming operational readiness.
