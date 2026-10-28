import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { formatPhone, formatTime } from "../lib/timeline";
import type { Contact, PhoneMessage, ServerEvent } from "../types";

interface Props {
  lastEvent: ServerEvent | null;
}

export function PhoneSimulator({ lastEvent }: Props) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contact, setContact] = useState<Contact>({ phone: "5511999990001", name: "Ana Souza" });
  const [chat, setChat] = useState<PhoneMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.contacts().then(setContacts).catch(() => setContacts([]));
  }, []);

  useEffect(() => {
    api.phoneChat(contact.phone).then(setChat).catch(() => setChat([]));
  }, [contact.phone]);

  useEffect(() => {
    if (lastEvent?.type === "simulator_delivery" && lastEvent.phone === contact.phone) {
      api.phoneChat(contact.phone).then(setChat);
    }
  }, [lastEvent, contact.phone]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  const run = async (action: () => Promise<unknown>) => {
    setSending(true);
    setError(null);
    try {
      await action();
      setChat(await api.phoneChat(contact.phone));
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSending(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    setText("");
    run(() => api.sendText(contact.phone, contact.name, message));
  };

  const attach = (file: File | undefined) => {
    if (!file) return;
    const caption = text.trim();
    setText("");
    run(() => api.sendMedia(contact.phone, contact.name, caption, file));
  };

  return (
    <section className="phone" aria-label="Simulador de WhatsApp">
      <div className="phone__top">
        <select
          className="phone__contact"
          value={contact.phone}
          onChange={(event) => {
            const chosen = contacts.find((item) => item.phone === event.target.value);
            if (chosen) setContact(chosen);
          }}
          aria-label="Contato simulado"
        >
          {contacts.map((item) => (
            <option key={item.phone} value={item.phone}>
              {item.name} · {formatPhone(item.phone)}
            </option>
          ))}
        </select>
        <span className="phone__store">Loja Aurora</span>
      </div>

      <div className="phone__chat">
        {chat.length === 0 && (
          <p className="phone__hint">Envie "Qual o status do pedido 1001?" para começar.</p>
        )}
        {chat.map((message) => (
          <div
            key={message.message_id}
            className={`bubble bubble--${message.direction === "from_phone" ? "me" : "them"}`}
          >
            {message.media && <span className="bubble__media">📎 anexo</span>}
            <span>{message.text}</span>
            <time>{formatTime(message.at)}</time>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      {error && <p className="phone__error">{error}</p>}

      <form className="phone__input" onSubmit={submit}>
        <button
          type="button"
          className="icon-button"
          onClick={() => fileInput.current?.click()}
          disabled={sending}
          aria-label="Anexar imagem"
        >
          📎
        </button>
        <input
          type="file"
          accept="image/*"
          hidden
          ref={fileInput}
          onChange={(event) => attach(event.target.files?.[0])}
        />
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Mensagem"
          aria-label="Mensagem"
          maxLength={2000}
        />
        <button type="submit" className="send-button" disabled={sending || !text.trim()}>
          ➤
        </button>
      </form>
    </section>
  );
}
