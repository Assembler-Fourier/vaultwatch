#!/usr/bin/env python3
"""Exercise synthetic cases through the running local stack; no paid model calls."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from local_status import wait_until_ready

BASE = 'http://127.0.0.1:8000'


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(BASE + path, data=data, headers={'Content-Type': 'application/json'}), timeout=30) as response:
        raw = response.read().decode()
        return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='Save synthetic reports and verification results here')
    args = parser.parse_args()
    readiness = wait_until_ready(60)
    if not readiness['ready']:
        raise RuntimeError('Local services did not become ready: ' + '; '.join(readiness['problems']))
    status = readiness['checks']['backend']
    # Keep this guard effective even when Python assertions are disabled.
    if status.get('model_mode') != 'replay' or status.get('storage') != 'postgres':
        raise RuntimeError('Smoke checks require replay mode and PostgreSQL storage')
    results = []
    for scenario in ('normal', 'review', 'unusual', 'sanctions', 'takeover'):
        result = request('/v1/demo/run', {'scenario': scenario, 'origin': 'Dublin', 'destination': 'Sydney'})
        tx = result['transaction']
        receipts = result['audit']['entries']
        assert result['audit']['status'] == 'verified', result['audit']
        assert receipts[0]['event_type'] == 'case.opened' and receipts[-2]['event_type'] == 'case.completed'
        assert receipts[-1]['event_type'] == 'payment.policy'
        assert all(row['subject_id'] == tx['id'] for row in receipts)
        assert len(receipts) == len(result['events']) + 2
        assert receipts[0]['payload']['transaction'] == tx
        saved = request('/v1/cases/' + tx['id'])
        assert saved['result'] == result
        assert request('/v1/cases/' + tx['id'] + '/report.json') == saved
        report = request('/v1/cases/' + tx['id'] + '/report')
        assert tx['id'] in report and 'Current chain verification' in report
        if scenario == 'normal':
            assert result['payment']['action'] == 'allow'
            assert result['payment']['execution_status'] == 'simulated_complete'
            assert result['rules']['risk_score'] == 0
            assert result['stage_reached'] == 'closed' and result['triage'] is None and result['alert'] is None
            assert result['review']['distance_km'] == 0
        elif scenario == 'review':
            assert result['payment']['action'] == 'hold'
            assert result['alert']['severity'] == 'medium'
            assert result['rules']['risk_score'] == 35
            assert result['review']['distance_km'] == 0
            assert result['review']['new_device'] and not result['review']['new_beneficiary']
            assert result['payment']['simulation_receipt'] is None
            assert result['payment']['execution_status'] == 'not_executed'
        else:
            assert result['payment']['action'] == ('hold' if scenario == 'unusual' else 'block')
            assert result['payment']['simulation_receipt'] is None
            assert result['payment']['execution_status'] == 'not_executed'
            assert result['review']['distance_km'] > 17000
            assert result['review']['new_device'] and result['review']['new_beneficiary']
            assert any(rule['rule'] == 'impossible_travel' for rule in result['rules']['triggered_rules'])
            research = {e['detail']['tool']: e['detail']['result'] for e in result['events'] if e.get('detail', {}).get('tool')}
            assert result['case']['sanctions_hit'] == research['check_sanctions_list']['hit'] == (scenario == 'sanctions')
            assert result['case']['linked_accounts'] == research['get_entity_graph']['linked_accounts']
            assert result['compliance']
        if scenario == 'takeover':
            assert len(result['review']['login_evidence']) == 2
            assert result['alert']['fused_with_security_event'] and result['alert']['severity'] == 'critical'
            security = result['alert']['detail']['security_event']
            assert security['account_id'] == tx['account_id'] and security['type'] == 'impossible_travel'
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / f'VaultWatch-{scenario}-report.html').write_text(report)
            (args.output_dir / f'VaultWatch-{scenario}-report.json').write_text(json.dumps(saved, indent=2))
        summary = {'scenario': scenario, 'transaction_id': tx['id'], 'rules_score': result['rules']['risk_score'],
                   'stage': result['stage_reached'], 'severity': (result['alert'] or {}).get('severity', 'closed'),
                   'audit_receipts': len(receipts), 'audit_status': result['audit']['status'],
                   'payment_action': result['payment']['action']}
        results.append(summary)
        print(json.dumps(summary), flush=True)
    for path, body, expected in [('/v1/demo/run', {'scenario': 'normal', 'amount': -1}, 422),
                                  ('/v1/demo/run', {'scenario': 'takeover', 'origin': 'Dublin', 'destination': 'Dublin'}, 422),
                                  ('/v1/cases/does-not-exist', None, 404)]:
        try:
            request(path, body)
            raise AssertionError('Invalid request unexpectedly succeeded')
        except HTTPError as error:
            assert error.code == expected
    chain = request('/v1/audit')
    assert chain['verify']['valid']
    proof = {'services': status, 'scenarios': results, 'audit': chain, 'invalid_inputs_rejected': True}
    if args.output_dir:
        (args.output_dir / 'VaultWatch-local-checks.json').write_text(json.dumps(proof, indent=2))
    print('PASS: five scenarios, saved cases, reports, evidence consistency, audit verification and input validation')


if __name__ == '__main__':
    main()
