export type ConversationStatus = "bot" | "waiting_human" | "human";

export interface Conversation {
  id: string;
  name: string;
  status: ConversationStatus;
  handoff_reason: string | null;
  attendant: string | null;
  updated_at: string;
}

export interface ChatEntry {
  phone: string;
  direction: "in" | "out";
  author: "customer" | "bot" | "attendant" | "system";
  text: string;
  at: string;
  message_id: string | null;
  media_key: string | null;
  attendant: string | null;
}

export interface Contact {
  phone: string;
  name: string;
}

export interface PhoneMessage {
  phone: string;
  direction: "from_phone" | "to_phone";
  text: string;
  media: boolean;
  at: string;
  message_id: string;
}

export interface ServerEvent {
  id: string;
  type: string;
  phone: string;
  data: Record<string, unknown>;
  at: string;
}

export interface ToolStep {
  callId: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: "running" | "ok" | "failed";
  result?: unknown;
  at: string;
}
