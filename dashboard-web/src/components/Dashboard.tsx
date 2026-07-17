"use client";

import { useMemo, useState } from "react";
import { useLiveFeed, type FeedItem } from "@/lib/hooks/useLiveFeed";
import type { Alert, AgentEvent } from "@/lib/types";
import { SeverityBadge, StageBadge } from "./StageBadge";

function isAlert(item: FeedItem): item is Alert & { key: string } {
  return item.type === "alert";
}

function isAgentEvent(item: FeedItem): item is AgentEvent & { key: string } {
  return item.type === "agent_event";
}

export function Dashboard() {
  const { mode, feed, cases, modelMode, auditStatus, connected, triggerRun } = useLiveFeed();
  const [pending, setPending] = useState(false);

  const alerts = useMemo(() => feed.filter(isAlert).slice(0, 12), [feed]);
  const events = useMemo(() => feed.filter(isAgentEvent), [feed]);

  const stats = useMemo(() => {
    const total = cases.length;
    const escalated = cases.filter((c) => c.result.stage_reached !== "closed").length;
    const critical = cases.filter((c) => c.result.alert?.severity === "critical").length;
    return { total, escalated, critical };
  }, [cases]);

  async function handleSendRisky() {
    setPending(true);
    try {
      await triggerRun(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 border-b border-neutral-800 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-neutral-50">
            VaultWatch <span className="text-neutral-500">/ ops</span>
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-400">
            A tiered multi-agent Claude pipeline fusing financial-fraud signals with account-security signals into
            one live view. Every transaction, account and identity here is synthetic.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-300">
            <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-500" : "bg-neutral-600"}`} />
            {mode === "full" ? "full stack" : "showcase"}
          </span>
          <span
            className={`inline-flex items-center rounded border px-2 py-1 text-xs font-medium ${
              modelMode === "live"
                ? "border-emerald-700 bg-emerald-950 text-emerald-300"
                : "border-neutral-700 bg-neutral-900 text-neutral-400"
            }`}
          >
            {modelMode === "live" ? "live Claude calls" : modelMode === "replay" ? "replay mode (no API key)" : "connecting…"}
          </span>
          <button
            onClick={handleSendRisky}
            disabled={pending}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-red-600 disabled:opacity-50"
          >
            {pending ? "Sending…" : "Send risky transaction"}
          </button>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Transactions seen" value={stats.total} />
        <StatTile label="Escalated past stage 0" value={stats.escalated} />
        <StatTile label="Critical alerts" value={stats.critical} accent="text-red-400" />
        <StatTile
          label="Audit chain"
          value={auditStatus ? (auditStatus.valid ? "verified" : "TAMPERED") : "…"}
          accent={auditStatus?.valid === false ? "text-red-400" : "text-emerald-400"}
          small
        />
      </section>

      <main className="grid flex-1 grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PanelHeader title="Reasoning trace" subtitle="Every stage each transaction passed through, in order" />
          <div className="mt-3 space-y-2 rounded-lg border border-neutral-800 bg-neutral-900/50 p-3">
            {events.length === 0 && <EmptyState text="Waiting for the first transaction…" />}
            {events.map((event) => (
              <div key={event.key} className="rounded border border-neutral-800 bg-neutral-950 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <StageBadge stage={event.stage} />
                  <span className="font-mono text-xs text-neutral-500">{event.account_id}</span>
                </div>
                <p className="mt-2 text-neutral-200">{event.label}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <div>
            <PanelHeader title="Alerts" subtitle="Financial risk, fused with account security where relevant" />
            <div className="mt-3 space-y-2">
              {alerts.length === 0 && <EmptyState text="No alerts yet." />}
              {alerts.map((alert) => (
                <div key={alert.key} className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <SeverityBadge severity={alert.severity} />
                    {alert.fused_with_security_event && (
                      <span className="text-xs font-medium text-rose-400">fraud + security fusion</span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-neutral-200">{alert.title}</p>
                  <p className="mt-1 font-mono text-xs text-neutral-500">{alert.account_id}</p>
                </div>
              ))}
            </div>
          </div>

          <div>
            <PanelHeader title="About this demo" subtitle={null} />
            <div className="mt-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-3 text-xs leading-relaxed text-neutral-400">
              <p>
                Stage 0 (deterministic rules + a statistical pre-filter) runs on every transaction for free. Only
                anomalies reach Haiku triage; only triage-escalated cases reach Sonnet for tool-using investigation
                and, if warranted, a synthetic compliance narrative.
              </p>
              <p className="mt-2">
                {mode === "showcase"
                  ? "This is the public showcase: a self-contained TypeScript port of the pipeline running as Vercel serverless functions. The full polyglot system (Rust risk engine, Go auth gateway, Python agent orchestrator) runs via docker compose - see the README."
                  : "You're viewing the full stack: Rust risk engine, Go auth gateway, and the Python agent orchestrator, wired together over Redis and Postgres."}
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function StatTile({ label, value, accent, small }: { label: string; value: string | number; accent?: string; small?: boolean }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-3">
      <p className="text-xs text-neutral-500">{label}</p>
      <p className={`mt-1 font-bold ${small ? "text-sm" : "text-2xl"} ${accent ?? "text-neutral-100"}`}>{value}</p>
    </div>
  );
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string | null }) {
  return (
    <div>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">{title}</h2>
      {subtitle && <p className="text-xs text-neutral-500">{subtitle}</p>}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="p-4 text-center text-sm text-neutral-600">{text}</p>;
}
