import { describe, expect, it } from "vitest";
import type { ServerEvent } from "../types";
import { formatPhone, statusLabel, toolSteps, visibleArguments } from "./timeline";

function event(type: string, data: Record<string, unknown>): ServerEvent {
  return { id: Math.random().toString(), type, phone: "5511999990001", data, at: "2026-01-01T10:00:00Z" };
}

describe("toolSteps", () => {
  it("pairs started and finished events by call id", () => {
    const steps = toolSteps([
      event("tool_started", { call_id: "a", tool: "consultar_pedido", arguments: { numero_pedido: "1001" } }),
      event("tool_started", { call_id: "b", tool: "rastrear_entrega", arguments: {} }),
      event("tool_finished", { call_id: "a", tool: "consultar_pedido", ok: true, result: { status: "entregue" } }),
    ]);
    expect(steps.map((s) => [s.tool, s.status])).toEqual([
      ["consultar_pedido", "ok"],
      ["rastrear_entrega", "running"],
    ]);
    expect(steps[0].result).toEqual({ status: "entregue" });
  });

  it("marks failed tools and ignores unrelated events", () => {
    const steps = toolSteps([
      event("message_received", { text: "oi" }),
      event("tool_finished", { call_id: "x", tool: "agendar_troca", ok: false, result: "fora do prazo" }),
    ]);
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("failed");
  });
});

describe("formatters", () => {
  it("hides the injected phone argument", () => {
    expect(visibleArguments({ telefone: "5511", numero_pedido: "1001" })).toBe("numero_pedido: 1001");
  });

  it("formats brazilian phones and statuses", () => {
    expect(formatPhone("5511999990001")).toBe("+55 (11) 99999-0001");
    expect(formatPhone("123")).toBe("123");
    expect(statusLabel("waiting_human")).toBe("Aguardando atendente");
  });
});
