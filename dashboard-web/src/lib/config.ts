// Showcase-mode runtime config. Mirrors agents-python/app/config.py's
// MODE semantics: "live" always calls Anthropic, "replay" never does,
// "auto" (default) uses live calls only if ANTHROPIC_API_KEY is set. That
// last mode is what lets this run for free the moment it's deployed, and
// switch to real Claude reasoning the instant a key is added to the
// Vercel project - no code change either way.

export type Mode = "live" | "replay" | "auto";

export function resolveUseLiveModels(): boolean {
  const mode = (process.env.MODE ?? "auto") as Mode;
  const hasKey = !!process.env.ANTHROPIC_API_KEY;
  if (mode === "live") return true;
  if (mode === "replay") return false;
  return hasKey;
}

export const HAIKU_MODEL = process.env.HAIKU_MODEL ?? "claude-haiku-4-5-20251001";
export const SONNET_MODEL = process.env.SONNET_MODEL ?? "claude-sonnet-5";
