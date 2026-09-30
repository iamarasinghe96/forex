# Evidence-gated performance intelligence

Layer 11 is a research tool. It observes the complete PAPER journal, including generated,
rejected, risk-blocked and no-trade decisions. Diagnosis counts each state, records source
identities/fingerprints and emits evidence-backed attribution with no causal certainty.
It never turns a recent losing streak into a trading veto or edits production parameters.

Workflow:

1. Run `forex diagnose --start-utc <UTC> --end-utc <UTC>` after genuine paper evidence exists.
2. Write a hypothesis, explicit candidate parameters and pre-registered acceptance criteria
   to a local JSON file. Criteria have no default promotion thresholds: choose justified
   minimum history (at least five years), folds, OOS sample, real shadow/paper durations,
   net expectancy and maximum drawdown before examining candidate test results.
3. `forex experiment-propose --file <proposal.json> --start-utc <UTC> --end-utc <UTC>` records
   the complete diagnosis, hypothesis and criteria as an immutable candidate hash.
4. Independently run historical/recent tests, completed walk-forward folds and untouched
   OOS, then shadow and paper observation. Produce `ExperimentEvidence` JSON reports bound
   to that version, Git SHA and dataset fingerprint, with SHA256 references to source
   artifacts. The Pydantic model in `forex.intelligence` is the exact report schema.
5. Attach each report with `forex experiment-attach --version <hash> --file <report.json>`.
   Stage reports are immutable. Changed parameters, criteria or results require a new
   experiment rather than overwriting inconvenient evidence.
6. `forex experiment-status --version <hash>` checks all six stages, source/report hashes,
   pre-registration timing, separate holdout windows, complete costs, verified broker H4,
   explicit performance criteria and actual elapsed operational evidence.
7. Only complete evidence reaches READY_FOR_OPERATOR_REVIEW. The optional Python registry
   method `record_review` stores an explicit reviewer/reference and evidence fingerprint;
   it does not merge code, rewrite config, activate a strategy or authorize real money.

Evidence producer assertions remain assertions: file hashes prove artifact integrity, not
that a broker assertion or profitability claim is true. Independent review must trace
reports to actual runs and source data. The existing Bid-only fixed-UTC Dukascopy baseline
does not satisfy cost/H4/OOS/soak gates and is not automatically imported as passing evidence.
Synthetic fixtures exist solely in tests and never enter the operator registry.

Recent-window diagnosis and hypothesis creation are implemented; autonomous parameter
search/automatic production adaptation is deliberately absent. Existing Layer 4 replay,
walk-forward and cost provenance APIs are the research engine. Candidate experiments must
be run with a separately reviewed configuration, preserving the frozen baseline and final
holdout. No experiment or parameter promotion has been validated by this build.
