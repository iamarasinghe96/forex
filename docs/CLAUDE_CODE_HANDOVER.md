# Claude Code handover: finish setup and start a monitored VPS paper run

Prepared 30 September 2026 for Indika. This is a continuation of an existing build, not a
request to rebuild the strategy. The immediate objective is an AUD 100 simulated account
running on the Windows VPS, with alerts and an authenticated dashboard, followed by a
real seven-day observation period. Do not promise profits or enable real-money orders.

## Start here

Read this file, BUILD_PROGRESS.md, PROJECT_CONTEXT.md, OPERATOR_SETUP.md and
docs/PAPER_OPERATIONS.md before changing anything. Later explicit user decisions override
the original build brief. The user wants hands-on assistance with minimal copying/pasting:
do available local work yourself; guide them one concrete step at a time for VPS-only work,
Google sign-in, credentials, broker support and review decisions.

PC repository: C:\Users\Indika\Desktop\forex
VPS repository: C:\forex (confirmed by the user; the trailing > was a PowerShell prompt).
GitHub: https://github.com/iamarasinghe96/forex
Working branch: codex/layers6-11-integration
Combined draft PR: https://github.com/iamarasinghe96/forex/pull/18
Main remains 6b0273d8ccc84143ffeb0495adcf9a19f0021d8b. Do not pull main and assume it
contains this implementation. Inspect local changes before switching, pulling or copying.
The latest setup commits will be on the integration branch; inspect its actual remote HEAD.
Runtime + New York reset commit before this handoff: f4401d96c2fa3d6cb1fc8d97a226ea831d1edfa2.
PRs #9–17 are component drafts; #18 combines them. Do not blindly merge both paths.

No agent currently has demonstrated remote command access to the VPS. Do not pretend that
PC checks were VPS checks. Ask the user to run a short read-only command there when needed.
Do not request RDP passwords in chat or silently establish remote access.

## What is built and tested

Layers 6–11 exist: constrained AI review, durable execution/reconciliation, complete local
journal and asynchronous Firestore mirror, read-only dashboard, persistent paper runtime,
Windows recovery tooling, and immutable evidence-gated performance intelligence.

Latest full Python run: 180 passed. Ruff clean; mypy clean (31 source files). Seven new
session tests cover winter/summer and both US DST transition days. The most recent changes
after that run are setup values, handover documentation and a read-only VPS preflight script;
config loading, disabled flags, script syntax and git diff checks passed. No actual VPS
startup, restart, outage recovery or multi-day soak has passed yet.

Settings currently saved:
- mode: paper; paper.enabled: false; execution.demo_enabled: false.
- paper.starting_balance_aud: 100. Existing persisted balances, if any, must NOT be reset.
- execution.session_rollover: new_york_close; session_rollover_hour_utc: null.
  Boundary is 17:00 America/New_York (21:00/22:00 UTC with automatic US DST).
  Do not switch policy mid-run: its session ID namespace differs from fixed UTC.
- Context, Telegram, cloud sync and remote halt are all still disabled.
- ATR trailing multiple remains null. Do not invent a validated value.
- Risk policy unchanged: conviction minimum55 / medium70 / high85; risk2/3.5/5%;
  leverage cap30; RR>=1.5; maximum4 positions; totalrisk20%; dailyloss12%; reserve32.5%.
- At AUD100, broker minimum volume/margin may prevent entries. Do not increase risk or
  round orders up merely to manufacture trades. No-trade evidence is a legitimate result.

## Verified PC integrations

### MT5: connected but entries blocked

Account23011822, ICMarketsAU-Demo, AUD, leverage1:30, hedging. Broker demo balance AUD200;
that is independent of our virtual AUD100 paper balance. EURUSD/GBPUSD/USDJPY quotes were
fresh and consistent with the existing server-clock conversion at check time.
All three symbols returned SYMBOL_TRADE_MODE_CLOSEONLY (3), confirmed in the terminal UI.
The user reports the suggested password/symbol/new-demo troubleshooting did not resolve it.
Support was offline; an email was drafted for the user. Sending/reply is not confirmed.
Ask whether IC Markets has replied. Do not repeat speculative Gemini diagnoses as facts.

