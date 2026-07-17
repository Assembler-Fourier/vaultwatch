import { NextRequest, NextResponse } from "next/server";
import { recentCases } from "@/lib/recentCases";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const limit = Number(new URL(req.url).searchParams.get("limit") ?? "50");
  return NextResponse.json(recentCases(limit));
}
