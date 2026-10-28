import type { ChatEntry, Contact, Conversation, PhoneMessage, ServerEvent } from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ? String(body.detail) : `Erro ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  contacts: () => request<Contact[]>("/api/simulator/contacts"),
  phoneChat: (phone: string) => request<PhoneMessage[]>(`/api/simulator/chats/${phone}`),
  sendText: (phone: string, name: string, text: string) =>
    postJson("/api/simulator/messages", { phone, name, text }),
  sendMedia: (phone: string, name: string, caption: string, file: File) => {
    const form = new FormData();
    form.append("phone", phone);
    form.append("name", name);
    form.append("caption", caption);
    form.append("file", file);
    return request("/api/simulator/media", { method: "POST", body: form });
  },
  conversations: () => request<Conversation[]>("/api/conversations"),
  messages: (phone: string) => request<ChatEntry[]>(`/api/conversations/${phone}/messages`),
  events: (phone: string) => request<ServerEvent[]>(`/api/conversations/${phone}/events`),
  assume: (phone: string, attendant: string) =>
    postJson(`/api/conversations/${phone}/assume`, { attendant }),
  release: (phone: string) => postJson(`/api/conversations/${phone}/release`, {}),
  reply: (phone: string, attendant: string, text: string) =>
    postJson(`/api/conversations/${phone}/reply`, { attendant, text }),
};
