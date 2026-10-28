import { useState } from "react";
import { AttendantPanel } from "./components/AttendantPanel";
import { PhoneSimulator } from "./components/PhoneSimulator";
import { useServerEvents } from "./hooks/useServerEvents";
import type { ServerEvent } from "./types";

export function App() {
  const [lastEvent, setLastEvent] = useState<ServerEvent | null>(null);
  const connected = useServerEvents(setLastEvent);

  return (
    <div className="layout">
      <header className="header">
        <h1>ZapAgent</h1>
        <p className="muted">
          Atendimento no WhatsApp com agente de IA, ferramentas MCP e transferência para humanos.
        </p>
      </header>
      <main className="content">
        <PhoneSimulator lastEvent={lastEvent} />
        <AttendantPanel lastEvent={lastEvent} connected={connected} />
      </main>
    </div>
  );
}
