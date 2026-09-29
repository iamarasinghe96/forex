# Operator dashboard

Read-only, mobile-first Firebase Auth/Firestore client for GitHub Pages. No service-account
key, order submission, database writes or emergency controls belong in this application.
Firestore rules are the authorization boundary: only the UID configured by the administrator
in `access/operator` may read PAPER/DEMO records. A successful Google sign-in alone grants
no financial-data access. Sessions remain in memory and require sign-in after refresh.

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
