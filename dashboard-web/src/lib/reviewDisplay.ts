import type { ReviewResult, Scenario } from "./useCaseReview";

export const scenarioNames: Record<Scenario, string> = {
  normal: "Normal payment", review: "Review needed", unusual: "Unusual payment",
  sanctions: "Watchlist match", takeover: "Account takeover",
};
export const scenarioDescriptions: Record<Scenario, string> = {
  normal: "A familiar recipient, known device and usual amount.",
  review: "Several small payments from a new device, without a location change.",
  unusual: "A large payment with a new device, recipient and location.",
  sanctions: "A fabricated watchlist match for the recipient.",
  takeover: "A payment matched to suspicious logins through Go and Redis.",
};
export const paymentLabels = { allow: "Allowed", hold: "On hold", block: "Blocked" };
export const paymentTone = { allow: "good", hold: "warn", block: "danger" };
export const severityOf = (r: ReviewResult) => r.alert?.severity ?? r.rules?.risk_band ?? "unknown";
export const human = (value: string) => value.replaceAll("_", " ");
export const money = (amount?: number, currency = "EUR") => typeof amount === "number"
  ? new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(amount) : "Earlier record";
export const time = (value?: string) => value ? new Date(value).toLocaleString("en-IE", {
  timeZone: "Europe/Dublin", hour12: false,
}) : "Not recorded";
