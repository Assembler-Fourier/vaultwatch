"use client";
import { useState } from "react";
import { API, useCaseReview, type ReviewCase } from "@/lib/useCaseReview";
import { scenarioNames, paymentLabels, paymentTone, severityOf, money, time, human } from "@/lib/reviewDisplay";

export function CaseDetail({
  record,
  chain,
}: {
  record: ReviewCase;
  chain: ReturnType<typeof useCaseReview>["chain"];
}) {
  const [tab, setTab] = useState("overview");
  const r = record.result,
    tx = r.transaction,
    review = r.review;
  const toolEvents =
    r.events?.filter(
      (event) => event.type === "agent_event" && event.detail.tool,
    ) ?? [];
  if (!tx)
    return (
      <section className="panel empty">
        <h2>Earlier demo record</h2>
        <p>
          This case predates the complete transaction capture. Run a new
          scenario to see locations, research results and audit receipts.
        </p>
        <p className="mono">{record.transaction_id}</p>
      </section>
    );
  const auditComplete = r.audit?.status === "verified";
  const auditLabel = !chain
    ? "Verification unavailable"
    : !chain.verify.valid
      ? "Audit chain broken"
      : auditComplete
        ? "Recorded and verified"
        : (r.audit?.status ?? "Not recorded");
  const tabs = ["overview", "evidence", "timeline", "audit"];
  const reportUrl = `${API}/v1/cases/${encodeURIComponent(tx.id)}`;
  return (
    <article className="case-detail">
      <section className="panel case-summary">
        <div className="section-head">
          <div>
            <p className="eyebrow">
              {review?.scenario
                ? scenarioNames[review.scenario]
                : "TRANSACTION REVIEW"}
            </p>
            <h2>
              {money(tx.amount, tx.currency)}{" "}
              <span className="muted">
                to {tx.beneficiary_name ?? tx.beneficiary_id}
              </span>
            </h2>
          </div>
          <span className={`pill severity-${severityOf(r)}`}>Risk: {severityOf(r)}</span>
        </div>
        <p className="mono muted">{tx.id}</p>
        <div className="case-actions">
          <a className="secondary" href={`${reportUrl}/report`} target="_blank" rel="noreferrer">Open audit report ↗</a>
          <a className="text-link" href={`${reportUrl}/report.json`}>Download JSON</a>
        </div>
        <details className="transaction-details"><summary>Transaction details</summary>
        <dl className="facts">
          <div>
            <dt>Account</dt>
            <dd className="mono">{tx.account_id}</dd>
          </div>
          <div>
            <dt>Payment time</dt>
            <dd>{time(tx.timestamp)}</dd>
          </div>
          <div>
            <dt>Device</dt>
            <dd>
              {review?.new_device === true ? "New device" : review?.new_device === false ? "Known device" : "Familiarity not recorded"}
              <small className="mono">{tx.device_id}</small>
            </dd>
          </div>
          <div>
            <dt>Recipient</dt>
            <dd>
              {review?.new_beneficiary === true ? "New recipient" : review?.new_beneficiary === false ? "Known recipient" : "Familiarity not recorded"}
              <small className="mono">{tx.beneficiary_id}</small>
            </dd>
          </div>
        </dl></details>
      </section>
      <section className={`panel payment-panel ${r.payment?.action ?? "unknown"}`}>
        <div className="section-head">
          <h2>Payment decision</h2>
          <span className={`pill ${r.payment ? paymentTone[r.payment.action] : "warn"}`}>
            {r.payment ? paymentLabels[r.payment.action] : "Not evaluated"}
          </span>
        </div>
        {r.payment ? <>
          <p>{r.payment.reasons.join(" ")}</p>
          <p className="muted">{r.payment.execution_status === "simulated_complete"
            ? "The backend allowed simulated execution. No real payment was sent."
            : "Execution was withheld. The payment simulator was not called."}</p>
          {r.payment.simulation_receipt && <p className="mono">Receipt: {r.payment.simulation_receipt.id}</p>}
          <details className="policy-details"><summary>Decision policy · {r.payment.policy_version}</summary>
            <p className="fine-print">{r.payment.policy_version === "local-demo-v1"
              ? "Historical policy: high and critical alerts or rules ≥70 blocked execution. This saved decision has not been rewritten."
              : "Critical risk or a synthetic watchlist match blocks execution. High or medium risk is held for review. Clear checks may proceed only after audit verification."} All outcomes are simulated. Held payments cannot be released from this demo.</p>
          </details>
        </> : <p className="muted">This earlier case predates payment controls. Run a new case to apply the policy; old alerts were not payment blocks.</p>}
      </section>
      <div className="case-tabs" role="tablist" aria-label="Case details">
        {tabs.map(name => <button key={name} id={`tab-${name}`} type="button" role="tab"
          aria-selected={tab === name} aria-controls="case-tab-panel" tabIndex={tab === name ? 0 : -1}
          onClick={() => setTab(name)} onKeyDown={event => {
            const index = tabs.indexOf(name);
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
              : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
            if (next >= 0) { event.preventDefault(); setTab(tabs[next]); document.getElementById(`tab-${tabs[next]}`)?.focus(); }
          }}>{name}</button>)}
      </div>
      <div className="case-tab-content" role="tabpanel" id="case-tab-panel" aria-labelledby={`tab-${tab}`} tabIndex={0}>
      {tab === "overview" && <>
      {review?.origin && (
        <section className="panel">
          <div className="section-head">
            <h2>Location journey</h2>
            <span
              className={`pill ${review.implied_speed_kmh > 900 ? "danger" : "good"}`}
            >
              {review.implied_speed_kmh > 900
                ? "Impossible travel"
                : "Location consistent"}
            </span>
          </div>
          <div className="journey">
            <div>
              <p className="eyebrow">PREVIOUS ACCOUNT LOCATION</p>
              <h3>{review.origin.name}</h3>
              <p>{time(review.origin.timestamp)}</p>
              <small>
                {review.origin.lat.toFixed(4)}, {review.origin.lon.toFixed(4)}
              </small>
            </div>
            <div className="route-line">
              <span>→</span>
              <strong>{review.distance_km.toLocaleString()} km</strong>
              <small>{review.elapsed_minutes} minutes</small>
            </div>
            <div>
              <p className="eyebrow">PAYMENT DEVICE LOCATION</p>
              <h3>{review.current_location.name}</h3>
              <p>{time(review.current_location.timestamp)}</p>
              <small>
                {review.current_location.lat.toFixed(4)},{" "}
                {review.current_location.lon.toFixed(4)}
              </small>
            </div>
          </div>
          <p className="muted">
            That implies {review.implied_speed_kmh.toLocaleString()} km/h. The
            travel rule triggers above 900 km/h.
          </p>
          <p className="fine-print">{review.location_note}</p>
        </section>
      )}
      <section className="panel">
        <h2>Risk checks</h2>
        <div className="metrics">
          <div>
            <small>Rules score</small>
            <strong>
              {r.rules?.risk_score ?? "—"}
              <span>/100</span>
            </strong>
          </div>
          <div>
            <small>Usual payment</small>
            <strong>{money(review?.baseline_average)}</strong>
          </div>
          <div>
            <small>Statistical check</small>
            <strong>{r.prefilter?.is_anomaly ? "Unusual" : "Normal"}</strong>
          </div>
          <div>
            <small>Investigator score</small>
            <strong>
              {r.case ? `${r.case.risk_score}/100` : "Not needed"}
            </strong>
          </div>
        </div>
        {r.rules?.triggered_rules.length ? (
          <ul className="rule-list">
            {r.rules.triggered_rules.map((rule) => (
              <li key={rule.rule}>
                <span className="rule-points">+{rule.weight}</span>
                <div>
                  <strong>{human(rule.rule)}</strong>
                  <p>{rule.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No deterministic rules triggered.</p>
        )}
        <p className="fine-print">
          Rules points are capped at 100. The investigator’s replay score is a
          separate indicator. Neither is a calibrated probability of fraud.
        </p>
      </section>
      </>}
      {tab === "evidence" && <>
      <section className="panel">
        <h2>Investigation evidence</h2>
        {r.case ? (
          <>
            <p>{r.case.summary}</p>
            <div className="evidence-grid">
              <div>
                <p className="eyebrow">SYNTHETIC WATCHLIST</p>
                <strong
                  className={r.case.sanctions_hit ? "danger-text" : "good-text"}
                >
                  {r.case.sanctions_hit ? "Match found" : "No match"}
                </strong>
                <p>{tx.beneficiary_name}</p>
              </div>
              <div>
                <p className="eyebrow">LINKED ACCOUNTS</p>
                <strong>{r.case.linked_accounts.length}</strong>
                <p className="mono">
                  {r.case.linked_accounts.join(", ") ||
                    "None returned by the tool"}
                </p>
              </div>
            </div>
            {toolEvents.map((event, index) => (
              <details key={index}>
                <summary>
                  {human(String(event.detail.tool))} · view returned evidence
                </summary>
                <pre>{JSON.stringify(event.detail.result, null, 2)}</pre>
              </details>
            ))}
          </>
        ) : (
          <p className="muted">
            This payment closed before the research stage. No investigation
            tools were needed.
          </p>
        )}
      </section>
      {review?.login_evidence?.length ? (
        <section className="panel">
          <h2>Account security</h2>
          <p>
            {r.alert?.fused_with_security_event
              ? "A Go login warning arrived through Redis and was matched to this payment’s account."
              : "Login evidence was recorded."}
          </p>
          <ol>
            {review.login_evidence.map((login, i) => (
              <li key={i}>
                {login.location} · {time(login.timestamp)} · {login.source}
              </li>
            ))}
          </ol>
          <details>
            <summary>View the matched security event</summary>
            <pre>{JSON.stringify(r.alert?.detail.security_event, null, 2)}</pre>
          </details>
        </section>
      ) : null}
      <section className="panel">
        <h2>Review outcome</h2>
        <p>
          {r.compliance?.narrative ??
            "No compliance draft was needed. See the payment decision for the current outcome."}
        </p>
        <p className="fine-print">
          {r.compliance?.disclaimer ??
            "Synthetic demonstration only. No real payment was approved or blocked."}
        </p>
      </section>
      </>}
      {tab === "timeline" && <section className="panel">
        <h2>What happened, in order</h2>
        <ol className="timeline">
          {r.events?.map((event, i) => (
            <li key={i}>
              <span className="timeline-number">{i + 1}</span>
              <div>
                <p className="eyebrow">
                  {event.type === "alert" ? "ALERT" : human(event.stage)}
                </p>
                <p>{event.type === "alert" ? event.title : event.label}</p>
                <small>{time(event.timestamp)}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>
      }
      {tab === "audit" && <section className="panel audit-panel">
        <div className="section-head">
          <h2>Audit report</h2>
          <span
            className={`pill ${auditComplete && chain?.verify.valid ? "good" : "warn"}`}
          >
            {auditLabel}
          </span>
        </div>
        <p>
          {r.audit?.entries.length ?? 0} receipts capture this transaction’s
          inputs, processing steps and outcome. The completed case is saved in
          Postgres.
        </p>
        <p className="muted">
          Current chain:{" "}
          {chain
            ? chain.verify.valid
              ? `valid across ${chain.verify.entries_checked} records`
              : `broken at record ${chain.verify.first_broken_seq}`
            : "verification unavailable"}
          . Checked {time(chain?.checked_at)}.
        </p>
        {!!r.audit?.errors.length && (
          <div role="alert" className="error-box">
            {r.audit.errors.join(". ")}
          </div>
        )}
        <details>
          <summary>Inspect this case’s audit receipts</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Sequence</th>
                  <th>Event</th>
                  <th>SHA-256 hash</th>
                </tr>
              </thead>
              <tbody>
                {r.audit?.entries.map((entry) => (
                  <tr key={entry.seq}>
                    <td>{entry.seq}</td>
                    <td>{entry.event_type}</td>
                    <td className="mono hash">{entry.hash}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <div className="report-actions">
          <a
            className="primary"
            href={`${API}/v1/cases/${encodeURIComponent(tx.id)}/report`}
            target="_blank"
            rel="noreferrer"
          >
            Open audit report
          </a>
          <a
            className="secondary"
            href={`${API}/v1/cases/${encodeURIComponent(tx.id)}/report.json`}
          >
            Download case JSON
          </a>
        </div>
        <p className="fine-print">
          The report can be printed to PDF. Hash chaining detects changes to
          recorded evidence; it does not prove a fraud allegation or provide an
          independent signature.
        </p>
      </section>}
      </div>
    </article>
  );
}
