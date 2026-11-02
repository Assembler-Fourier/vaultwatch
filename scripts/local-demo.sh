#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
compose() {
  docker compose -p vaultwatch-study -f docker-compose.yml -f compose.local.yml "$@"
}
if [ "$#" -eq 0 ]; then set -- start; fi
case "$1" in
  start)
    shift
    if ! compose up --build --wait --wait-timeout 180 "$@"; then
      printf '%s\n' 'VaultWatch did not become ready. Current service state:' >&2
      compose ps -a >&2
      printf '%s\n' 'Inspect logs with: ./scripts/local-demo.sh logs --tail=50' >&2
      exit 1
    fi
    exec python3 scripts/local_status.py --wait 15
    ;;
  doctor)
    shift
    exec python3 scripts/local_status.py "$@"
    ;;
  verify)
    shift
    exec python3 scripts/smoke-local.py "$@"
    ;;
  *)
    exec docker compose -p vaultwatch-study -f docker-compose.yml -f compose.local.yml "$@"
    ;;
esac
