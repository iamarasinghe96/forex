# Build progress and resumption

## Current status: development implementation through Layer 11 complete

Updated 30 September 2026. User-authorized local implementation and verification are complete.
Credential-dependent integrations remain disabled, manual setup is documented, and actual
broker/cloud/VPS verification and elapsed paper soak remain NOT_RUN. No real-money orders,
parameter promotion, deployment or merge has been performed.

Current branch: `codex/layers6-11-integration`.
Combined draft review: https://github.com/iamarasinghe96/forex/pull/18
Main remains `6b0273d8ccc84143ffeb0495adcf9a19f0021d8b`.
The runtime/dashboard source is commit `89e0cbc84bc1cb5445c1ae7976c7fc2d39e40667`;
`bbd3f9972e9968b93520ed3f40e9ecf11b907c6e` adds the local cloud adapter verification script.
Later commits close out documentation and completed research evidence.

## Authorization and review boundary

Continue from the existing repository, not from a fresh build. PROJECT_CONTEXT.md and
later operator guardrails govern the original brief. Local commands, tests, branches,
commits, pushes and draft PRs are authorized. Do not merge semantic/risk/interface/
validation/execution/promotion/architecture changes without operator review. Do not commit
historical market data, SQLite databases or secrets. Keep external setup placeholders
explicit and disabled; do not fabricate realistic costs, broker checks or soak duration.

## Implemented

- Layer 6: constrained JSON context review, provider failover/cache, risk ceilings and costs.
- Layer 7: durable order identities, fresh risk checks, ambiguity/reconciliation, demo-only
  MT5 transport, monotonic stop protection and persistent risk latches.
- Layer 8: full-state SQLite journal, decision provenance, attribution, reserve ledger,
  exports, persistent cloud outbox and aggregate divergence repair.
- Layer 9: authenticated read-only mobile dashboard, history/rejections, scoped performance,
  reserve evidence and exports; client writes denied. Remote PAPER halt is separately
  administered and cannot remotely clear a local halt latch.
- Layer 10: durable paper broker/runtime, restart recovery, duplicate guards, quote marks,
  heartbeat/watchdog, notifications, backups, Windows operations and actual-interval soak reports.
- Layer 11: all-state diagnosis, immutable hypotheses, pre-registered criteria, hashed
  evidence and historical/recent/walk-forward/OOS/shadow/paper gates. Promotion requires
  operator review and never automatically changes production parameters.

Draft PRs #12–17 preserve the individual layer stack on requirements PR #11. PR #18 also
includes the research corrections from #9/#10. It is an alternative combined review path;
do not blindly merge both the stack and integration. Main was preserved.
Historical trailing now requires break-even first; the baseline used trailing disabled.

## Final verification

- Current full Python suite: **173 passed** (36.95 seconds, final rerun).
- Ruff clean; mypy clean across 31 source files.
- Dashboard: six model tests, actual Edge mobile setup test and production build passed.
- Local Firestore emulator: operator-only PAPER/DEMO reads, unauthorized/anonymous denial,
  all client-write denial, mode restriction and operator revocation passed.
- Actual Python Firebase adapter passed local-emulator event delivery, aggregate repair
  and separate PAPER halt latching. Script: scripts/verify_firestore_mirror.py.
- Windows start/watchdog scripts parsed; offline layer verification commands passed.
  Default paper runtime refuses incomplete/disabled setup.
- Dashboard GitHub CI passed on runtime source commit 89e0cbc:
  https://github.com/iamarasinghe96/forex/actions/runs/36556956061
- Production browser dependency audit: zero vulnerabilities. Development-only Firebase
  CLI tooling: five moderate transitive advisories; no forced major downgrade applied.

## Historical research: complete local runs, not formal validation

All three original imports were verified: EURUSD 48,263 H1 rows, GBPUSD 48,260, USDJPY
48,262; approximately 7.74 years. Full data/reports remain local and ignored by Git.
Research DB: data/dukascopy-research.sqlite3.
Dataset: dukascopy-h1-bid-2019-2026-v1; Dukascopy bid; volume unavailable; fixed UTC H4 hour 0.

Corrected pre-holdout baseline gross expectancy R:
EURUSD -0.06453886285315559; GBPUSD -0.07469902592687842; USDJPY +0.001297812487040083.

Actual fixed-baseline walk-forward process **finished successfully** for all three pairs.
The old session 18157 is finished; do not restart or wait on it. Nine folds per pair were
verified, with 730-day training, 180-day testing/step, one unchanged parameter version and
no optimization. Test span: 2021-01-01 through 2025-06-09 UTC. Final holdout begins
2025-09-28T16:00:00Z and was not evaluated by these runs. An earlier serialization failure
was fixed and regression-tested; only the successful complete reports count.

| Pair | Completed candidate simulations | Gross expectancy R | Gross profit factor |
|---|---:|---:|---:|
| EURUSD | 8,024 | -0.03967421 | 0.923877 |
| GBPUSD | 8,176 | -0.05885054 | 0.889211 |
| USDJPY | 8,824 | +0.04080980 | 1.085538 |

See docs/RESEARCH_RESULTS.md for scope and report SHA256 hashes. Reports are under
reports/backtest/walk-forward-<PAIR>-185c5a2aa8772f0fc863437b3f80b057d449085df03702b9ea1dfe09497e12ab.json.
These include below-minimum-conviction candidate outcomes and are not executed portfolio
returns. Costs remain incomplete, broker DST/H4 equivalence unresolved, and all three
reports explicitly state strategy_validated=false. No candidate was promoted.
Monte Carlo remains IID outcome bootstrap, not trade-order permutation.

## Manual/external completion checklist

OPERATOR_SETUP.md and docs/PAPER_OPERATIONS.md contain the concrete setup steps:
1. Review the draft changes before merging/deploying.
2. DONE: operator selected AUD 100; delegated daily boundary configured as 17:00 New York
   with automatic US DST. Paper/demo execution remain disabled.
3. Configure provider keys/models, Firebase credentials/Auth/operator UID/web settings,
   and optional Telegram credentials locally.
4. Verify actual MT5 demo account, quotes, broker alignment, constraints, execution,
   reconnects and reconciliation; collect genuine costs.
5. Deploy reviewed rules and read-only Pages dashboard; verify access, revocation,
   outages and the separate emergency halt.
6. Configure Windows/VPS startup/watchdog and test backups/recovery under the MT5 session.
7. Run a real unattended paper soak and independently review candidate evidence.

## Resume guidance

There is no unfinished background research to preserve from this checkpoint. Inspect the
working tree and GitHub before any follow-up. The next phase is operator setup and external
evidence, not another implementation pass through the already-built layers. Credentials,
operator decisions and genuine elapsed duration must not be replaced with fabricated values.
No automatic usage-reset retry was configured. Real-money production remains out of scope.

User-facing handoff and full local research copies are in the task outputs folder:
C:/Users/Indika/Documents/Codex/2026-09-29/referenced-chatgpt-conversation-this-is-an/outputs
Files: FOREX_BUILD_HANDOFF.md, WALK_FORWARD_RESULTS.md, walk-forward-summary.json, and the
three full walk-forward reports. Historical baseline evidence is retained separately.

## Setup continuation � 30 September 2026

Operator selected AUD 100 virtual starting balance and delegated the reset time based on
industry practice. Config now uses 17:00 America/New_York, matching IC Markets published
New York-close day. Added an explicit NY-close option alongside backward-compatible fixed
UTC settings, mutual-exclusion validation, and DST-boundary regression tests. This is an
unmerged change on draft PR #18. No default paper database or running MT5 terminal was
found during setup. Next user action: open MT5 and sign into the configured IC Markets AU
demo account; credentials stay local. Then perform read-only account/quote/spec checks.

Setup verification: full suite 180 passed, including winter/summer and both US DST transition
days; Ruff and mypy clean after an explicit naive-timestamp test fixture adjustment.

