# Local development

## Start and inspect

Install Docker with Compose 2.24.4+, Git and Python 3. Keep Docker running, then use these commands from the repository root:

```sh
./scripts/local-demo.sh start
./scripts/local-demo.sh doctor
./scripts/local-demo.sh doctor --json
./scripts/local-demo.sh ps
./scripts/local-demo.sh logs --tail=50
./scripts/local-demo.sh stop
```

`start` rebuilds changed source and waits up to 180 seconds for Compose readiness after the build, then checks dashboard access, dependencies and audit integrity. No arguments also runs `start`. If startup fails, the command prints service state and exits unsuccessfully.

`doctor` is read-only. `doctor --wait 30` retries readiness for up to 30 seconds. Other arguments are passed to Compose, so ordinary commands such as `restart agents-python` remain available.

| Endpoint | Purpose |
|---|---|
| http://localhost:3000 | Full review dashboard |
| http://localhost:8000/docs | Python API explorer |
| http://localhost:8000/v1/status | Model mode, storage and dependencies |
| http://localhost:8000/v1/audit | Current audit verification |
| http://localhost:8081/healthz | Rust service health |
| http://localhost:8090/healthz | Go service health |

All published ports bind to `127.0.0.1`. PostgreSQL uses port 5432 and Redis uses 6379. Resolve conflicts with another local service before starting; do not stop unrelated applications blindly.

## Verify behavior

```sh
./scripts/local-demo.sh verify
# Optionally save synthetic evidence outside the repository:
./scripts/local-demo.sh verify --output-dir /tmp/vaultwatch-verification
```

This creates five cases and a synthetic login account. It verifies allow/hold/block behavior, returned tool evidence, PostgreSQL readback, JSON/HTML exports, audit receipts and rejected invalid inputs. It refuses an unexpected model mode or non-PostgreSQL storage.

For a visual batch, click **Run balanced demo**. Expect ten results: five allowed, three held and two blocked with the unmodified replay scenarios. Expand **Manual transaction** to vary one input at a time.

## Preserve data

The local override fixes the Compose project name to `vaultwatch-study`. PostgreSQL uses `vaultwatch-study_pgdata`; Rust uses `vaultwatch-study_audit-data`. Starting, stopping, rebuilding and recreating services retain these named volumes.

Use `stop` for a normal shutdown. `down -v` deletes data volumes and is not part of the normal workflow. Old cases retain their stored decisions and policy versions; opening them does not rerun the current policy.

## Recovery checks

For a controlled local check, restart one component and wait for recovery:

```sh
./scripts/local-demo.sh restart redis
./scripts/local-demo.sh doctor --wait 60
./scripts/local-demo.sh restart agents-python
./scripts/local-demo.sh doctor --wait 60
```

Reopen a saved case to confirm persistence. Missed Redis Pub/Sub notifications are not replayed. Health checks report an unhealthy running process; restart policies recover an exited process. Per-container logs are capped at three 10 MB files.

## Run service checks

With the relevant language toolchains installed:

```sh
(cd engine-rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test --release)
(cd gateway-go && go build ./... && go vet ./... && go test ./... -race)
(cd agents-python && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/ruff check app tests seed.py && MODE=replay .venv/bin/pytest -q)
(cd dashboard-web && npm ci && npm run lint && MODE=replay npm run build)
```

CI uses separate jobs for these service checks. The local end-to-end smoke command needs the running six-service stack and is separate from those jobs.

The Docker profile forces replay, clears the Anthropic key and disables automatic traffic. Development credentials and direct local API access are for this loopback demonstration. [Model configuration](model-modes.md) explains the separate base profile.

Docker references: [health-based startup](https://docs.docker.com/compose/how-tos/startup-order/), [readiness wait](https://docs.docker.com/reference/cli/docker/compose/up/), [Compose override requirements](https://docs.docker.com/reference/compose-file/merge/).
