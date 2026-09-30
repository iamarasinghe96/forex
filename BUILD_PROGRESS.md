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
