import { NextResponse } from "next/server";
import { recentAuditEntries, verifyAuditChain } from "@/lib/audit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const [verify, entries] = await Promise.all([verifyAuditChain(), Promise.resolve(recentAuditEntries(20))]);
  return NextResponse.json({ verify, entries });
}
