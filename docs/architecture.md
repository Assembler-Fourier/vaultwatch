# Architecture

VaultWatch combines financial-risk signals and login anomalies in a synthetic local workflow. Each service has a distinct job; the dashboard talks directly to Python, rather than routing every request through Go.

## One transaction

1. **Create input.** A manual scenario or balanced batch constructs a transaction and its history/context. Data and coordinates are fabricated.
2. **Check rules.** Python calls Rust over HTTP. Rules consider amount, velocity, new devices/recipients and impossible travel. Rule points are capped at 100.
3. **Apply the prefilter.** A Python IsolationForest checks the synthetic feature vector. Its score is an anomaly indicator, not a measured fraud probability.
4. **Escalate when needed.** Triage can stop or request investigation. The investigator requests transaction history, entity links and a synthetic sanctions-list check. Returned tool evidence is saved with the case.
5. **Draft when requested.** The compliance stage creates an explicitly synthetic narrative when investigation recommends review. Its absence does not mean a case was closed at the initial checks.
6. **Correlate security.** A recent Go login anomaly for the same account can upgrade an investigated financial alert to critical severity.
7. **Apply payment policy.** Policy `local-demo-v2` separates final risk from payment action. Critical risk or a watchlist hit blocks execution; high risk and unresolved signals hold it. Clear cases can reach the simulator only after the policy audit verifies.
8. **Persist.** Python saves the resulting transaction, events, investigation, audit receipts and simulated payment decision to PostgreSQL. The UI can read the saved record and export it as JSON or a printable HTML report.

No step sends a real payment. A simulation receipt is a synthetic record, not settlement confirmation.

## Login correlation

The takeover scenario creates a synthetic account and performs two local Go login requests at supplied coordinates. Go publishes the anomaly to Redis. Python's subscriber matches the warning to the transaction account.

The payment history uses a controlled one-hour interval; the login requests have their own actual timestamps. Coordinates are explicit inputs, not IP geolocation or banking routes.

## Audit boundaries

Rust appends JSON records to a named-volume file and links them with SHA-256 hashes. It reports write failures and verifies the on-disk chain. Cases record receipts for processing events, completion and payment policy.

The policy entry is written before allowed simulation executes. The final `payment` object and its simulation receipt are stored in PostgreSQL afterward. Verifying the chain does **not** prove those database fields match a receipt, prove an allegation, independently sign the evidence or establish external anchoring.

Reports distinguish audit status recorded during processing from a fresh chain verification. A failed or unavailable audit is not shown as verified. An allow decision is withheld if its required policy receipt cannot be verified.

## Data ownership

| Data | Store | Survives service recreation? |
|---|---|---|
| Accounts, refresh tokens, cases | PostgreSQL named volume | Yes, while the volume is retained |
| Audit chain | Rust named volume | Yes, while the volume is retained |
| Security notifications | Redis Pub/Sub | No replay for missed messages |
| Subscriber's recent security context | Python process memory | No |
| Showcase history and audit | Next.js instance memory | No persistence guarantee |

WebSocket messages show processing progress before database persistence finishes. Seeing a live event alone is not evidence that a case saved successfully.

## Failure boundaries

- Health probes cover service readiness; `doctor` also checks dependencies, storage, dashboard access and current audit integrity.
- Local restart policies recover exited containers. They do not restart a still-running unhealthy process automatically.
- WebSocket clients and Redis subscribers reconnect, but reconnecting does not recover missed Pub/Sub events.
- The ten-case batch is request-bound and saves successful cases individually. A lost response can leave completed cases; there is no durable job state or idempotent batch replay.
- No cross-service transaction covers Rust audit writes and PostgreSQL case persistence. A partial failure can leave audit evidence without a saved case.
- The payment simulator is not a ledger. Holds have no approval/release workflow, and all outcomes remain synthetic.
- Local Python/Rust APIs are directly reachable on loopback without Go authentication. Do not expose this profile as a public service.

## Code map

- `agents-python/app/orchestrator.py`: tiered processing and event capture.
- `agents-python/app/demo.py`: manual scenarios and balanced inputs.
- `agents-python/app/payments.py`: simulated payment policy.
- `agents-python/app/audit.py` and `engine-rust/src/audit.rs`: audit client and storage.
- `agents-python/app/db.py`: saved cases.
- `agents-python/app/reports.py`: escaped printable reports.
- `dashboard-web/src/lib/useCaseReview.ts`: local API, live updates and case selection.
- `dashboard-web/src/components/CaseDetail.tsx`: evidence and decisions.
