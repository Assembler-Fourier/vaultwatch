"use client";
import { useState } from "react";
import { useCaseReview, type ReviewCase, type Scenario } from "@/lib/useCaseReview";
import { scenarioNames, scenarioDescriptions, paymentLabels, paymentTone, severityOf, money } from "@/lib/reviewDisplay";
import { CaseDetail } from "./CaseDetail";

const cities = ["Dublin", "London", "New York", "Sydney"];
const serviceNames = ["python", "rust", "go", "postgres", "redis", "security_feed"];
type Outcome = "all" | "allow" | "hold" | "block";

export function FullDashboard() {
  const data = useCaseReview();
  const [manual, setManual] = useState(false);
  const [scenario, setScenario] = useState<Scenario>("normal");
  const [amount, setAmount] = useState("");
  const [origin, setOrigin] = useState("Dublin");
  const [destination, setDestination] = useState("Sydney");
  const [filter, setFilter] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("all");
  const [showHistory, setShowHistory] = useState(false);
  const sameCity = scenario === "normal" || scenario === "review";
  const batchCases: ReviewCase[] = (data.batch?.results ?? []).flatMap(result => result.transaction ? [{
    transaction_id: result.transaction.id, account_id: result.transaction.account_id, result,
  }] : []);
  const inBatch = !!data.batch && !showHistory;
  const rows = inBatch ? batchCases : data.cases;
  const counts = { all: rows.length, allow: 0, hold: 0, block: 0 };
  for (const row of rows) if (row.result.payment) counts[row.result.payment.action]++;
  const visibleCases = rows.filter(row =>
    (outcome === "all" || row.result.payment?.action === outcome) &&
    `${row.transaction_id} ${row.account_id} ${row.result.transaction?.beneficiary_name ?? ""} ${scenarioNames[row.result.review?.scenario ?? "normal"]} ${severityOf(row.result)}`.toLowerCase().includes(filter.toLowerCase())
  );
  const online = serviceNames.filter(name => data.status?.services[name] === "online").length;
  const clearFilters = () => { setFilter(""); setOutcome("all"); };
  return (
    <div className="review-shell">
      <header className="review-header">
        <div className="brand"><div className="brand-mark" aria-hidden="true">V</div><div>
          <h1>VaultWatch</h1><p className="muted">Payment review workspace</p>
        </div></div>
        <div className="status-stack">
          <span className={`connection ${data.connected ? "good" : "warn"}`}><i />{data.connected ? "Live feed" : "Reconnecting"}</span>
          <span className="pill">{data.status ? data.status.model_mode === "replay" ? "Replay mode" : "Live model" : "Model unavailable"}</span>
          <details className="service-menu"><summary>{online}/6 services <span aria-hidden="true">⌄</span></summary>
            <div className="service-popover" aria-label="Service health">
              {serviceNames.map(name => <div key={name} className="service-row"><span>{name === "security_feed" ? "Security feed" : name}</span><span className={`pill ${data.status?.services[name] === "online" ? "good" : "warn"}`}>{data.status?.services[name] ?? "unavailable"}</span></div>)}
              <button className="text-link" onClick={() => void data.refresh()}>Refresh status</button>
            </div>
          </details>
        </div>
      </header>
      <div className="workspace-heading"><div><p className="eyebrow">LOCAL DEMONSTRATION</p><h2>Follow the decision.</h2><p className="muted">From payment details to evidence, action and audit.</p></div><span className="demo-tag">Synthetic data · No money moves</span></div>
      <section className="panel demo-controls" aria-label="Transaction controls">
        <div className="runner-main"><div className="runner-copy"><h2>A balanced set of 10</h2><p>Normal payments, review signals and serious risk in one run.</p>
          <div className="mix-legend"><span><i className="dot good" />5 normal</span><span><i className="dot warn" />2 review</span><span><i className="dot high" />1 unusual</span><span><i className="dot danger" />1 watchlist</span><span><i className="dot danger" />1 takeover</span></div>
        </div><div className="runner-actions"><button className="primary" disabled={data.busy} onClick={() => { clearFilters(); setShowHistory(false); void data.runBatch(); }}>{data.batchProgress !== null ? `Running ${data.batchProgress}/10…` : "Run balanced demo"}<span aria-hidden="true"> →</span></button>
          <button className="secondary" aria-expanded={manual} aria-controls="manual-form" onClick={() => setManual(!manual)}>{manual ? "Close manual entry" : "Manual transaction"}</button></div></div>
        {manual && <div id="manual-form" className="manual-entry"><div className="manual-heading"><h3>Build one transaction</h3><p className="muted">{scenarioDescriptions[scenario]}</p></div>
          <form onSubmit={event => { event.preventDefault(); clearFilters(); setShowHistory(true); void data.run(scenario, amount, origin, sameCity ? origin : destination); }}>
            <label>Scenario<select value={scenario} onChange={e => { setScenario(e.target.value as Scenario); setAmount(""); }}>{Object.entries(scenarioNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Amount (EUR)<input type="number" min="0.01" max="1000000" step="0.01" value={amount} placeholder={sameCity ? "Usual amount" : "4,200.00"} onChange={e => setAmount(e.target.value)} /></label>
            <label>Previous location<select value={origin} onChange={e => setOrigin(e.target.value)}>{cities.map(city => <option key={city}>{city}</option>)}</select></label>
            <label>Payment location<select disabled={sameCity} value={sameCity ? origin : destination} onChange={e => setDestination(e.target.value)}>{cities.map(city => <option key={city}>{city}</option>)}</select></label>
            <button className="primary" disabled={data.busy}>{data.busy && data.batchProgress === null ? "Processing…" : "Run transaction"}</button>
          </form>
        </div>}
        {data.busy && <div className="run-progress" role="status"><progress max={10} value={data.batchProgress ?? undefined} /><span>{data.batchProgress !== null ? `${data.batchProgress} of 10 processed` : "Checking evidence and saving the case…"}</span></div>}
        {data.error && <div className="error-box" role="alert">{data.error}</div>}
        {data.batch && <div className="batch-notice" role="status"><span>{data.batch.results.length}/10 cases saved · {data.batch.failures.length ? `${data.batch.failures.length} unconfirmed` : "All items completed"}</span><span className="muted">Fixed scenarios · Shuffled order · Replay only</span></div>}
        {data.batch?.failures.map(f => <p key={f.index} className="error-box">Item {f.index}: {f.message}</p>)}
      </section>
      <div className="results-heading"><h2>{inBatch ? "Demo results" : "Recent cases"}</h2><div className="history-switch">{data.batch && <button className="text-link" onClick={() => { setShowHistory(!showHistory); clearFilters(); }}>{inBatch ? "View recent history" : "Back to demo results"}</button>}<span className="muted">{inBatch ? "This run" : "Latest saved cases"}</span></div></div>
      <div className="outcome-stats" aria-label="Filter by payment decision">{([
        ["all", "All cases", "Saved results"], ["allow", "Allowed", "Simulation completed"],
        ["hold", "On hold", "Execution paused"], ["block", "Blocked", "Execution prevented"],
      ] as const).map(([key, label, caption]) => <button key={key} className={`stat-card ${key} ${outcome === key ? "active" : ""}`} aria-pressed={outcome === key} onClick={() => setOutcome(key)}><span>{label}</span><strong>{counts[key].toString().padStart(2, "0")}</strong><small>{caption}</small></button>)}</div>
      <div className="case-layout">
        <aside className="panel case-list"><label className="search-label"><span>Find a case</span><input type="search" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Search recipient, risk or ID" /></label>
          <div className="list-count"><span>{visibleCases.length} {visibleCases.length === 1 ? "case" : "cases"}</span>{(filter || outcome !== "all") && <button className="text-link" onClick={clearFilters}>Clear filters</button>}</div>
          <div className="case-items">{visibleCases.map(row => <button key={row.transaction_id} onClick={() => data.setSelected(row)} className={`case-choice ${data.selected?.transaction_id === row.transaction_id ? "selected" : ""}`} aria-pressed={data.selected?.transaction_id === row.transaction_id}>
            <span className="case-row-top"><strong>{money(row.result.transaction?.amount)}</strong><span className={`risk-dot severity-${severityOf(row.result)}`}>{severityOf(row.result)}</span></span>
            <span className="case-row-name">{row.result.review?.scenario ? scenarioNames[row.result.review.scenario] : "Earlier record"}</span>
            <span className="case-row-bottom"><small>{row.transaction_id.slice(-8)}</small><span className={`pill ${row.result.payment ? paymentTone[row.result.payment.action] : "neutral"}`}>{row.result.payment ? paymentLabels[row.result.payment.action] : "Not evaluated"}</span></span>
          </button>)}</div>
          {!visibleCases.length && <p className="list-empty">{rows.length ? "No cases match these filters." : "Run the demo to see cases here."}</p>}
        </aside>
        <main>{data.selected ? <CaseDetail key={data.selected.transaction_id} record={data.selected} chain={data.chain} /> : <section className="panel empty"><div className="empty-symbol" aria-hidden="true">◇</div><h2>Your next case starts here</h2><p>Run the balanced demo or build a transaction.<br />Select a case to follow its decision.</p></section>}</main>
      </div>
      <footer className="muted">Local simulation · High risk is held for review · Critical risk or a watchlist match is blocked · Times in Dublin</footer>
    </div>
  );
}
