import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { formatTime, statusLabel, toolSteps, visibleArguments } from "../lib/timeline";
import type { ChatEntry, Conversation, ServerEvent, ToolStep } from "../types";

const TOOL_LABELS: Record<string, string> = {
  consultar_pedido: "Consultou pedido",
  rastrear_entrega: "Rastreou entrega",
  agendar_troca: "Agendou troca",
  abrir_chamado: "Abriu chamado",
  transferir_para_humano: "Transferiu para humano",
};

interface Props {
  conversation: Conversation;
  attendant: string;
  lastEvent: ServerEvent | null;
  onChanged: () => void;
}

export function ConversationDetail({ conversation, attendant, lastEvent, onChanged }: Props) {
  const phone = conversation.id;
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [steps, setSteps] = useState<ToolStep[]>([]);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.messages(phone).then(setMessages).catch(() => setMessages([]));
    api.events(phone).then((events) => setSteps(toolSteps(events))).catch(() => setSteps([]));
  }, [phone]);

  useEffect(() => {
    if (!lastEvent || lastEvent.phone !== phone) return;
    if (lastEvent.type.startsWith("tool_")) {
      api.events(phone).then((events) => setSteps(toolSteps(events)));
    } else if (lastEvent.type.startsWith("message_")) {
      api.messages(phone).then(setMessages);
    }
  }, [lastEvent, phone]);

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      onChanged();
      setMessages(await api.messages(phone));
    } catch (cause) {
      setError((cause as Error).message);
    }
  };

  const send = (event: FormEvent) => {
    event.preventDefault();
    const text = reply.trim();
    if (!text) return;
    setReply("");
    act(() => api.reply(phone, attendant, text));
  };

  const isHuman = conversation.status === "human";

  return (
    <div className="detail">
      <div className="card detail__chat">
        <div className="detail__head">
          <div>
            <strong>{conversation.name || phone}</strong>
            <span className={`badge badge--${conversation.status}`}>
              {statusLabel(conversation.status)}
              {conversation.attendant ? ` · ${conversation.attendant}` : ""}
            </span>
            {conversation.handoff_reason && (
              <p className="muted">Motivo: {conversation.handoff_reason}</p>
            )}
          </div>
          <div className="detail__actions">
            {!isHuman && (
              <button className="button" onClick={() => act(() => api.assume(phone, attendant))}>
                Assumir conversa
              </button>
            )}
            {conversation.status !== "bot" && (
              <button className="button button--ghost" onClick={() => act(() => api.release(phone))}>
                Devolver ao assistente
              </button>
            )}
          </div>
        </div>

        {error && <p className="alert">{error}</p>}

        <ol className="messages">
          {messages.map((message, index) => (
            <li key={message.message_id ?? index} className={`message message--${message.author}`}>
              <span className="message__author">
                {message.author === "customer"
                  ? "Cliente"
                  : message.author === "attendant"
                    ? `Atendente ${message.attendant ?? ""}`
                    : "Assistente"}
              </span>
              <p>{message.text}</p>
              {message.media_key && <code className="message__media">{message.media_key}</code>}
              <time>{formatTime(message.at)}</time>
            </li>
          ))}
        </ol>

        <form className="detail__reply" onSubmit={send}>
          <input
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            placeholder={isHuman ? "Responder como atendente" : "Assuma a conversa para responder"}
            disabled={!isHuman}
            aria-label="Resposta do atendente"
          />
          <button className="button" type="submit" disabled={!isHuman || !reply.trim()}>
            Enviar
          </button>
        </form>
      </div>

      <aside className="card trace">
        <h3>Ferramentas MCP do agente</h3>
        {steps.length === 0 && <p className="muted">Nenhuma ferramenta chamada nesta conversa.</p>}
        <ol className="trace__list">
          {steps.map((step) => (
            <li key={step.callId} className={`trace__step trace__step--${step.status}`}>
              <span className="trace__dot" aria-hidden />
              <div>
                <strong>{TOOL_LABELS[step.tool] ?? step.tool}</strong>
                <p className="muted">{visibleArguments(step.arguments)}</p>
                {step.status !== "running" && (
                  <details>
                    <summary>Resultado</summary>
                    <pre>{JSON.stringify(step.result, null, 2)}</pre>
                  </details>
                )}
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