MT5 setup check (30 September Sydney): installed the optional MT5 Python connector in the
project venv. Read-only connection to the configured ICMarketsAU-Demo account succeeded:
AUD, 1:30, hedging, broker demo balance AUD 200 (separate paper balance remains AUD 100).
All three symbols returned fresh ticks consistent with the existing server-clock conversion.
However, all three report SYMBOL_TRADE_MODE_CLOSEONLY (3); full-entry permission is not
verified and paper entry checks will block them. Terminal Algo Trading is off. No orders
were sent or settings changed. Local evidence: work/mt5-setup-check.json. Resolve broker
symbol close-only restriction before enabling the runtime; toolbar Algo Trading does not
remove a broker-side close-only restriction. External execution tests remain NOT_RUN.

Operator reports login/symbol/new-demo troubleshooting did not resolve close-only and support is offline. Drafting a support email for the operator to send; no email sent by agent. Continue AI provider and Firebase setup while awaiting IC Markets. Local .env provider fields prepared without exposing existing values. Trading remains disabled.

Firebase PC setup: operator explicitly chose local PC credential storage in ignored .secrets. Credential parsed successfully without disclosure. Actual authenticated Firestore metadata read succeeded for forex-paper-bot, default database, STANDARD/FIRESTORE_NATIVE, australia-southeast1. The access/operator document does not exist yet (404). Project ID recorded in config; cloud and trading remain disabled. Next: enable Google Authentication, register dashboard web app, bind verified operator UID and verify deployed rules before enabling sync. No live cloud writes have been performed.

Firebase Google sign-in verified enabled through Admin API. Registered Forex Paper Dashboard web app in existing forex-paper-bot project; saved only public web config in ignored dashboard/.env.local. localhost is already an authorized Auth domain. Local dashboard started at http://localhost:5173 for operator first sign-in. Operator UID not yet bound, deployed operator rules not yet verified, and cloud sync/paper execution remain disabled. Next: user signs in, identifies the intended Google account, then bind that verified Firebase UID and complete authorization checks.

Confirmed operator email authorized by user. access/operator now binds its verified Google UID. Deployed firestore.rules to forex-paper-bot and read back exact source/release match. Actual client-token REST checks all 12 passed: operator PAPER/DEMO reads allowed, LIVE denied; authenticated other user and signed-out reads denied; writes denied for all three. Temporary test Auth user deleted. Evidence: work/firebase-access-deployment.json and work/firebase-live-access-check.json; no tokens persisted. Dashboard remains local at localhost:5173; cloud sync/trading disabled, no trading data yet. User can refresh and sign in to view empty dashboard.


## Current handoff checkpoint — follow this over older setup notes

User is approaching weekly usage limit and requested a Claude Code handover. VPS path is
C:/forex, explicitly confirmed. Detailed current state and ordered next steps are in
docs/CLAUDE_CODE_HANDOVER.md and the task output CLAUDE_CODE_HANDOVER.md. Older lines above
about missing Firebase operator setup are historical: operator is now bound and deployed
client access checks passed12/12. Firebase Admin isolated write/read/delete also passed;
real journal mirror outage/recovery remains unverified.

PC AI credential checks: Groq/Gemini/OpenRouter authenticated. Synthetic structured
responses passed Groq openai/gpt-oss-120b and Gemini gemini-3.1-flash-lite. OpenRouter
selected google/gemma-4-31b-it:free returned HTTP429; fallback not verified. Model values
saved, context still disabled. Telegram getMe and one PAPER setup send succeeded; actual
phone receipt not yet confirmed. No passwords/tokens printed or stored in handover.

Added scripts/vps-preflight.ps1 (read-only); PowerShell syntax and current config validation
passed. All integration/run flags remain disabled. No VPS access, installation, scheduled
tasks, broker restriction resolution, runtime start or seven-day soak completed. Full suite
remains180passed from preceding runtime change; subsequent edits are setup/docs/preflight.
User explicitly authorized PC credential setup; later transfer must adapt paths to C:/forex.
Main remains unchanged; PR18 draft is not merge-approved. Preserve local PC.env user values.


## Broker clarification: tradable .a forex symbols verified

After IC Markets replied that this account uses .a instruments, a direct read-only check
of PC MT5 account23011822 confirmed EURUSD.a, GBPUSD.a and USDJPY.a all report FULL access
(mode4). Their unsuffixed counterparts remain CLOSEONLY(mode3). The screenshots compared
unsuffixed EURUSD with ECL.NYSE.a (a share CFD); they did not show EURUSD.a failing.
This resolves the symbol-availability question on the PC; no orders were sent.

Before runtime startup, fix/verify broker symbol resolution: the previously inspected
MT5Broker.resolve_symbol prefers an exact unsuffixed match, so it can still choose the
close-only instrument even when .a is available. Use an explicit reviewed mapping or
unambiguous broker-symbol selection, retaining canonical EURUSD/GBPUSD/USDJPY strategy
identities. Audit market-data, position, risk, execution and journal paths and test suffix
handling. Do not merely change strategy symbols globally to .a or bypass permission gates.
Recheck actual VPS account/symbols; this PC result alone does not verify VPS setup.


### Follow-up: explicit broker mapping implemented and checked

Configured broker.symbol_overrides for EURUSD->EURUSD.a, GBPUSD->GBPUSD.a and
USDJPY->USDJPY.a. MT5 resolver now honors explicit mappings even when unsuffixed symbols
exist, rejects missing/wrong-pair mappings without fallback, and retains canonical strategy
names. Broker intents already use spec.broker_name; existing suffixed positions resolve
without remapping. The three live .a symbols returned positive tick sizes/values and full
entry permission. No orders sent; Algo Trading remains off.
34 affected MT5/execution/paper tests passed; Ruff and mypy(31files) clean. Added regression
coverage for explicit mapping precedence, missing mapping and wrong currency pair.
This supersedes the earlier instruction to implement mapping; review the existing fix first.
Next: read-only VPS inventory at C:/forex, review/deploy pinned code, securely adapt credentials,
verify actual VPS .a specs and resolve data-only connection/Algo Trading requirement before
supervised PAPER startup. No unattended run or VPS checks completed by this PC result.


## Claude Code session — 30 September 2026 (VPS inventory and data-only MT5 connection)

Operator confirmed: Telegram PAPER setup message received on phone; MT5 password and
Telegram token were rotated after the earlier screenshot exposure.

Read-only VPS inventory (C:/forex, operator-run): branch main at 6b0273d8, no uncommitted
code changes, untracked reports/ only, no stashes. Python 3.13.15 in .venv. data/forex.sqlite3
(2,301,952 bytes, 29 Sep) holds candles 17,271 rows; outbox/risk_sessions empty; no
data/paper.sqlite3. .secrets/firebase-admin.json absent. One MT5 terminal, no Python
processes, no Forex scheduled tasks. Integration branch was fetched but not checked out.

Backup at C:/forex-backups/before-paper-20260930-100312: config.yaml, .env (existence
confirmed without printing), code-version.txt, reports/, and forex.sqlite3 made with the
SQLite backup API from a read-only source; integrity_check ok.

Proposed change (branch claude/determined-thompson-f4ewei, not merged, needs operator review):
MT5Broker.connect() no longer requires terminal Algo Trading, so the read-only paper data
feed can run with Algo Trading OFF (attached EAs cannot trade). MT5ExecutionBroker.connect()
now requires it, and its per-order _guard still checks terminal/account trade permissions,
demo account mode and login. Tests: 184 passed on Linux Python 3.13; Ruff clean; mypy clean
except the two expected Windows-only msvcrt errors in operations.py on a non-Windows checker.

Next: operator decides which reviewed commit the VPS checks out; then install extras, run
tests on the VPS, transfer the Firebase key securely, and run read-only .a symbol checks.

VPS code deployment (operator-approved pin, not a merge): C:/forex local branch paper-vps at
ccd00d7d236cbbff135fa3b41a376b9ffb1da6a5. Rollback: main 6b0273d8 plus the backup above.
pip install -e .[mt5,firebase,dev] completed in the VPS .venv (Python 3.13.15). On the VPS:
184 passed, Ruff clean, mypy "no issues found in 31 source files". Nothing started; paper,
demo, context, Telegram and cloud flags all still disabled. reports/ is now git-ignored.
Next: transfer PC .env and Firebase key to the VPS via RDP, fix the key path, verify presence.

