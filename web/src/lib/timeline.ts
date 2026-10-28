import type { ConversationStatus, ServerEvent, ToolStep } from "../types";

export function toolSteps(events: ServerEvent[]): ToolStep[] {
  const steps = new Map<string, ToolStep>();
  for (const event of events) {
    const callId = String(event.data.call_id ?? "");
    if (!callId) continue;
    if (event.type === "tool_started") {
      steps.set(callId, {
        callId,
        tool: String(event.data.tool),
        arguments: (event.data.arguments as Record<string, unknown>) ?? {},
        status: "running",
        at: event.at,
      });
    } else if (event.type === "tool_finished") {
      const current = steps.get(callId);
      const base: ToolStep = current ?? {
        callId,
        tool: String(event.data.tool),
        arguments: (event.data.arguments as Record<string, unknown>) ?? {},
        status: "running",
        at: event.at,
      };
      steps.set(callId, {
        ...base,
        status: event.data.ok ? "ok" : "failed",
        result: event.data.result,
      });
    }
  }
  return [...steps.values()];
}

export function visibleArguments(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([key]) => key !== "telefone")
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

const STATUS_LABELS: Record<ConversationStatus, string> = {
  bot: "Assistente",
  waiting_human: "Aguardando atendente",
  human: "Com atendente",
};

export function statusLabel(status: ConversationStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function formatPhone(phone: string): string {
  const match = /^(\d{2})(\d{2})(\d{4,5})(\d{4})$/.exec(phone);
  return match ? `+${match[1]} (${match[2]}) ${match[3]}-${match[4]}` : phone;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
