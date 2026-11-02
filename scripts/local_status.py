#!/usr/bin/env python3
"""Read-only health checks for VaultWatch's local synthetic stack."""

import argparse
import json
import math
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

EXPECTED_SERVICES = ('python', 'rust', 'go', 'postgres', 'redis', 'security_feed')


def inspect_stack(deadline=None):
    checks = {}
    problems = []

    def fetch(url, decode=True):
        remaining = 5 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Readiness deadline reached')
        with urlopen(url, timeout=min(5, remaining)) as response:
            return json.load(response) if decode else response.status

    try:
        status = fetch('http://127.0.0.1:8000/v1/status')
        checks['backend'] = status
        for service in EXPECTED_SERVICES:
            value = status.get('services', {}).get(service, 'missing')
            if value != 'online':
                problems.append(f'{service}: {value}')
        if status.get('storage') != 'postgres':
            problems.append('Case storage is not PostgreSQL')
        if status.get('model_mode') != 'replay':
            problems.append('Expected the local replay profile; model mode is not replay')
    except (URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError) as error:
        problems.append(f'Backend status unavailable: {error}')

    try:
        checks['dashboard_http'] = fetch('http://127.0.0.1:3000/', decode=False)
    except (URLError, TimeoutError, OSError) as error:
        problems.append(f'Dashboard unavailable: {error}')

    try:
        audit = fetch('http://127.0.0.1:8000/v1/audit')
        checks['audit'] = audit
        if audit.get('verify', {}).get('valid') is not True:
            problems.append('Audit chain did not verify')
    except (URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError) as error:
        problems.append(f'Audit verification unavailable: {error}')

    return {'ready': not problems, 'checks': checks, 'problems': problems}


def wait_until_ready(seconds=0):
    deadline = time.monotonic() + seconds if seconds > 0 else None
    while True:
        result = inspect_stack(deadline)
        if result['ready'] or deadline is None or time.monotonic() >= deadline:
            return result
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait', type=float, default=0, help='Maximum seconds to wait for readiness')
    parser.add_argument('--json', action='store_true', help='Print the complete health report')
    args = parser.parse_args()
    if not math.isfinite(args.wait) or args.wait < 0:
        parser.error('--wait must be a finite nonnegative number')
    result = wait_until_ready(args.wait)
    if args.json:
        print(json.dumps(result, indent=2))
    elif result['ready']:
        print('Ready: dashboard, Python, Rust, Go, PostgreSQL, Redis, security feed and audit chain.')
        print('Mode: local replay with synthetic data. No live model calls.')
        print('Dashboard: http://localhost:3000')
        print('API explorer: http://localhost:8000/docs')
    else:
        print('VaultWatch is not ready:', file=sys.stderr)
        for problem in result['problems']:
            print(f'  - {problem}', file=sys.stderr)
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
