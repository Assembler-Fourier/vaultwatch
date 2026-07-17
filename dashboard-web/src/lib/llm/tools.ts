// Research tools exposed to the investigator agent via Claude's tool-use.
// TS port of agents-python/app/llm/tools.py, backed by the same synthetic
// generators.

import { checkSanctionsList, generateEntityGraph, generateTransactionHistory } from "../synthetic";
import type { ToolSchema } from "./provider";

export const RESEARCH_TOOL_SCHEMAS: ToolSchema[] = [
  {
    name: "get_transaction_history",
    description: "Fetch an account's recent transaction history to establish its normal spending baseline.",
    input_schema: {
      type: "object",
      properties: { account_id: { type: "string" } },
      required: ["account_id"],
    },
  },
  {
    name: "get_entity_graph",
    description: "Fetch accounts linked to the given account via shared device, beneficiary, or other identifiers.",
    input_schema: {
      type: "object",
      properties: { account_id: { type: "string" } },
      required: ["account_id"],
    },
  },
  {
    name: "check_sanctions_list",
    description: "Screen a name against the sanctions/watchlist.",
    input_schema: {
      type: "object",
      properties: { name: { type: "string" } },
      required: ["name"],
    },
  },
];

export function executeResearchTool(name: string, input: Record<string, unknown>): Record<string, unknown> {
  if (name === "get_transaction_history") {
    return { history: generateTransactionHistory(String(input.account_id)) };
  }
  if (name === "get_entity_graph") {
    return generateEntityGraph(String(input.account_id));
  }
  if (name === "check_sanctions_list") {
    return checkSanctionsList(String(input.name));
  }
  throw new Error(`unknown research tool: ${name}`);
}