VPS credentials: operator copied PC .env (813 bytes; old 311-byte VPS .env backed up) and
.secrets/firebase-admin.json via RDP. Firebase path line rewritten to C:/forex/.secrets/...
All seven FOREX_* settings present (values never displayed); key file parses as
service_account for forex-paper-bot. Operator confirmed MT5 password/Telegram token rotated.

VPS read-only MT5 check (2026-09-30T00:32:47Z, pinned ccd00d7): account 23011822
ICMarketsAU-Demo, DEMO, AUD, 1:30, broker balance AUD 200. EURUSD.a, GBPUSD.a, USDJPY.a all
FULL (mode 4) and visible in Market Watch; plain symbols CLOSE_ONLY. Live ticks 2-10 s old;
server clock check OK. Terminal Algo Trading switched OFF by operator (was ON) and the
read-only connection worked with it off. Close-only blocker resolved on the VPS. No orders.
Note: first run returned empty 0.0 ticks (time 0) straight after the .a symbols were
selected; MT5Broker.tick() does not reject an empty tick (paper freshness checks still
reject it as stale). Candidate hardening for review, not changed.

VPS service checks (pinned ccd00d7, from C:/forex): Groq openai/gpt-oss-120b PASS, JSON ok,
0.9 s, 117/48 tokens; Gemini gemini-3.1-flash-lite PASS, JSON ok, 1.5 s, 17/9 tokens; cost
not reported (unknown, not zero). OpenRouter google/gemma-4-31b-it:free HTTP 429 again on the
single allowed retry: unverified third fallback; no billing change. Telegram getMe and
getChat ok (no message sent). Firestore reachable for forex-paper-bot; access/operator present.

Operator approved the supervised PAPER configuration: paper, telegram, context and cloud
enabled; mode paper; demo_enabled false; emergency_halt_enabled false; AUD 100; New York
close. tests/test_paper.py candidate-provenance test now disables context explicitly instead
of relying on config.yaml defaults. 184 passed, Ruff clean.

Pre-start finding: PaperRuntime.heartbeat() journaled a balance and a health event every
cycle (paper.poll_seconds 5), and every journal event is queued for Firestore as one event
plus two aggregate writes: about 34,560 events and roughly 100,000 document writes a day.
That exceeds Firestore's free daily write allowance within hours and would bloat the local
journal. Proposed fix (needs operator approval before deployment): journal health/balance
at most every paper.health_journal_seconds (60, capped at 110, below the 120 s soak gap
threshold), and immediately on status change; the heartbeat file is still written every
cycle for the watchdog. Expected ~2,880 events and ~8,640 cloud writes a day. New regression
test fails on the previous code and passes now; 185 passed, Ruff clean.

First supervised start on the VPS (4055846, 2026-09-30 ~00:53 UTC) exited at once with
"Retrieve an MT5 tick before validating the broker server clock." run_paper validated the
clock before any tick had been read; unit tests used fakes and never exercised that order.
Nothing was created (no paper DB, heartbeat or journal) and no order was sent. Fix: read a
live tick for the first configured symbol (waiting up to broker.connect_timeout_seconds for
MT5 to deliver one) before the clock check; MT5Broker.tick() now rejects empty 0.0/time-0
ticks. New startup test reproduces the VPS error on the old code. 188 passed, Ruff clean.
Known limitation: startup clock validation needs a tick newer than the 300 s tolerance, so
a restart while the market is closed (weekend) will refuse to start until it reopens.

Pre-start finding 2: every cycle starts by reading a live quote per symbol, and
PaperBroker._quote rejects quotes older than execution.maximum_quote_age_seconds (30 s)
without regard to market hours. Any failed cycle journaled an "error" with a unique identity,
and errors go to Telegram and Firestore. Over a weekend close (~48 h at 5 s) that is ~34,000
Telegram messages and ~100,000 Firestore writes, plus bursts at the daily rollover pause.
Fix: every failure is still logged locally, but the journal records the first failure of a
streak, then at most one reminder per paper.error_repeat_seconds (3600), with consecutive
count and start time, and one "recovered" alert when a cycle succeeds again. Regression test
fails on the previous runtime. 189 passed, Ruff clean. Remaining known behaviour: no
heartbeat is written while cycles fail (e.g. weekends), so the soak report shows those
periods as unobserved gaps and a scheduled watchdog would halt; review before scheduling it.

Supervised PAPER run started on the VPS at 2026-09-30T01:07:05Z (1530190): first analysis ran,
a Groq context review returned HTTP 200, and a daily_summary alert reached the operator's
phone. SECURITY INCIDENT: httpx logs request URLs at INFO and Telegram URLs embed the bot
token, so the token was printed in the bot console, written to logs/forex.jsonl and pasted
into the assistant chat by the operator. Fix: httpx/httpcore loggers set to WARNING and a
redaction filter masks bot<id>:<token> patterns on console and file handlers; regression
test fails on the old code. 190 passed, Ruff clean. Required operator actions: stop the bot,
revoke the token in BotFather, set the new token in VPS and PC .env without displaying it,
redact old log files, deploy the fix, restart.

Supervised run on b0d8e41 from 01:19:29Z: the heartbeat stalled soon after start (188 s old
at the first status check) and later resumed; the operator stopped it with Ctrl+C at
01:44:33Z ("Paper loop stopped by operator; positions retained"). Probable cause: Windows
console QuickEdit selection after clicking in the bot window, which blocks the next console
write. start-paper.ps1 now disables QuickEdit for the bot's own console (warning if it cannot).
Firestore rejected one risk_decision event 13 times with InvalidArgument: exposure fields are
tuples of pairs, i.e. arrays inside arrays, which Firestore forbids. Cloud documents now wrap
inner arrays as {"items": [...]}; the local journal and payload hash are unchanged, and the
stuck event will deliver on retry. First evaluation (01:07Z): EURUSD and GBPUSD no_trade;
USDJPY candidate passed risk, Groq review VALID, execution recorded but no simulated order
was stored (reason to be read from the execution event). Paper balance AUD 100, no positions.
Test runs write warnings into the production logs/forex.jsonl (cosmetic; not changed).
192 passed, Ruff clean; PowerShell 7 parse check of all scripts clean.

Restarted on 906f682 at 2026-09-30T02:00:10Z: heartbeat fresh, entry-blocked [], balance AUD 100,
Firestore delivered 99 / waiting 0 / no errors (stuck risk_decision delivered after the fix).
The 01:07Z USDJPY attempt was BLOCKED by the fresh Layer 5 re-check. Finding: the runtime
decides with no requested objective (minimum 1.5R target from the decision-time entry), but
the pre-submit re-check passed that old minimum target as a fixed objective with the fresh
entry, so any adverse tick during the ~3 s AI review pushed reward:risk below 1.5 and blocked
the entry, while unchanged/favourable moves passed: a systematic favourable selection bias.
Proposed fix (execution semantics; needs operator approval before deployment): re-derive the
minimum target from the fresh entry unless an objective was explicitly requested; the reviewed
money-risk ceiling still applies; blocked details now name the Layer 5 reasons. New
parametrized test (1-tick and 5-pip adverse moves) fails on the old code. 196 passed, Ruff clean.

## Seven-day supervised PAPER observation — official start

- Start (runtime started_at_utc): 2026-09-30T02:16:08.567819Z on the Windows VPS, C:/forex,
  interactive console under the MT5 user session (scripts/start-paper.ps1).
