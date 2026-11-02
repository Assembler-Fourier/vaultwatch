"""Printable evidence report with escaped content and explicit verification scope."""

import html
import json


def render_report(record: dict, verification: dict) -> str:
    result = record["result"]
    tx, review = result.get("transaction", {}), result.get("review", {})
    audit = result.get("audit", {})
    payment = result.get("payment") or {"action": "not_evaluated", "reasons": ["This record predates payment controls."]}

    def esc(value):
        return html.escape(str(value))

    def block(title, value):
        return f"<section><h2>{esc(title)}</h2><pre>{esc(json.dumps(value, indent=2, ensure_ascii=False))}</pre></section>"

    def familiarity(value, subject):
        if value is True:
            return f"New {subject}"
        if value is False:
            return f"Known {subject}"
        return f"{subject.capitalize()} familiarity not recorded"

    rows = "".join(
        f'<tr><td>{esc(e["timestamp"])}</td><td>{esc(e.get("stage", "alert"))}</td><td>{esc(e.get("label", e.get("title", "")))}</td></tr>'
        for e in result.get("events", [])
    )
    receipts = "".join(
        f'<tr><td>{esc(e["seq"])}</td><td>{esc(e["event_type"])}</td><td class="hash">{esc(e["hash"])}</td></tr>'
        for e in audit.get("entries", [])
    )
    decision = result.get("alert") or {
        "title": "Closed without alert",
        "severity": "low",
    }
    journey = f"{review.get('origin', {}).get('name', 'Not recorded')} → {review.get('current_location', {}).get('name', 'Not recorded')}"
    findings = "".join(
        f"<li><strong>{esc(rule['rule'].replace('_', ' '))}</strong>: {esc(rule['detail'])}</li>"
        for rule in (result.get("rules") or {}).get("triggered_rules", [])
    )
    case = result.get("case")
    screen = (
        ("Match found" if case.get("sanctions_hit") else "No match")
        if case
        else "Not screened: case closed before investigation"
    )
    summary = (
        case["summary"]
        if case
        else "Initial checks did not require an investigation. The case closed without an alert."
    )
    current = verification.get("verify")
    integrity = (
        ("Valid" if current["valid"] else "BROKEN") if current else "Unavailable"
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>VaultWatch case {esc(record['transaction_id'])}</title>
<style>body{{font:15px/1.6 system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#17212b}}h1{{margin-bottom:0}}h2{{font-size:19px;margin-top:32px}}.note{{background:#edf3f7;padding:16px;border-left:4px solid #376d82}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #ddd;padding:9px;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px;font-size:12px}}.hash{{word-break:break-all;font:11px monospace}}section{{break-inside:avoid}}@media print{{body{{margin:0;max-width:none}}button{{display:none}}}}</style>
<h1>VaultWatch audit report</h1><p>{esc(record['transaction_id'])} · {esc(tx.get('account_id',''))}</p>
<p class="note">Synthetic demonstration · {esc(result.get('model_mode','unknown'))} model mode · No money moved. No regulatory filing. Hash verification checks record integrity, not the truth of a fraud allegation.</p>
<h2>{esc(tx.get('amount',''))} {esc(tx.get('currency',''))} · {esc(decision['title'])}</h2><p>Final severity: <strong>{esc(decision['severity'])}</strong>. Processing audit at completion: <strong>{esc(audit.get('status','not recorded'))}</strong>.</p>
<h2>Case summary</h2><p>{esc(summary)}</p>
<h2>Payment decision: {esc(payment['action'])}</h2><p>{esc(' '.join(payment['reasons']))}</p>
<p>Execution: {esc(payment.get('execution_status', 'not recorded'))}. Local simulation only; no money moved.</p>
{block('Payment policy and simulation receipt', payment)}
<table><tr><th>Recipient</th><td>{esc(tx.get('beneficiary_name', tx.get('beneficiary_id', 'Not recorded')))}</td></tr>
<tr><th>Account location journey</th><td>{esc(journey)} · {esc(review.get('distance_km', 'Not recorded'))} km in {esc(review.get('elapsed_minutes', 'Not recorded'))} minutes</td></tr>
<tr><th>Device / recipient</th><td>{familiarity(review.get('new_device'), 'device')} / {familiarity(review.get('new_beneficiary'), 'recipient')}</td></tr>
<tr><th>Synthetic watchlist</th><td>{esc(screen)}</td></tr>
<tr><th>Security correlation</th><td>{'Matched Go login warning to this account' if decision.get('fused_with_security_event') else 'No matched login warning'}</td></tr>
<tr><th>Current audit verification</th><td>{esc(integrity)} · checked {esc(verification.get('checked_at', 'Not available'))}</td></tr></table>
<p>{esc(review.get('location_note', 'Location evidence was not recorded.'))}</p>
<h2>Reasons for review</h2><ul>{findings or '<li>No deterministic rules triggered.</li>'}</ul>
<p>{esc((result.get('compliance') or {}).get('narrative', 'No compliance draft was requested. See the payment decision for the current outcome.'))}</p>
<h2>Processing timeline</h2><table><tr><th>Time (UTC)</th><th>Stage</th><th>What happened</th></tr>{rows}</table>
{block('Transaction and location data', {'transaction': tx, 'review': review})}
{block('Rules and statistical check', {'rules': result.get('rules'), 'prefilter': result.get('prefilter')})}
{block('Investigation and compliance draft', {'triage': result.get('triage'), 'case': result.get('case'), 'compliance': result.get('compliance'), 'security_event': decision.get('detail',{}).get('security_event')})}
{block('Research tool evidence', [e['detail'] for e in result.get('events',[]) if e.get('detail',{}).get('tool')])}
<h2>Audit receipts</h2><p>Each receipt links to the previous record through a SHA-256 hash. The local file-backed chain is tamper-evident; it is not independently signed or externally anchored.</p><table><tr><th>Sequence</th><th>Event</th><th>Hash</th></tr>{receipts}</table>
{block('Current chain verification', verification)}
{block('Audit errors', audit.get('errors', []))}
<p>Use your browser’s Print command to save this report as a PDF.</p></html>"""
