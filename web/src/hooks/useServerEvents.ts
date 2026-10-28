import { useEffect, useRef, useState } from "react";
import type { ServerEvent } from "../types";

const EVENT_TYPES = [
  "message_received",
  "message_sent",
  "tool_started",
  "tool_finished",
  "status_changed",
  "simulator_delivery",
];

export function useServerEvents(onEvent: (event: ServerEvent) => void) {
  const handler = useRef(onEvent);
  const [connected, setConnected] = useState(false);
  handler.current = onEvent;

  useEffect(() => {
    const source = new EventSource("/api/events");
    const listener = (message: MessageEvent<string>) => handler.current(JSON.parse(message.data));
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    EVENT_TYPES.forEach((type) => source.addEventListener(type, listener));
    return () => source.close();
  }, []);

  return connected;
}