- Code: ebb4311f67eb62f16d428b15f25552ecf0d2229c (branch claude/determined-thompson-f4ewei;
  PR #18 not merged; main unchanged). Runtime code fingerprint
  72cfd83c0ffb7081233679a3e8ab485a002051194308cb9ca80df974d7d22576.
- Config fingerprint ac6ff7dfc1d6806c92e28f2d604389c361a1c301bf38c0b3abd54b82884844fa:
  mode paper, paper/telegram/context/cloud enabled, demo_enabled false, remote halt false,
  AUD 100 virtual start, New York 17:00 rollover, symbols mapped to .a instruments.
- Opening state: virtual balance AUD 100.0, no open positions, entry-blocked none, Firestore
  135 delivered / 0 waiting / no errors. MT5 Algo Trading OFF; no broker orders possible.
- Evidence so far (same paper DB, earlier runs 01:07Z-02:16Z): 4 no_trade, 2 candidates,
  2 risk decisions, 1 hard_risk_block, 1 execution BLOCKED (fresh re-check, pre-fix).
- Operator decisions: Telegram token exposure accepted without rotation (operator choice);
  OpenRouter remains an unverified 429 fallback; no billing changes.
- Known limitations during the run: no heartbeat while markets are closed (weekend gaps are
  expected in the soak report); startup/restart needs an open market (clock check); no
  commission/swap/slippage in simulated P&L; no scheduled task/watchdog/reboot recovery yet,
  so a VPS reboot or Windows sign-out stops the bot until manually restarted.
- Planned review: after 2026-10-07T02:16Z run paper-soak-report and the Layer 11 diagnosis.

Operator usability request (2026-09-30): one-click VPS start and a simple phone dashboard.
- scripts/run-bot.ps1: launcher that disables QuickEdit, refuses a duplicate start, starts
  run-paper and retries every 120 s after a non-zero exit (e.g. market closed, MT5 down);
  a normal stop (Ctrl+C, exit 0) ends it. Log: logs/launcher.log. Simulated loop test passed.
- scripts/install-shortcuts.ps1: "Forex Paper Bot" icon on the Desktop and in Startup
  (starts at sign-in, e.g. after a reboot once the user signs in; no auto-logon configured).
- Dashboard: new default simple view (bot status, period dropdown, invested, profit, balance,
  trades, won, lost, open and latest trades); technical view kept under "Technical details";
  sign-in now persists on the device. 9 model tests and the browser setup test passed; phone
  preview rendered with no page errors or horizontal overflow.
- GitHub Pages: repo is public; Pages source set to GitHub Actions by the operator. Workflow
  now also deploys from this branch when DASHBOARD_DEPLOY_ENABLED=true. Pending operator
  steps: environment branch rule, four Firebase web variables, authorized domain
  iamarasinghe96.github.io.
- 2026-09-30 ~02:58Z: operator completed the Pages environment branch rule, the five repository
  variables and the Firebase authorized domain iamarasinghe96.github.io. Workflow run
  36661534530 (attempt 2, 072aa09) passed model, Firestore-rules, browser and build checks and
  deployed to https://iamarasinghe96.github.io/forex/. Phone sign-in on the live page is not yet
  verified (this agent's network cannot reach github.io).

2026-09-30 03:00Z: first simulated trade opened (USDJPY.a, trade_opened 03:00:10Z) after the
fresh-target fix. Immediately afterwards cycles failed intermittently with OperatorError and
recovered every 5-20 s, sending an error and a recovered Telegram alert per blip. Cause (code
analysis, reproduced by test): the cycle reads "now" once, then later reads quotes; with an open
position more work happens first, so a quote timestamped after "now" gave a negative age and
PaperBroker._quote rejected it as stale/invalid. Consequence: skipped stop/target management on
failed cycles and alert spam. Fix (needs deployment): accept quotes up to 5 s newer than the
cycle time (QUOTE_FUTURE_TOLERANCE_SECONDS, also in the pre-submit check); stale quotes older
than 30 s are still rejected. Failures now reach Telegram/Firestore only after persisting
paper.error_grace_seconds (30 s), with the OperatorError reason; recovery alerts only follow a
reported error. Both new tests fail on the old code. 198 passed, Ruff clean. The code
fingerprint of the observation run changes with this deployment (recorded as a version change).

## Research track (started 2026-09-30, parallel to the paper run)

Existing walk-forward reports (PC) aggregated out-of-sample by factor (gross, no costs):
confidence bands are inversely related to outcome (below-minimum +0.028 R, LOW -0.033, MEDIUM
-0.121, HIGH -0.323 over 11,445/10,274/3,175/130 signals) while the live policy skips the
below-minimum band and raises risk with confidence; trend-continuation setups +0.063 R (9,133)
vs range mean-reversion -0.064 R (15,891); swing +0.096 vs day -0.041; high volatility -0.075.
Long/short and trend-up/down asymmetries are treated as period-specific, not candidate rules.
Added scripts/research_trades.py (per-trade OOS export with conviction; verified on synthetic
data to reproduce run_walk_forward's aggregate OOS trade count and cumulative R exactly, no
holdout rows) and scripts/research_summary.py (assumed costs, one-position-per-pair sequencing,
setup x band table, candidate rules A/A-live/B/C, net by year). Research only; bot unchanged.

Per-trade OOS export on the PC reproduced the report counts exactly (EURUSD 8024, GBPUSD 8176,
USDJPY 8824). research_summary.py (assumed round-trip costs 0.9/1.2/1.0 pips, one position per
pair): current live rules -0.488 R/trade net over 6,643 trades, negative in every year 2021-2025;
trend setups with confidence >= 55: +0.040 R net over 361 trades (about 1.6/week across 3 pairs;
years -0.085/+0.162/+0.028/+0.082/-0.101), statistically indistinguishable from zero; trend swing
+0.044 R (273). Range mean-reversion is the dominant, consistent loser. Every-signal trend
results (+0.063, +0.170 at >=55) exceed first-signal-when-flat results, suggesting confirmation
entries may matter (scripts/research_entries.py tests signal-N-in-a-row, minimum stop size and
per-pair results). Added analysis.allowed_setups (default both families) and set config to
trend setups only with parameter_version trend-only-v1, pending operator approval to deploy.

### Pre-registration (recorded before any 2012-2018 data was downloaded or examined)

Candidate: trend setups only, confidence >= 55, enter only from the 3rd consecutive hourly
signal (same pair/direction/setup), one open trade per pair, EURUSD/GBPUSD/USDJPY, assumed
round-trip costs 0.9/1.2/1.0 pips. N=3 chosen over the better-looking N=4 to limit selection bias.
Pass rule: net average R > 0 AND net profit factor > 1, all pairs combined, on an independent
Dukascopy H1 bid dataset 2012-01-01..2018-12-31 (evaluation from 2012-04-01 after warm-up),
fetched with dukascopy-node 1.50.0 exactly as the original data. Evaluated by
scripts/research_candidate.py. Per-pair/per-year results are informative only. The 2025-09-28
final holdout stays untouched until after this test. Motivation and caveats: 2021-2025 OOS gave
+0.090 R/trade for this rule (253 trades) but all profit came from USDJPY's 2021-2024 trend.

Tooling: scripts/normalize_dukascopy_range.py (original checks; close clamped to own high/low
with every repair logged, abort above 50 per pair), research_trades.py --start-utc single-window
mode (exports all setup families regardless of live allowed_setups), research_candidate.py.
Verified on synthetic data: fold export still reproduces run_walk_forward exactly; repair,
import and validate_research_database succeed; single window starts at the requested time.

### Result of the pre-registered test (2026-09-30)

Independent Dukascopy H1 bid 2012-2018 (dukascopy-node 1.50.0, flats excluded, 0 repairs;
EURUSD 43,635 / GBPUSD 40,441 / USDJPY 42,009 rows; dataset bed3584927bd; evaluated from
2012-04-01). Pre-registered candidate: 349 trades, net -0.001 R, PF 1.00 -> VERDICT FAIL.
Confirmation-entry effect seen in 2021-2025 did not replicate. Supporting results (net, one
position per pair): all-setups current rules -0.425 R (9,548 trades, every year negative);
range mean-reversion negative in every band and year (confirms the trend-only switch); trend
setups with confidence >= 55: +0.028 R (475 trades, 5 of 7 years positive), consistent in sign
with 2021-2025 (+0.040 R, 361) but not distinguishable from zero. Conclusion: the current
signal has no demonstrated edge beyond break-even; further filtering would be data mining.
Final holdout remains untouched. Proposed next hypothesis (not yet registered): trend entries
with an ATR trailing exit (multiple 3, fixed a priori) instead of the fixed 1.5R target, which
must pass on both independent periods.

### Pre-registration 2 (recorded before any trailing-exit export was run on real data)

Hypothesis: the fixed 1.5R target truncates the large winners trend-following depends on.
Candidate "trend55 + trailing": trend setups only, confidence >= 55, every signal eligible,
one open trade per pair, all three pairs; exit model fixed a priori: no practical target
(reward_risk 1000), break-even at 1R (existing), then 3 x H1 ATR trailing stop, maximum hold
480 H1 bars. Assumed costs as before. Pass rule: net average R > 0 AND net profit factor > 1 on
BOTH independent periods: 2012-2018 (single window from 2012-04-01) and 2021-2025 (walk-forward
test windows, final holdout excluded). No other multiple or horizon will be tried before this
verdict is recorded. Tooling: research_trades.py --reward-risk/--atr-trailing/--horizon-bars;
research_candidate.py --rule trend55. Verified on synthetic data (exits become STOP/trailing only).

### Result of pre-registration 2 (trailing exit) and registration of the final-holdout check

trend55 + trailing (no target, break-even 1R, 3 x H1 ATR trail, 480-bar max), net, one per pair:
2012-2018: 418 trades, +0.013 R, PF 1.03 -> PASS. 2021-2025 (walk-forward test windows):
297 trades, +0.079 R, PF 1.16 -> PASS. Compared with the fixed 1.5R target (+0.028 / +0.040)
the trailing exit is not a clear improvement; combined about +0.04 R per trade, not
statistically distinguishable from zero. Consistent across all four runs (two periods x two exit
models): USDJPY positive (+0.063, +0.162, +0.313, +0.486 R), EURUSD and GBPUSD negative. Swap
costs for multi-day holds are not modelled.

Final-holdout registration (recorded before the holdout is examined; used once):
window 2025-09-28T16:00Z to the end of the original dataset, same exit model and costs.
Primary: trend55 + trailing, all three pairs; pass = net average R > 0 and net PF > 1; a failure
means the exit model is not deployed. Secondary (informational only, cannot rescue a failed
primary): the same rule on USDJPY alone. Expected sample about 60 trades, so a pass is weak
evidence while a clear loss is informative.

### Final holdout result (used once, 2026-09-30) and research status

Window 2025-09-28T16:00Z to 2026-09-28 (5,642 exported signals). Primary trend55 + trailing,
all pairs, net: 56 trades, -0.303 R, PF 0.51 -> VERDICT FAIL (EURUSD -0.080 R/18, GBPUSD
-0.321 R/17, USDJPY -0.480 R/21). Per the registration the trailing exit is NOT deployed; the
secondary USDJPY-only observation also failed, so the USDJPY pattern is treated as
period-specific. The final holdout is now consumed; any further look at it is exploration only.
Overall status: no variant of the current signal (all setups, trend-only, confirmation entry,
trailing exit) has shown a reliable edge across 2012-2018, 2021-2025 and the final year. The
live paper bot remains trend-only with the fixed 1.5R target for observation; real-money use of
this strategy is not recommended. Operator is studying trading to propose new hypotheses, which
must be pre-registered and tested on 2012-2018 and 2021-2025 (a fresh holdout will be needed).

### Protection scan on stored candles (exploration, 2026-10-01) and pre-registration 3 (J6-a, J6-b)

Operator asked to remove over-protective layers. Added switches, all off by default (live
behaviour unchanged): analysis.high_volatility_blocks_trend (J6-a), analysis.trend_efficiency_window
(J6-b), paper.target_reward_risk and paper.atr_trailing_multiple (J6-c). scripts/scan_protections.py
replayed the VPS's stored candles 2025-11-15 to 2026-10-01 (largely the consumed final-holdout year,
so exploration only), one layer removed at a time, live exits, A$100 balance, 2-5% sizing:
current rules took only 2 trades (+2.94 R, +A$9.35); about 1,300 idea-hours were stopped by the
conviction minimum and about 240 by the 0.01-lot minimum (a A$100 account cannot hold stops wider
than about 13-33 pips at 2-5% risk). Removing the conviction and lot limits gave 83 trades, 35% wins,
-3.59 R, -A$64.79, with up to 29% of the account at risk on one trade. Under those relaxed limits:
J6-a -5.29 R (worst trend variant), J6-b -1.44 R (only variant better than current), J6-a+b
-3.53 R, setup-strength threshold off -22.28 R, range setups on -438 R. On this year the blocked
trades lost on balance: the layers saved money rather than cost it. Live journal 30 Sep confirmed
the blocks in action (minimum volume over budget, conviction 54 < 55, stop on wrong side).

Pre-registration 3 (recorded before any J6 export exists): exports with research_trades.py
--analysis-set (J6-a: high_volatility_blocks_trend=false; J6-b: trend_efficiency_window=10), standard
exit (1.5R target, break-even 1R), on 2012-2018 (--start-utc 2012-04-01, dukascopy-2012-2018) and
2021-2025 (walk-forward test windows, dukascopy-research), evaluated with research_candidate.py
--rule trend55. A variant passes only if, on BOTH periods, net average R > 0, net PF > 1 and net
average R is above the baseline trend55 result on the same period (existing exports
trades-2012-2018.csv and oos-trades.csv). Window length 10 is fixed in advance; no other values
will be tried before the verdict. The account-size lines (A$100 / A$1,000) are information only.

### Fresh A$1,000 paper account (operator decision, 2026-10-01)

Operator chose option (a) until the J6 13-year results arrive: paper.database is now
data/paper-a1000.sqlite3 with starting_balance_aud 1000, so the 0.01-lot minimum fits the 2-5%
risk budget (stops up to roughly 130 pips at 2%). Strategy settings unchanged (trend-only, J6
switches off). The A$100 journal stays in data/paper.sqlite3. Journal summaries now carry
first_event_at_utc and the dashboard ignores closed trades mirrored before it, so the earlier
A$100 trade is not mixed into the new account's results. Real-money and demo execution stay disabled.

### Result of pre-registration 3 (J6-a, J6-b), 2026-10-01

trend55, standard exit (1.5R, break-even 1R), net, one position per pair; baseline = same rule on
the existing exports:

| Variant | 2012-2018 avg R / PF / trades | 2021-2025 avg R / PF / trades | Verdict |
|---|---|---|---|
| Baseline (current rules) | +0.028 / 1.06 / 475 | +0.040 / 1.09 / 361 | reference |
| J6-a volatility block off | +0.037 / 1.08 / 511 | +0.019 / 1.04 / 395 (below baseline) | FAIL |
| J6-b trend_efficiency_window=10 | -0.003 / 0.99 / 713 | +0.091 / 1.22 / 536 | FAIL |

Neither variant beat the baseline on both periods, so per the registration neither is switched on.
J6-b's strong 2021-2025 result (+48.7 R) did not repeat in 2012-2018 (-2.0 R): period-dependent,
led again by USDJPY (positive in every run so far, but it failed the final holdout). J6-a changed
little either way. Account-size lines: on A$100 only 0-2 trades in each period fit the 0.01-lot
minimum (median stops 72-86 pips), confirming the switch to the A$1,000 paper account; on A$1,000
the baseline keeps roughly the same result (+0.021 R and +0.067 R). Note: with drawdowns of about
16-17 R, the configured 2-5% risk per trade implies account drawdowns of roughly 30-60%.
Next research direction (to be pre-registered): J4-a slow time-series momentum (1-12 month trend),
the idea with the strongest external evidence.

### Operator-chosen aggressive paper profile and quiet-quote fix (2026-10-01)

Operator decision, PAPER only (real-money and demo execution stay disabled): parameter_version
operator-aggressive-v1 on the fresh A$1,000 paper account. J6-a on (volatility block off), J6-b on
(trend_efficiency_window 10), no confidence floor (conviction minimum 0), 5% risk on every trade,
daily loss circuit 25%, target 10R with a 3 x H1 ATR trailing stop after +1R. Kept: trend setups
only (range setups lost in every tested year), setup-strength threshold, AI news review, 20% total
open-risk cap. This profile is NOT validated: J6-a/J6-b failed pre-registration 3, the trailing
exit failed the final holdout, and the 2025-26 scan showed relaxed limits losing on that year. The
operator accepts the risk on paper to observe live behaviour; results will be judged as exploration.

Fix: Telegram/console "Paper quote is stale or invalid" errors came from a single pair not ticking
for 30 s (e.g. the 17:00 New York rollover), which failed the whole cycle. Now a quiet pair only
pauses its own entries and stop checks (valuation uses its last valid price); the cycle fails only
if a pair has no fresh quote for paper.stale_quote_alert_seconds (900 s), which still reports
weekend closures once and then hourly. Future-dated quotes still fail (clock fault).

### Learning loop with Telegram-approved strategy changes (2026-10-01)

Operator request: the bot should learn from each trade with AI reasoning, build a score per
strategy decision, and apply operator-approved changes without VPS logins or code edits, using a
prompt the operator pastes into Claude and a reply pasted back. Built (docs/LEARNING_LOOP.md):
- src/forex/learning.py: trade facts from journal provenance; decision buckets (pair, regime,
  session, style, volatility, pair+side, pair+regime); shrunk score = total R / (trades + prior);
  size factor (only down, floor min_factor, after min_trades); StrategyPatch, a strict whitelisted
  and bounded JSON change set (no code); overlay merge/apply; Claude review prompt builder.
- src/forex/learning_worker.py: background scoring and AI post-mortem per closed trade
  (src/forex/prompts/trade-postmortem-v1.md); rule-based fallback; Telegram "Trade review" message.
- src/forex/telegram_commands.py: operator-chat-only commands /scores /settings /review (prompt
  file) /approve /reject /rollback; pasted replies become PENDING change sets until approved.
- Runtime: reloads the approved overlay (data/<paper db>.strategy-overlay.json) each cycle,
  rebuilds risk policy/execution, announces "Strategy updated", skips paused pairs, applies the
  learned size factor after the AI news review. Invalid overlay keeps current settings and alerts.
- config: learning section enabled. Safety: patches cannot touch execution, credentials or files;
  learning cannot raise size above configured risk; real-money and demo execution stay disabled.
Tests: tests/test_learning.py (end-to-end trade -> score -> review -> Telegram message, sizing,
whitelist rejection, overlay merge, approval/rollback, operator-only chat, runtime reload, paused
pair, broker-suffix symbols).

### Fix: one open trade per pair (2026-10-01)

Live observation on the A$1,000 account: four EURUSD shorts opened at 09:00-12:00 UTC, one per
hourly signal. The runtime only capped total positions (4) and total open risk (20%); research and
scans always assumed one position per pair, and the old confidence floor had hidden the gap.
Added paper.max_positions_per_pair (default and config 1): further signals on a held pair are
journaled as no_trade "Already holding N ...". Existing open trades are managed normally.
Telegram daily summary now reads "Daily summary <day>: N trades closed (W won, L lost), P&L A$x".

### Codex review fact-check and new research tools (2026-10-03)

Codex (operator's second reviewer) produced a plan, ALPHALEDGER_REVIEW.md, RESEARCH_TEST_SPEC.md and
draft PR #19. Fact-check in docs/CODEX_REVIEW_FACTCHECK.md: live ATR trailing never activated
(cache key EURUSD vs position EURUSD.a) - TRUE, PR #19 fix reviewed and correct; short-trade review
excursions wrong - TRUE (review text only); research censors trades near walk-forward window ends and
uses a 120-bar time exit unlike live - TRUE, magnitude unmeasured; random controls and slow momentum
never run - TRUE. Added scripts/causal_replay.py (single chronological stream, live-equivalent exits,
1,000 matched random-entry controls) and scripts/slow_momentum.py (spec section 3 benchmark with
flat/constant-long comparators, cost/financing stress, block bootstrap). Verified on synthetic data
only; this session's network policy blocks datafeed.dukascopy.com and app.alphaledger.ai.
Power note: detecting +0.03 R/trade at 2 SE (SD ~1.2 R) needs ~6,400 trades.

### PR #19 merged and held-pair ATR refresh (2026-10-03)

Merged Codex PR #19 (operator approval): runtime caches trailing ATR under the broker symbol
(EURUSD.a) used by paper positions, so the configured 3 x H1 ATR trail now activates after +1R;
short-trade review excursions corrected. Added refresh_position_atr: for every held pair the 14-bar
H1 ATR is recomputed at most hourly from closed MT5 candles when the hourly analysis did not supply
it (restart, paused pair, quiet quote); failures keep the previous value. Deploying this tightens
the stops of open trades that are past +1R (locks part of their open profit). No time-based exit
exists in the live bot; the 120/480-bar time exits were research-only.
Update: Codex INDEPENDENT_TRADE_AUDIT matches all nine recorded variants exactly; measured per-trade
SD ~1.06 R (power ~5,000 trades for +0.03 R). causal_replay now fills gapped stops at the open; the
learning score's n/(n+20) is labelled "evidence weight". Rebuilt research DBs on the PC from the
normalized CSVs: 2012-2018 fingerprint bed3584927bd (identical); 2019-2026 4475c2ba5eff vs original
185c5a2aa877 (same row counts; at least one input CSV differs, likely the 13 tick-repaired EURUSD
candles). AlphaLedger: Gold Reaper basket verified; its early shorts were >= -$1,398 floating.

### Causal replay, random-entry controls and slow momentum on real data (2026-10-03)

Run by the operator on the PC (read-only research DBs). Full verdict: docs/CODEX_REVIEW_FACTCHECK.md.

| Period | Trades | Mean net R | PF | Total R | Random controls mean R | Controls >= strategy (total / mean) |
|---|---|---|---|---|---|---|
| 2012-2018 (never used for design) | 427 | +0.026 | 1.054 | +11.2 | -0.069 | 4.1% / 3.4% |
| 2021-2025 (development data) | 322 | +0.042 | 1.084 | +13.4 | -0.048 | 7.0% / 5.9% |

- Entry timing beats 1,000 matched random entries (same H4 direction, stops, exits, costs, entry
  rate) by about +0.09 R/trade in both periods. Fisher-combined share ~2%; the clean evidence is
  2012-2018 alone (~4%).
- The net edge stays small (+0.03 to +0.04 R/trade), inside the bootstrap noise of a 5,000-trade
  power requirement and close to zero under doubled costs.
- Pair concentration: USDJPY +23.7 / +34.2 R, EURUSD +4.5 / -12.8 R, GBPUSD -17.0 / -8.0 R
  (2012-2018 / 2021-2025). Dropping GBPUSD now would be selected on these results; it must be
  pre-registered and tested on data not yet examined (other pairs).
- Window-boundary censoring (Codex claim 4) is negligible: causal +0.026 vs walk-forward +0.028
  (2012-2018); +0.042 vs +0.040 (2021-2025).
- Slow 3-pair momentum (2013-04 to 2026-09): +0.70%/yr, Sharpe 0.17, max DD 20%, versus
  constant-long +0.66%/yr; paired difference CI [-0.31, +0.34]%/month -> FAIL; -0.78%/yr under
  cost/financing stress. Not adopted.

### Cost recorder and noise-resistant learning (2026-10-03)

Cost recorder (Codex item 6):
- `src/forex/costs.py` samples the live bid/ask spread of every pair each paper cycle and writes
  hourly mean/median/p90/max to `cost_hours` in the paper DB, with MT5's published swap rates
  (read-only `symbol_info`).
- Each paper entry's `execution` event now records the spread paid (`entry_spread_pips`,
  `entry_spread_r`).
- `scripts/cost_report.py` compares these with the research costs (0.9/1.2/1.0 pips), shows the
  spread by UTC hour, and estimates the swap the paper trades would have paid. The paper account
  already pays the live spread; swap and commission are not charged.
- Observation only: fills and P&L are unchanged, and a sampling failure is logged without
  interrupting trading.

Learning loop:
- Scores are computed per settings version: a hash of the analysis and exit settings, recorded
  on every candidate.
- Approving an analysis or exit change starts fresh scores. Earlier trades show per version
  (pre-version trades are `legacy`).
- Sizing now shrinks a trade only for buckets whose average R plus `learning.evidence_z` (2.5)
  standard errors is still below 0. Standard errors use a spread of at least 1 R; measured
  1.04-1.08 R.
- `evidence_z` is in config.yaml only, not in the review whitelist.
- Telegram `/scores`, trade reviews and the `/review` prompt show `avg ± SE` and the version.
  The review instructions now carry the random-control results.
Deployed to the VPS on 2026-10-03 (Saturday, market closed): C:\forex moved from 0a4ac35 to
119a87f. Paper DB backed up to C:\forex\backup first; no halt latch; 235 tests passed on Windows.
This also brings PR #19 trailing, the held-pair ATR refresh and the weekend notice to the VPS.

### Pre-registration 4: classic swing-structure rules (recorded 2026-10-03, before any real data run)

Background and mapping to the bot: docs/SWING_TRADING_REVIEW.md. Script:
scripts/swing_structure.py, verified only on hand-built and random-walk data.

**Rules, fixed:**
- Swing points are 2-bar fractals.
- Trend: the last two swing highs and the last two swing lows both rising (or both falling).
- Consolidation: the 10 bars before the signal span at most 3 x ATR(14).
- Entry: a close beyond the consolidation in the trend direction.
- Stop: the far side of the consolidation, at least 1 x ATR away.
- Exit: the stop trails to each new confirmed swing low (high). No target.
- Costs: round trip 0.9/1.2/1.0 pips; one trade per pair.

**Primary test (decides PASS/FAIL): H4 bars, EURUSD/GBPUSD/USDJPY.**
- P1: 2012-04-01 to 2019-01-01.
- P2: 2019-01-01 to the end of the data. This includes the 2025-26 holdout that was consumed
  for the old strategy; it is unseen for these rules.

**PASS only if every condition holds in both periods:**
- at least 100 closed trades;
- mean net R > 0;
- no more than 5% of 1,000 matched random controls (seeds 2026100400+) reach the strategy's
  mean R.

**Secondary, reported only (cannot rescue a FAIL):**
- D1 bars (UTC days from H4);
- costs x2 on H4;
- per-pair and per-year breakdowns;
- R per year compared with the current strategy's causal replay. The current strategy made
  +11.2 R over 2012-04 to 2018 (about 1.7 R/yr) and +13.4 R over 2021-2025 (about 2.9 R/yr).

**After the results:**
- No parameter is changed after seeing results.
- A FAIL is recorded as a FAIL.
- A PASS makes the rules a candidate for a separate paper strategy, not a replacement for real
  money.

### Result of pre-registration 4, live-settings replay, and corrections (2026-10-03)

Run by Codex (read-only, operator PC, commit f7a8def); verdicts in
docs/CODEX_REVIEW_FACTCHECK.md "Round 2".

**Pre-registration 4 (swing structure): FAIL.**

| Period | Trades | Net R/trade | Controls ranked |
|---|---|---|---|
| H4 2012-2018 | 436 | -0.005 | 0.40 |
| H4 2019-2026 | 511 | about 0.000 | 0.57 |

The pass required controls ranked at or below 0.05. D1 (secondary): -0.034 and -0.219 R.
Classic swing rules are not adopted.

**Live settings, replayed with the old replay semantics.**

| Period | Trades | Net R/trade | At 2x costs |
|---|---|---|---|
| 2012-2018 | 807 | +0.043 | |
| 2021-2025 | 681 | +0.065 | |
| 2025-09 to 2026-09 | 125 | +0.017 | -0.002 |

USDJPY alone exceeded the total in both development periods. These settings were chosen after
seeing those periods.

**Correction to "Causal replay, random-entry controls..." above.**
- The controls were not matched on regime or stop width. Their cost per R was about 4x the
  strategy's.
- Before costs, the strategy's advantage is about +0.025 R/trade (within noise), not +0.09 R.
- The entry logic's skill is unproven. Most of the measured advantage was cost efficiency.
- causal_replay.py is fixed: matched controls, the live stop rule, data-hole segmentation,
  and gross/net output. The bot's /review prompt is corrected.

### Pre-registration 5: replication with the corrected replay (recorded 2026-10-03, before any run)

**Steps:**
1. Run `scripts/data_coverage.py` on both databases. Any 48+ hour gap inside a test period is
   re-downloaded and the database rebuilt first. Where that is impossible, the replay censors
   trades across the hole, and the count is reported.
2. Run R-A, the baseline research settings:
   `--profile baseline --min-conviction 55 --target-r 1.5` (break-even at 1R, no trail).
3. Run R-B, the live settings:
   `--profile config --min-conviction 0 --target-r 10 --trail-atr 3`.

**Periods:**
- P1: 2012-04-01 to 2019-01-01.
- P2: 2021-01-01 to 2025-09-28 (development data).
- P3: 2025-09-28 to the end of the data (reused; information only).

1,000 controls; seeds fixed by the script.

**Questions and pass rules (P1 and P2 both required):**
- Q1, direction skill: matched controls (gross) share at or above the strategy's mean R ≤ 0.05.
- Q2, profitable signal: net mean R at 2x costs > 0.
- Q3, not only USDJPY: net mean R excluding JPY pairs > 0.

**Interpretation, fixed now:**
- Q2 yes but Q1 no: the profit is trend-direction exposure plus cost efficiency, and the hourly
  entry logic adds nothing. Simplify rather than tune.
- Q3 no: USDJPY concentration. Test on new pairs before any further conclusion.

No settings change based on these runs.

### Pending operator decisions (live paper bot unchanged)

1. Margin realism: paper sizing ignores notional margin, so some 5% trades are impossible on a
   real A$1,000 30:1 account.
2. H4 alignment: build live H4 bars from MT5 H1 with fixed UTC boundaries, as in research,
   instead of broker-midnight H4 bars.
3. Risk per trade: Codex recommends 0.25% for research-comparable paper and 0% real money until
   an edge is established; the current setting is 5%.

### Operator decisions on the Codex findings (2026-10-03): margin yes, research H4 yes, risk stays 5%

**1. Margin realism (`risk.enforce_margin: true`)**
- `size_position` caps volume so that margin fits the account's free margin. Margin =
  notional / account leverage; notional per lot = price / tick_size x tick_value. Open positions
  count at their entry prices.
- If even the minimum lot does not fit, the trade is blocked with
  INSUFFICIENT_FREE_MARGIN_AT_ACCOUNT_LEVERAGE.
- On A$1,000 at 30:1 the whole account can hold about A$30k notional. At 5% risk a 15-pip
  EURUSD stop is cut from 0.22 to 0.18 lots (4.05% risk). A 20-pip stop uses about 90% of the
  margin, so often only one or two trades fit at once, as on a real account.
- No margin call or stop-out is simulated.
- Policy identity changes only when the switch is on.

**2. Research H4 bars (`market_data.h4_alignment_hour_utc: 0`)**
- The paper bot no longer requests MT5 H4 candles. It builds H4 from the stored MT5 H1
  candles with `history.aggregate_h4`, as the research databases were built: complete groups at
  00/04/08/12/16/20 UTC.
- MT5's H4 bars start at the broker's midnight (21:00/22:00 UTC).
- `replay_decisions.py` and `scan_protections.py` now build H4 the same way. Older MT5 H4 rows
  stay in the paper database, unused.
- The settings version now includes the H4 rule, so learning scores restart. No trades closed
  since the 119a87f deploy (weekend).
- `scripts/data_coverage.py` prints the alignment recorded in each research database to
  confirm 0.

**3. Risk per trade:** stays at 5% (operator choice; Codex recommended 0.25% for research and
0% real money).

Tests: 249 passed; ruff clean; mypy shows only the two Windows-only msvcrt errors.

### Setup score merged from Codex (codex/setup-score 32cc58b), shadow only (2026-10-03)

Codex implemented docs/SETUP_SCORE_SPEC.md:
- dataset export: scripts/export_setup_dataset.py;
- fixed-order model training with purged yearly walk-forward folds and unseen-pair confirmation:
  scripts/train_setup_score.py and scripts/setup_score_training.py, with the optional extra
  `score-training` (numpy, scikit-learn);
- portable JSON scoring with hash and feature checks: src/forex/scoring.py;
- quarter-Kelly risk mapping, used only when activated: risk.risk_percent_for_score;
- shadow logging on every candidate, score bands in learning, and score plus risk in Telegram
  trade alerts.

Usage: docs/SETUP_SCORING.md.

**Defaults are scoring.enabled false and shadow true.** With no model file, candidates record
"unavailable" and sizing is unchanged. Activation refuses to start unless:
- the model passed 7/7 in both periods and on six unseen pairs;
- settings match the model;
- the journal holds at least 28 days of shadow scores for that model hash.

**Merge review (Claude):**
- Kept the margin cap: the score sets the risk percent first, then size_position applies the
  margin cap.
- The settings version keeps the H4 rule and adds the model hash. The model's strategy
  signature now includes the H4 alignment.
- The export moved onto the corrected causal replay: live protective_stop exits, data-hole
  segmentation, and censored trades excluded. Codex's opportunity, feature and cost options were
  re-applied.
- Shadow scoring errors no longer stop trading: they are recorded as status "error". Activated
  sizing still fails closed.

Tests: 269 passed with training extras. A clean environment without scikit-learn, like the VPS,
gives 259 passed, 1 skipped. Ruff clean; mypy only the two Windows-only errors.

No historical model exists yet. Acceptance needs the research databases plus downloaded
AUDUSD/USDCAD/USDCHF/NZDUSD/EURJPY/GBPJPY history for the unseen-pair confirmation.
Deployed to the VPS on 2026-10-04 (market closed): C:\forex at 6202416, clean tree, 259 passed and
1 skipped (scikit-learn not installed, as intended). Includes the margin cap, research-aligned H4
bars and shadow setup scoring with no model loaded.

### Data coverage and pre-registration 5, period P2 (2021-01-01 to 2025-09-28), 2026-10-04

**Coverage (scripts/data_coverage.py, operator PC):**
- Both research databases build H4 bars on fixed UTC boundary hour 0, matching the paper bot.
- 2019-2026 is complete apart from New Year holidays.
- 2012-2018: EURUSD is complete. Whole months are missing for GBPUSD (2012-05, 2013-08,
  2013-09, 2014-07, 2017-10, 2018-11) and USDJPY (2012-05, 2012-08, 2016-12). Codex's claim is
  confirmed. Likely cause: empty monthly responses during the download.

**R-A, baseline research settings.**
- Strategy: 322 trades. Net +0.039 R, 2x costs +0.024 R, gross +0.055 R. Month-block 95% CI on
  net: [-0.087, +0.166].
- By pair: USDJPY +34.2 R; EURUSD -12.8 R; GBPUSD -8.8 R. Excluding JPY: -0.110 R/trade.
- By side: longs +0.103 R, shorts -0.049 R.
- Matched controls: net +0.003 R; gross +0.019 R (share at or above strategy 0.176). Broad
  controls net: share 0.055, the earlier "beats random" figure.

**R-B, live settings.**
- Strategy: 728 trades. Net +0.055 R, 2x costs +0.040 R, gross +0.071 R. CI on net:
  [-0.043, +0.150].
- By pair: USDJPY +45.1 R; EURUSD +0.1 R; GBPUSD -4.8 R. Excluding JPY: -0.010 R/trade.
- By side: longs +0.106 R, shorts -0.015 R.
- **Matched controls: net +0.087 R, gross +0.104 R. Random entries in the same trend regimes,
  with the same stops and exits, did better than the strategy (share 0.93-0.94).**

**Verdict for P2:**
- Q1 (direction skill): FAIL in both runs.
- Q2 (net at 2x costs > 0): yes in both.
- Q3 (excluding JPY > 0): FAIL in both.

Q1 and Q3 must pass in both periods, so they cannot pass overall whatever P1 shows. The P1 run
is optional and informational: it needs the missing months re-downloaded, or it runs with
censoring.

**Pre-registered interpretation applies:**
- The profit is H4 trend-direction exposure with wide stops and the trailing exit, concentrated
  in USDJPY longs.
- The hourly entry logic adds nothing; under live settings it is worse than random timing.
- Simplify rather than tune. Test on new pairs before any further conclusion.
- No live setting is changed by this result.

### Dashboard: open-trade P&L and price charts (2026-10-05)

**Bot:**
- Health snapshots now include each open trade's opening time, initial stop and open R
  multiple.
- A new `position_chart` journal event is published hourly, and whenever the set of open
  trades changes. It carries each open trade's H1 bars from 24 hours before entry, at most
  240 bars.
- The Firestore mirror keeps the latest chart in `modes/PAPER/aggregates/chart`, as parallel
  arrays with no nested arrays. Operator read rules already cover it.
- Chart failures are logged and never interrupt trading. Nothing is published while halted.

**Dashboard (dashboard/src/chart.js, model.js):**
- New "Open trades P&L" and "Equity if closed now" tiles.
- Each open trade shows its facts and an SVG chart:
  - close line and high-low ranges;
  - entry dot, solid stop and dotted first stop, dashed target or an off-chart note, current
    price dot;
  - direct labels that never overlap, and a hover/tap crosshair readout;
  - a plain-English key and a table view.
- The chart is sized to the screen. Status red and green are never the only cue (line style
  and text labels).
- Checked visually at desktop and phone widths with sample data.

Tests: 273 passed with training extras; a clean VPS-like environment gives 263 passed, 1 skipped.
Dashboard: 11 node tests pass and the build succeeds.
Deployed to the VPS on 2026-10-05: C:\forex at 5345525, 263 passed and 1 skipped. Includes the
dashboard chart publisher; the dashboard itself was published by the Pages workflow (build and
deploy succeeded).

### Loss review prompts for ChatGPT (2026-10-09)

**Operator request:** after every loss, a copyable prompt that explains the bot's strategy and
structure, and what happened in the trade. It is for ChatGPT without Codex, which has no access
to the repository. ChatGPT's answer comes back to Claude Code. Process: docs/LOSS_REVIEWS.md.
Ledger: docs/LOSS_LESSONS.md.

**Bot:**
- `src/forex/loss_review.py` builds the prompt about an hour after each losing trade, so the exit
  bar is stored. It is triggered from the learning worker and stored as a `loss_prompt` journal
  event.
- The prompt contains:
  - the instructions and research so far, from
    `src/forex/prompts/loss-review-chatgpt-v1.md`; Claude Code keeps the research list current;
  - the live rules, generated from the settings;
  - the trade's facts and the bot's own entry record;
  - hourly prices in R from 24 hours before entry, with the stop-setting, entry and exit hours
    marked;
  - a DST-aware market clock;
  - the account's closed trades and other open trades.
- The prompt has no account identifiers.
- Losses closed in the last 14 days get a prompt, so the 7 Oct USDJPY loss gets one after the
  update.
- Delivery:
  - Telegram sends the prompt as a `.txt` file (`TelegramAlerter.send_document`);
  - `/loss` resends the latest one;
  - prompt failures are logged and never affect trading or learning.
- The clock is read only when a prompt may be due. A shared test clock caught an earlier
  version that read it every 30 s.
- `JournalStore.find` and `JournalStore.of_kind` were added.
- `learning.loss_prompts: true` (default true).

**Dashboard:**
- New "Learn from losses" section: Copy prompt for ChatGPT, Download as a file, Show the prompt.
- Checked at phone width against a fake offline Firebase: Copy put the newest prompt on the
  clipboard, with no page errors and no sideways scrolling.

**Tests:** 280 passed (7 new: prompt content and timing, Telegram file, /loss, Firestore
safety, no prompt for wins or when switched off, DST market clock, price-table markers). Ruff
clean; mypy shows only the two Windows-only errors. Dashboard: 12 node tests pass, the build
succeeds, and the browser test passes.

**Testing ChatGPT's proposals from Claude Code needs historical data.** The cloud environment's
network policy blocks `datafeed.dukascopy.com` (403), so the operator must allow it there, or the
tests run on the PC.