The paper runtime intentionally blocks new simulated entries on close-only symbols.
Do NOT bypass that gate or send test orders. Resolve actual full-entry permission (mode4),
or obtain an explicit reviewed design decision for a distinct research-only simulator.
Algo Trading is OFF. The current shared MT5Broker.connect() also requires terminal
trade_allowed even for read-only paper data. Treat this as a separate startup requirement:
inspect attached EAs before asking the user to enable the terminal-wide button, or review
and test a narrowly scoped data-only connection change. Do not confuse the toolbar switch
with broker close-only permissions. PaperBroker must never call MT5 order methods.

### AI providers

All three keys authenticated successfully from PC .env. Current proposed provider order:
1. Groq: openai/gpt-oss-120b — actual JSON response parsed as ReviewResponse, PASS.
2. Gemini: gemini-3.1-flash-lite — actual JSON response parsed, PASS.
3. OpenRouter: google/gemma-4-31b-it:free — key valid, actual completion HTTP429.
   This fallback is NOT VERIFIED. Retry once after cooldown or inspect quota; do not
   continuously retry or enable billing/top-ups without the user's decision.

These were synthetic connectivity responses, NOT evidence of trading judgment or edge.
Groq/Gemini did not report cost in tested responses; cost remains unavailable, not zero.
No provider billing plan was changed. Provider list/model IDs are in config.yaml;
context.enabled remains false. Verify from VPS before enabling for the supervised run.

### Telegram

getMe succeeded; a single PAPER-labelled setup message was accepted by sendMessage from
this PC. Message said trading is disabled and no order placed. Confirm the user received it.
telegram.enabled is still false; enable only as part of the reviewed supervised setup.

### Firebase and dashboard

Project forex-paper-bot; (default) Firestore, STANDARD/FIRESTORE_NATIVE, Sydney
(australia-southeast1). Google Authentication enabled and checked by Admin API.
Registered web app: Forex Paper Dashboard. Public settings saved in dashboard/.env.local.
localhost already authorized. PC local Vite server was started at http://localhost:5173
(exec session10871, not portable to another agent). Check if still running before starting
another process. Dashboard is NOT yet publicly hosted, so that URL is PC-only.

User explicitly approved iamarasinghe96@gmail.com as the sole dashboard operator.
Its verified Google Firebase UID is stored in access/operator. Retrieve current UID using
Admin SDK; never authorize whichever user happens to appear first in a users list.
Deployed firestore.rules, then read back exact release/source equality.
Actual client-token tests:12/12PASS — operator PAPER/DEMO reads allowed, LIVE denied;
authenticated other user and signed-out reads denied; writes denied for all three.
The temporary test Auth user was deleted. No tokens were persisted.
Admin SDK write/read/delete also passed on a unique _setup_checks document, then removed.
No fake trading events or profit records were created.

Local emulator previously tested the actual mirror delivery/aggregate repair/halt path.
Real-project full journal outbox delivery, outage/reconnect, aggregate repair, remote halt,
IAM review and operator revocation/reinstatement still require verification. Do not equate
the isolated Admin document test with a complete mirror integration test.
cloud.project_id is saved, but cloud.enabled and cloud.emergency_halt_enabled remain false.
The dashboard cannot send orders, write Firestore or clear the local halt latch.

## Credentials: preserve and never disclose

User explicitly chose PC setup first and manually re-entered Telegram/MT5/AI values there.
Do NOT tell them to copy an older VPS .env over the PC file. They do not want to retype keys.
PC .env is ignored by Git. PC private Firebase file:
C:\Users\Indika\Desktop\forex\.secrets\firebase-admin.json
PC .env points to that file using FOREX_FIREBASE_SERVICE_ACCOUNT_FILE.
.secrets/ and dashboard/.env.local are ignored. .env.vps was also excluded locally in
.git/info/exclude, but was never supplied; do not rely on that exclusion on the VPS.
Never print .env, private JSON, tokens, HTTP authorization headers or raw auth exceptions.

