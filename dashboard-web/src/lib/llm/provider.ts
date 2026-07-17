// Model-provider abstraction for showcase mode - a TS port of
// agents-python/app/llm/provider.py's design. Agents talk to a
// ModelProvider, never to the Anthropic SDK directly, so a ReplayProvider
// can stand in with zero code changes in the agents themselves.

import Anthropic from "@anthropic-ai/sdk";
import * as transcripts from "./transcripts";

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ModelResponse {
  text: string;
  toolCalls: ToolCall[];
  stopReason: string;
}

export interface ToolSchema {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface CompleteArgs {
  model: string;
  system: string;
  messages: Anthropic.MessageParam[];
  tools?: ToolSchema[];
  toolChoice?: { type: "tool"; name: string };
  replayFamily?: "triage" | "investigation" | "compliance";
  replayScenario?: string;
  replayVars?: Record<string, string>;
}

export interface ModelProvider {
  readonly isLive: boolean;
  complete(args: CompleteArgs): Promise<ModelResponse>;
}

export class AnthropicProvider implements ModelProvider {
  readonly isLive = true;
  private client: Anthropic;

  constructor(apiKey: string) {
    this.client = new Anthropic({ apiKey });
  }

  async complete({ model, system, messages, tools, toolChoice }: CompleteArgs): Promise<ModelResponse> {
    const response = await this.client.messages.create({
      model,
      max_tokens: 1536,
      system,
      messages,
      tools: tools as Anthropic.Tool[] | undefined,
      tool_choice: toolChoice,
    });

    const textParts: string[] = [];
    const toolCalls: ToolCall[] = [];
    for (const block of response.content) {
      if (block.type === "text") {
        textParts.push(block.text);
      } else if (block.type === "tool_use") {
        toolCalls.push({ id: block.id, name: block.name, input: block.input as Record<string, unknown> });
      }
    }

    return { text: textParts.join(""), toolCalls, stopReason: response.stop_reason ?? "end_turn" };
  }
}

export class ReplayProvider implements ModelProvider {
  readonly isLive = false;

  async complete({ messages, replayFamily, replayScenario = "low", replayVars = {} }: CompleteArgs): Promise<ModelResponse> {
    const turn = messages.filter((m) => m.role === "assistant").length;

    let step: transcripts.ReplayStep;
    if (replayFamily === "triage") {
      step = transcripts.triageStep(replayScenario);
    } else if (replayFamily === "investigation") {
      const steps = transcripts.investigationSteps(replayScenario, replayVars.account_id ?? "acct_unknown");
      step = steps[Math.min(turn, steps.length - 1)];
    } else if (replayFamily === "compliance") {
      step = transcripts.complianceStep(replayVars.account_id ?? "acct_unknown");
    } else {
      step = { text: "[replay mode: no script configured for this agent]" };
    }

    if ("tool" in step) {
      return {
        text: "",
        toolCalls: [{ id: `replay_${Math.random().toString(16).slice(2, 10)}`, name: step.tool, input: step.input }],
        stopReason: "tool_use",
      };
    }
    return { text: step.text, toolCalls: [], stopReason: "end_turn" };
  }
}

export function getProvider(): ModelProvider {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  const mode = process.env.MODE ?? "auto";
  const useLive = mode === "live" || (mode === "auto" && !!apiKey);
  if (useLive && apiKey) {
    return new AnthropicProvider(apiKey);
  }
  return new ReplayProvider();
}
