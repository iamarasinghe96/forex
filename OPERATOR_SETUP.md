# Operator setup still required

Development uses disabled integrations and offline fixtures until the operator completes setup.
Do not put credentials in this file, Git, a chat message, screenshots or logs.

- [ ] Review and approve semantic/architecture PRs before merge; main is unchanged.
- [ ] Resolve or explicitly bound fixed UTC research H4 versus broker DST alignment.
- [ ] Obtain genuine historical spread/commission/slippage/swap evidence; no cost guesses.
- [ ] LLM: select model IDs and provider order; configure Groq/Gemini/OpenRouter keys in local .env.
      Model costs remain unavailable unless reported by the provider; no free-tier/pricing assumed.
- [ ] MT5 demo: verify account/currency/leverage, current prices/specs, symbol suffixes, server clock,
      market permissions and hedging/netting behavior. Never use real-money production for verification.
- [ ] Firebase: project, VPS-only Admin credentials, web configuration, operator Auth UID,
      default-deny rules/indexes and emulator tests before deployment.
- [ ] Phone alerts/emergency controls: Telegram token/chat or chosen authenticated server endpoint.
- [ ] Hosting: GitHub Pages and any privileged Vercel endpoint need explicit project configuration.
- [ ] Windows VPS: MT5 session, service account, startup/recovery, backups, clock and network checks.
- [ ] Run actual unattended paper soak and collect elapsed-time/failure-recovery evidence.
- [ ] Review Layer 11 candidate evidence and explicit version promotion; no automatic mutation.
- [ ] Real-money production is outside this build target and requires separate approval.

No auto-retry after a Codex usage reset is configured; a persistent development goal and progress
notes preserve continuity while the session can run.

Layer 7 follow-up:
- [ ] Choose the UTC daily risk-session boundary; currently null and not guessed.
- [ ] Verify broker order comments/IDs survive position/order/deal history and restarts.
- [ ] Exercise actual demo partial/rejected/ambiguous orders, netting/hedging, fill modes and stops.
- [ ] Decide emergency flatten scope for any manual positions; bot transport never closes them silently.
- [ ] Verify stop/close read-back before retrying any ambiguous management action.

Layer 8 follow-up:
- [ ] Install optional Firebase Admin SDK and configure the local credential-file environment variable.
- [ ] Deploy reviewed rules/indexes; create Admin-only access/operator with the approved Auth UID.
- [ ] Run security-rule emulator tests and confirm unauthorized reads and all browser writes fail.
- [ ] Exercise outage/reconnect and local/cloud divergence recovery with the actual project.
- [ ] Review reserve-ledger treatment and export with the operator's accountant; no tax classification is asserted.