Transfer .env and the private JSON securely via the user's RDP file transfer, preserving
and privately backing up the VPS's existing files first. The final VPS credential path is:
FOREX_FIREBASE_SERVICE_ACCOUNT_FILE=C:/forex/.secrets/firebase-admin.json
Do not commit, upload to chat, bundle into an output ZIP or embed Admin credentials in web
assets. Public dashboard Firebase configuration is distinct from the Admin private key.
An earlier user screenshot exposed the MT5 password and part of a Telegram token. Rotation
was advised but NOT confirmed. Ask the user to confirm rotation before unattended operation;
never repeat the exposed values. Preserve any newly rotated values during transfer.

## Remaining plan, in order

### 1. Read-only VPS inventory and preserve existing installation

Ask the user to run this in VPS PowerShell and return output (contains no secret values):

```powershell
Set-Location C:\forex
Get-Location
git status --short
git branch --show-current
git rev-parse HEAD
.\.venv\Scripts\python.exe --version
```

If git or Python is absent, handle that actual result; don't assume PC versions exist there.
The new scripts/vps-preflight.ps1 adds package versions, MT5 process count, selected file
existence and Forex task names without reading secret contents. Copy only that script to
the VPS if needed before running it. It changes no settings and sends no orders.
Record existing processes/scheduled tasks, code SHA and uncommitted work. Back up config,
secrets and any SQLite database securely. Use a consistent SQLite backup for running WAL
state, not an ordinary copy. Never reset/delete a database to make a startup check pass.

### 2. Review and install an explicit code version

Operator has not approved merging PR18. Review relevant code and fixes, present concrete
changes/test evidence, and obtain explicit approval before merging or deploying semantic/
execution/architecture changes. Setup actions and Firebase authorization are approved;
that is not blanket PR merge approval. Main is old. Deploy a reviewed pinned commit, not
an unexamined branch tip; preserve a known rollback version and schema-compatible backup.
Inspect status before fetch/switch; do not force checkout/reset or discard VPS changes.

Once code is reviewed and present in C:\forex, install the project extras in that VPS venv:

```powershell
Set-Location C:\forex
.\.venv\Scripts\python.exe -m pip install -e '.[mt5,firebase,dev]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
```

Create a compatible venv only if needed; do not copy the PC venv to the VPS.
Securely transfer credentials and adapt the Firebase path. Check secrets without printing.
Run VPS-specific read-only account/tick/spec, provider, Telegram and Firebase checks.

### 3. Resolve broker startup blockers

Read IC Markets response; verify the chosen actual demo account, AUD, leverage<=30,
identity/server, current quotes, native bars and full symbol permissions. If account changes,
review config and persisted account binding rather than quietly reusing old paper state.
Resolve the terminal trade_allowed requirement above. Do not make real or broker-demo
orders merely to prove that the paper bot works. Separate demo transport tests need their
own agreed scope; real-money production is excluded.

### 4. Supervised PAPER startup and cloud integration

Only after readiness checks, enable selected integrations and paper.enabled deliberately.
Keep mode:paper and execution.demo_enabled:false. Keep unresolved OpenRouter limits clear;
Groq/Gemini have passed only PC connectivity so far. No paid quota upgrade without consent.

```powershell
Set-Location C:\forex
.\scripts\start-paper.ps1 -Repository C:\forex
```

Confirm AUD100 simulated opening state, healthy quotes/heartbeat, New York risk session,
no MT5 orders, journal candidates/no-trades, explicit cost limitations, and cloud mirror
records. Verify actual asynchronous delivery and reconnect/repair without polluting trading
performance with fixtures. Confirm phone alerts and dashboard authorization on real data.
Check that disabling AI/providers preserves documented fallback and emits alerts.

### 5. Dashboard access away from the PC

