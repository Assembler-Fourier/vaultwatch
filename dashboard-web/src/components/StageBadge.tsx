import type { PipelineStage } from "@/lib/types";

const STAGE_STYLES: Record<PipelineStage, string> = {
  rules: "bg-slate-800 text-slate-300 border-slate-600",
  prefilter: "bg-indigo-950 text-indigo-300 border-indigo-700",
  triage: "bg-amber-950 text-amber-300 border-amber-700",
  investigation: "bg-orange-950 text-orange-300 border-orange-700",
  compliance: "bg-purple-950 text-purple-300 border-purple-700",
  fusion: "bg-rose-950 text-rose-300 border-rose-700",
  closed: "bg-emerald-950 text-emerald-300 border-emerald-700",
};

const STAGE_LABELS: Record<PipelineStage, string> = {
  rules: "Rules",
  prefilter: "ML Pre-filter",
  triage: "Haiku Triage",
  investigation: "Sonnet Investigation",
  compliance: "Sonnet Compliance",
  fusion: "Security Fusion",
  closed: "Closed",
};

export function StageBadge({ stage }: { stage: PipelineStage }) {
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${STAGE_STYLES[stage]}`}>
      {STAGE_LABELS[stage]}
    </span>
  );
}

const SEVERITY_STYLES: Record<string, string> = {
  low: "bg-slate-800 text-slate-300 border-slate-600",
  medium: "bg-amber-950 text-amber-300 border-amber-700",
  high: "bg-orange-950 text-orange-300 border-orange-700",
  critical: "bg-red-950 text-red-300 border-red-700 animate-pulse",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.low}`}>
      {severity}
    </span>
  );
}
