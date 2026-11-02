# Model modes

The latest local workspace includes a model-provider interface, not a downloaded local language model. The recommended setup uses scripted replay. The IsolationForest statistical prefilter runs locally in Python in either mode.

## Replay

`./scripts/local-demo.sh start` forces `MODE=replay` and clears `ANTHROPIC_API_KEY` for the Python service and dashboard. No model API key is required.

The provider returns deterministic triage/investigation/compliance responses. Investigation still executes the research tools and consumes their returned evidence. The surrounding HTTP calls, Go login flow, Redis events, PostgreSQL storage and Rust audit operations are real local service interactions over synthetic data.

Replay is useful for repeatable demonstrations and tests. Its conclusions are not evidence of live model quality, and its risk scores are not calibrated fraud probabilities.

## Optional live inference

The base configuration supports Anthropic through `agents-python/app/llm/provider.py`:

| Setting | Behavior |
|---|---|
| `MODE=replay` | Use replay even if a key exists |
| `MODE=auto` | Select Anthropic when a key is set; otherwise replay |
| `MODE=live` | Select Anthropic; requires a working key |
| `HAIKU_MODEL` | Model identifier for triage |
| `SONNET_MODEL` | Model identifier for investigation and compliance |

The configured defaults are recorded in `.env.example` and `agents-python/app/config.py`. Model identifiers and account availability should be checked before enabling live inference; this release does not claim they are the newest available models. Live inference was not exercised for the local verification.

The local override deliberately keeps replay active. Switching the base profile to live inference is a separate development choice that can incur API charges. Never commit a real key. Existing local demo endpoints, credentials and network settings are not a production deployment plan.

## Dashboard modes

`NEXT_PUBLIC_MODE=full` is selected at build time by the dashboard Dockerfile. It connects the case-review workspace to the Python API and WebSocket endpoints.

The default `showcase` build uses Next.js route handlers and the smaller TypeScript pipeline. It has a heuristic statistical check, a model/replay provider, and instance-memory case/audit storage. It does not have the full local payment policy, PostgreSQL history or Go/Redis security-event fusion.

Do not use showcase output to claim the complete local backend has been deployed. Likewise, repository publication and a frontend hosting deployment are separate states.