The existing localhost dashboard is not a public deployment. Follow dashboard/README.md
and the existing Pages workflow: publish the reviewed build, configure the four public
Firebase web settings, authorize the exact Pages domain in Firebase Auth, then verify sign-in,
unauthorized users, denied writes and operator revocation on the deployed URL. Never place
an Admin key or privileged order/halt endpoint in the browser. Hosting needs an explicit
reviewed deployment decision; do not merge PR18 silently to make Pages deploy.

### 6. Windows startup, monitoring and recovery

Run under the same Windows interactive user/session as MT5; generic Session0 services
may not see that terminal. Use the documented start script and OS process lock. Configure
Task Scheduler deliberately after checking for existing tasks; no task is installed yet.
Keep runtime and watchdog as separate tasks. Watchdog default stale threshold120seconds
is provisional and writes HALT_PAPER; it does not blindly restart/kill MT5. Schedule only
after supervised behavior is understood, with startup grace/order to avoid an immediate halt.

Test disconnect/reconnect, stale quotes, process restart, duplicate-start denial, database
backup/restoration and reboot/logon recovery. Capture evidence. Prove that ordinary RDP
disconnect leaves the process running; Windows sign-out is a different operation.
Never claim unattended recovery based solely on task creation or a green terminal icon.

Local emergency action (simulated positions only):

```powershell
Set-Content -LiteralPath C:\forex\data\HALT_PAPER -Value 'Operator requested paper halt'
```

Runtime flattens simulated positions only on healthy quotes; on an outage it must retain
uncertainty. Do not remove the latch automatically. Optional remote PAPER halt remains
separate Admin-console controls/paper_halt; enable/test only with verified IAM. Dashboard
writes stay prohibited. No claim of reliable phone halt during cloud/network failure.

### 7. Start the actual seven-day observation period

Record real UTC start, pinned code SHA/config fingerprint, opening virtual balance and
operator decisions. Keep alerts active and check early operation before leaving it alone.
Collect genuine elapsed heartbeat/gap/restart/incident evidence; do not fast-forward fixtures.
A stopped loop does not count as uptime. Diagnose incidents instead of merely resetting.

After a week, use paper-soak-report (consult CLI help for UTC flags), journal/export and
Layer11 diagnosis. Report closing balance, equity/open positions, realized/unrealized P&L,
observed spreads vs missing commission/swap/slippage, candidates/rejections/no-trades,
actual uptime/gaps and incidents. Positive virtual P&L is not real money or validation.
No actual trades is a valid outcome; explain the recorded causes rather than loosen policy.
Only later consider independently reviewed candidate research/promotion. No automatic
parameter changes, promotion after three losses, or live trading enablement.

## Research facts to preserve

Historical imports verified: EURUSD48263 H1 rows, GBPUSD48260, USDJPY48262, roughly7.74years.
Actual fixed-baseline walk-forward completed9folds per pair; no need to rerun. Gross
candidate expectancy R: EURUSD -0.03967421; GBPUSD -0.05885054; USDJPY +0.04080980.
These include below-minimum-conviction candidates and overlapping independent simulations,
not executable portfolio returns. Costs remain incomplete; fixed UTC H4 not proven equal
to broker DST-aligned H4. Final reserved holdout from2025-09-28T16:00Z was not evaluated by
these completed runs. No formal strategy validation or profitable-system claim.
See docs/RESEARCH_RESULTS.md and the existing output research reports/hashes.

## Local evidence and continuation

PC ignored work files contain sanitized results:
- mt5-setup-check.json
- provider-setup-check.json and provider-response-check.json
- firebase-access-deployment.json and firebase-live-access-check.json
- firebase-rules-release-before.json (rollback reference, not secret)
No API keys or ID tokens were written into these evidence files.

Useful guides: docs/PAPER_OPERATIONS.md, docs/INTELLIGENCE.md, dashboard/README.md,
RUNBOOK.md. Current progress is BUILD_PROGRESS.md. Keep it updated with verified facts,
failed/pending checks and the next user action. End each interaction with one clear next
step rather than asking the user to perform the whole checklist at once.

First user-facing response should say that you have the handover, know the VPS path is
C:\forex, and will begin with its read-only inventory while checking for IC Markets' reply.
