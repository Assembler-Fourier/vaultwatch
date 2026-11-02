# VaultWatch dashboard

A Next.js and React interface with two build modes.

- **Full:** local payment review, five synthetic scenarios, a ten-case batch, saved cases, evidence/timeline/audit tabs, health status and report exports. It talks to the Python API and WebSocket endpoint.
- **Showcase:** a smaller self-contained TypeScript financial-risk demo using Next.js route handlers and in-memory history. It has no full-stack payment policy or Go/Redis security fusion.

For the complete app, use `./scripts/local-demo.sh start` from the repository root. The Dockerfile builds with `NEXT_PUBLIC_MODE=full` and the dashboard is available at http://localhost:3000.

For dashboard development against the running local backend:

```sh
npm ci
NEXT_PUBLIC_MODE=full npm run dev -- --port 3001
```

For the standalone replay showcase:

```sh
NEXT_PUBLIC_MODE=showcase MODE=replay npm run dev -- --port 3001
```

The mode is a build-time setting. Rebuild after changing it; a runtime environment change alone does not replace compiled client code. See [model modes](../docs/model-modes.md) and the [local guide](../docs/local-development.md).

Checks:

```sh
npm run lint
MODE=replay npm run build
```

The full dashboard separates risk severity from payment action. It presents older records without inventing missing payment decisions or device history. All data and payment outcomes are synthetic.
