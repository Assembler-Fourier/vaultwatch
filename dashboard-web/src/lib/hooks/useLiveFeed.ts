"use client";

// Data source for the dashboard. Two modes, selected by NEXT_PUBLIC_MODE:
//
// - "showcase" (default, what's deployed to Vercel): the browser itself
//   drives the demo loop, calling POST /api/showcase/run every few seconds
//   plus on-demand via the "Send risky transaction" button. Each call runs
//   one transaction through the whole in-process TS pipeline and returns
//   the full trace, which we replay client-side as a stream.
// - "full" (docker-compose / local review): connects to agents-python's
//   real WebSocket for genuine server-pushed events, and to gateway-go /
//   engine-rust for the auth and audit-chain pieces.
//
// Same UI, same event shapes, different transport - the dashboard
// components don't know or care which mode they're in.

import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, Alert, CaseFile, ComplianceReport, PipelineResult, PreFilterVerdict, RuleEngineVerdict, Transaction, TriageVerdict } from "../types";

export type FeedItem = (AgentEvent | Alert) & { key: string };

export interface CaseSummary {
  transaction: Transaction;
  result: PipelineResult;
  recorded_at: string;
}

const MODE: "full" | "showcase" = process.env.NEXT_PUBLIC_MODE === "full" ? "full" : "showcase";
const AGENTS_WS_URL = process.env.NEXT_PUBLIC_AGENTS_WS_URL ?? "ws://localhost:8000/v1/stream";
const AGENTS_HTTP_URL = process.env.NEXT_PUBLIC_AGENTS_HTTP_URL ?? "http://localhost:8000";

export function useLiveFeed() {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [modelMode, setModelMode] = useState<"live" | "replay" | "unknown">("unknown");
  const [auditStatus, setAuditStatus] = useState<{ valid: boolean; entries_checked: number } | null>(null);
  const [connected, setConnected] = useState(MODE === "showcase");
  const seq = useRef(0);

  const pushItem = useCallback((item: AgentEvent | Alert) => {
    seq.current += 1;
    setFeed((prev) => [{ ...item, key: `${item.transaction_id}-${seq.current}` }, ...prev].slice(0, 60));
  }, []);

  const refreshRecent = useCallback(async () => {
    try {
      const url = MODE === "full" ? `${AGENTS_HTTP_URL}/v1/cases/recent` : "/api/showcase/recent";
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      setCases(MODE === "full" ? data.map((d: { transaction_id: string; account_id: string; result: PipelineResult }) => ({
        transaction: { id: d.transaction_id, account_id: d.account_id } as Transaction,
        result: d.result,
        recorded_at: "",
      })) : data);
    } catch {
      // best-effort - the feed still works without recent-cases history
    }
  }, []);

  const refreshAudit = useCallback(async () => {
    try {
      const url = MODE === "full" ? undefined : "/api/showcase/audit";
      if (!url) return; // full mode's audit panel is wired via engine-rust directly, see AuditPanel
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      setAuditStatus(data.verify);
    } catch {
      // best-effort
    }
  }, []);

  const triggerRun = useCallback(
    async (forceRisky: boolean) => {
      if (MODE === "full") {
        await fetch(`${AGENTS_HTTP_URL}/v1/pipeline/run?force_risky=${forceRisky}`, { method: "POST" });
        return;
      }
      const res = await fetch(`/api/showcase/run?force_risky=${forceRisky}`, { method: "POST" });
      if (!res.ok) return;
      const data = await res.json();
      setModelMode(data.model_mode);
      for (const event of data.events as (AgentEvent | Alert)[]) {
        pushItem(event);
      }
      await refreshRecent();
      await refreshAudit();
    },
    [pushItem, refreshRecent, refreshAudit],
  );

  // Showcase mode: client-driven polling loop. `connected` is already
  // seeded true for this mode (see useState above) since there's no real
  // socket to wait on - the timeouts below just defer the first state
  // update out of the effect body itself, per the rules-of-hooks lint.
  useEffect(() => {
    if (MODE !== "showcase") return;
    const kickoff = setTimeout(() => void triggerRun(Math.random() < 0.3), 0);
    const interval = setInterval(() => {
      void triggerRun(Math.random() < 0.3);
    }, 7000);
    return () => {
      clearTimeout(kickoff);
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Full mode: real WebSocket connection to agents-python.
  useEffect(() => {
    if (MODE !== "full") return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(AGENTS_WS_URL);
    } catch {
      return;
    }
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "agent_event" || data.type === "alert") {
          pushItem(data);
          if (data.type === "alert") void refreshRecent();
        }
      } catch {
        // ignore malformed frames
      }
    };
    const kickoff = setTimeout(() => void refreshRecent(), 0);
    const interval = setInterval(() => void refreshRecent(), 10000);
    return () => {
      clearTimeout(kickoff);
      clearInterval(interval);
      socket.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { mode: MODE, feed, cases, modelMode, auditStatus, connected, triggerRun, refreshAudit };
}

export type { AgentEvent, Alert, CaseFile, ComplianceReport, PreFilterVerdict, RuleEngineVerdict, TriageVerdict };
