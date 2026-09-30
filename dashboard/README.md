# Operator dashboard

Read-only, mobile-first Firebase Auth/Firestore client for GitHub Pages. No service-account
key, order submission, database writes or emergency controls belong in this application.
Firestore rules are the authorization boundary: only the UID configured by the administrator
in `access/operator` may read PAPER/DEMO records. A successful Google sign-in alone grants
no financial-data access. Sign-in persists on the operator's own device until Sign out (read-only access only).

Install Node 24, run `npm ci`, `npm test`, `npm run build` in this directory. `npm run dev`
opens a local development server. With no configuration it displays setup pending and makes
no Firebase connection. Copy `.env.example` to `.env.local` and supply only the four public
web-app values after deploying the deny-by-default rules. Enable Google sign-in and add the
local/Pages hostname to Firebase Auth authorized domains.

The Pages workflow builds and tests PRs. Deployment additionally requires main and repository
variable `DASHBOARD_DEPLOY_ENABLED=true`, Pages configured for Actions, and the four named
Firebase web variables. These are public identifiers, not Admin credentials. Deployment is
left disabled until operator authorization and security rules are verified.

All-time cards read precomputed aggregates. History loads 100 records per page; pair,
timeframe, day/swing and UTC-date filters operate on the loaded subset, explicitly labelled.
Load older records before interpreting a longer period or exporting its evidence. Daily
balance observations are not an intraday maximum-drawdown measurement. Profit factor with
no losses is unavailable rather than an invented infinite ratio. Costs remain labelled
incomplete. Tax grouping uses Sydney dates and is a reserve estimate, not tax advice.

Local complete CSV export is also available from `JournalStore.export_csv`; preserve it
for complete accounting evidence. Cloud data may lag during outages. Missing/stale heartbeats
are unknown, never proof that the process is stopped. Emergency actions belong in the
separate operator procedure, not this read-only view.

Implementation follows Firebase's official [Auth guide](https://firebase.google.com/docs/auth/web/start)
and [snapshot listener guide](https://firebase.google.com/docs/firestore/query-data/listen).
Actual authorized/unauthorized cloud sign-in and deployed security rules still require
operator setup and external verification; local model tests do not certify those checks.

Security verification: local Firestore emulator tests passed for operator/stranger/anonymous reads, mode restrictions, every client write, operator-record replacement and revocation. Run npm run test:rules with Java 21. This does not certify deployed project IAM or Auth settings. Current npm audit --omit=dev reports zero vulnerabilities; firebase-tools development dependencies report five moderate transitive advisories (OpenTelemetry/uuid). No forced major downgrade was applied.

Simple view (default): bot running/stopped, a period dropdown (24 hours to all time) with the
Sydney date range, invested amount (current balance minus all-time recorded P&L), profit, trades
made, won and lost, open trades and the latest ten closed trades. It reads `trade_closed` events
with a single-field `kind` query plus the `aggregates/all` summary. The earlier detailed operator
view is kept under "Technical details". Until PR #18 is reviewed and merged, the workflow also
publishes from `claude/determined-thompson-f4ewei` (the reviewed branch running on the VPS).
