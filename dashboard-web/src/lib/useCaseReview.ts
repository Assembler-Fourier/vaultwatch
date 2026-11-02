"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, Alert, PipelineResult, Transaction } from "./types";

export const API =
  process.env.NEXT_PUBLIC_AGENTS_HTTP_URL ?? "http://localhost:8000";
const WS =
  process.env.NEXT_PUBLIC_AGENTS_WS_URL ?? "ws://localhost:8000/v1/stream";
export type Scenario = "normal" | "review" | "unusual" | "sanctions" | "takeover";
export interface Receipt {
  seq: number;
  timestamp: string;
  event_type: string;
  hash: string;
  prev_hash: string;
}
export interface ReviewResult extends PipelineResult {
  payment?: {
    action: "allow" | "hold" | "block";
    policy_action: "allow" | "hold" | "block";
    policy_version: string;
    scope: "simulation_only";
    reasons: string[];
    execution_status: "simulated_complete" | "not_executed";
    simulation_receipt: { id: string } | null;
  };
  transaction?: Transaction & { beneficiary_name?: string };
  model_mode?: string;
  review?: {
    scenario: Scenario;
    source: string;
    origin: { name: string; lat: number; lon: number; timestamp: string };
    current_location: {
      name: string;
      lat: number;
      lon: number;
      timestamp: string;
    };
    distance_km: number;
    elapsed_minutes: number;
    implied_speed_kmh: number;
    baseline_average: number;
    new_device: boolean;
    new_beneficiary: boolean;
    location_note: string;
    login_evidence: { location: string; timestamp: string; source: string }[];
  };
  events?: (AgentEvent | Alert)[];
  audit?: {
    status: string;
    entries: Receipt[];
    errors: string[];
    checked_at?: string;
  };
}
export interface ReviewCase {
  transaction_id: string;
  account_id: string;
  result: ReviewResult;
}
export interface SystemStatus {
  model_mode: string;
  services: Record<string, string>;
  storage: string;
  checked_at: string;
}
export interface ChainStatus {
  verify: {
    valid: boolean;
    entries_checked: number;
    first_broken_seq: number | null;
  };
  checked_at: string;
}

export interface BatchResult {
  batch_id: string;
  requested: number;
  results: ReviewResult[];
  failures: { index: number; scenario: Scenario; message: string }[];
}

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}

export function useCaseReview() {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [selected, setSelected] = useState<ReviewCase | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const [batch, setBatch] = useState<BatchResult | null>(null);
  const [batchProgress, setBatchProgress] = useState<number | null>(null);
  const [pendingEvents, setPendingEvents] = useState<(AgentEvent | Alert)[]>(
    [],
  );

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      read<ReviewCase[]>("/v1/cases/recent"),
      read<SystemStatus>("/v1/status"),
      read<ChainStatus>("/v1/audit"),
    ]);
    const [history, health, audit] = results;
    if (history.status === "fulfilled") {
      setCases(history.value);
      setSelected(
        (previous) =>
          previous ??
          history.value.find((c) => c.result.review?.origin) ??
          null,
      );
      setHistoryError(null);
    }
    if (health.status === "fulfilled") setStatus(health.value);
    else setStatus(null);
    if (audit.status === "fulfilled") setChain(audit.value);
    else setChain(null);
    if (history.status === "rejected")
      setHistoryError("Case history is unavailable. Check the Python service.");
  }, []);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | undefined;
    let reconnect: ReturnType<typeof setTimeout>;
    let delay = 1000;
    const connect = () => {
      if (stopped) return;
      const current = new WebSocket(WS);
      socket = current;
      current.onopen = () => {
        if (stopped) {
          current.close();
          return;
        }
        setConnected(true);
        delay = 1000;
        void refresh();
      };
      current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "case_saved") void refresh();
          if (data.type === "batch_progress")
            setBatchProgress((current) => current === null ? null : data.completed);
          if (data.type === "agent_event" || data.type === "alert") {
            setPendingEvents((previous) => [...previous, data].slice(-60));
          }
        } catch {
          /* Ignore non-JSON transport frames. */
        }
      };
      current.onclose = () => {
        setConnected(false);
        if (!stopped) {
          reconnect = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 10000);
        }
      };
      current.onerror = () => current.close();
    };
    const kickoff = setTimeout(() => {
      void refresh();
      connect();
    }, 0);
    const poll = setInterval(() => void refresh(), 10000);
    return () => {
      stopped = true;
      clearTimeout(kickoff);
      clearTimeout(reconnect);
      clearInterval(poll);
      socket?.close();
    };
  }, [refresh]);

  const run = async (
    scenario: Scenario,
    amount: string,
    origin: string,
    destination: string,
  ) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setBatch(null);
    setError(null);
    setPendingEvents([]);
    try {
      const result = await read<ReviewResult>("/v1/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario,
          amount: amount ? Number(amount) : undefined,
          origin,
          destination,
        }),
      });
      if (!result.transaction)
        throw new Error("The server returned no transaction.");
      const record = {
        transaction_id: result.transaction.id,
        account_id: result.transaction.account_id,
        result,
      };
      setSelected(record);
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Transaction could not finish.",
      );
    } finally {
      setBusy(false);
      running.current = false;
    }
  };
  const runBatch = async () => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setBatch(null);
    setBatchProgress(0);
    setPendingEvents([]);
    try {
      const result = await read<BatchResult>("/v1/demo/batch", { method: "POST" });
      setBatch(result);
      const last = result.results.at(-1);
      if (last?.transaction) setSelected({
        transaction_id: last.transaction.id,
        account_id: last.transaction.account_id,
        result: last,
      });
      if (result.failures.length) setError(`${result.failures.length} of 10 could not be confirmed complete. Check the batch details and recent cases before rerunning.`);
      await refresh();
    } catch (failure) {
      setError(`${failure instanceof Error ? failure.message : "Batch response unavailable."} Some cases may have saved; check recent cases before rerunning.`);
    } finally {
      setBusy(false);
      setBatchProgress(null);
      running.current = false;
    }
  };
  return {
    cases,
    selected,
    setSelected,
    status,
    chain,
    connected,
    error: error ?? historyError,
    busy,
    pendingEvents,
    run,
    runBatch,
    batch,
    batchProgress,
    refresh,
  };
}
