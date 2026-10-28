import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { formatPhone, statusLabel } from "../lib/timeline";
import type { Conversation, ServerEvent } from "../types";
import { ConversationDetail } from "./ConversationDetail";

interface Props {
  lastEvent: ServerEvent | null;
  connected: boolean;
}

export function AttendantPanel({ lastEvent, connected }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [attendant, setAttendant] = useState("Rita");

  const reload = useCallback(() => {
    api
      .conversations()
      .then((items) => {
        setConversations(items);
        setSelected((current) => current ?? items[0]?.id ?? null);
      })
      .catch(() => undefined);
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (lastEvent && lastEvent.type !== "tool_started") reload();
  }, [lastEvent, reload]);

  const current = conversations.find((item) => item.id === selected) ?? null;
  const waiting = conversations.filter((item) => item.status === "waiting_human").length;

  return (
    <section className="panel" aria-label="Painel do atendente">
      <header className="panel__header">
        <div>
          <h2>Atendimento</h2>
          <p className="muted">
            <span className={`dot ${connected ? "dot--on" : ""}`} />
            {connected ? "Tempo real conectado" : "Reconectando..."}
            {waiting > 0 && <strong className="badge badge--waiting_human">{waiting} na fila</strong>}
          </p>
        </div>
        <label className="panel__attendant">
          Atendente
          <input value={attendant} onChange={(event) => setAttendant(event.target.value)} />
        </label>
      </header>

      <div className="panel__body">
        <ul className="conversations">
          {conversations.length === 0 && <li className="muted">Nenhuma conversa ainda.</li>}
          {conversations.map((item) => (
            <li key={item.id}>
              <button
                className={`conversation ${item.id === selected ? "conversation--active" : ""}`}
                onClick={() => setSelected(item.id)}
              >
                <strong>{item.name || formatPhone(item.id)}</strong>
                <span className="muted">{formatPhone(item.id)}</span>
                <span className={`badge badge--${item.status}`}>{statusLabel(item.status)}</span>
              </button>
            </li>
          ))}
        </ul>

        {current ? (
          <ConversationDetail
            conversation={current}
            attendant={attendant}
            lastEvent={lastEvent}
            onChanged={reload}
          />
        ) : (
          <div className="card empty muted">Selecione uma conversa.</div>
        )}
      </div>
    </section>
  );
}
