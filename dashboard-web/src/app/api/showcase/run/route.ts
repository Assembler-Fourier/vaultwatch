import { NextRequest, NextResponse } from "next/server";
import { getProvider } from "@/lib/llm/provider";
import { runPipeline } from "@/lib/orchestrator";
import { recordCase } from "@/lib/recentCases";
import { generateDemoTransaction } from "@/lib/synthetic";
import type { PipelineRunResponse, Transaction } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest): Promise<NextResponse<PipelineRunResponse | { error: string }>> {
  const { searchParams } = new URL(req.url);
  const forceRisky = searchParams.get("force_risky") === "true";

  const provider = getProvider();
  const tx = generateDemoTransaction(forceRisky) as unknown as Transaction;

  try {
    const { events, result } = await runPipeline(provider, tx);
    recordCase(tx, result);

    return NextResponse.json({
      transaction: tx,
      events,
      result,
      model_mode: provider.isLive ? "live" : "replay",
    });
  } catch (err) {
    console.error("pipeline run failed", err);
    return NextResponse.json({ error: err instanceof Error ? err.message : "pipeline run failed" }, { status: 500 });
  }
}
