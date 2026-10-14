"use client";

import { useCallback, useEffect, useState } from "react";
import type { ChatAnswer, ChatTurn } from "./types";
import { api } from "./hooks";

export interface ChatMessage extends ChatTurn {
  id: string;
  source?: string;
  tools?: string[];
}

const KEEP = 40; // messages remembered in this browser
const CONTEXT = 10; // earlier messages sent along for follow-up questions

let counter = 0;
const newId = () => `${Date.now()}-${counter++}`;

/** The conversation with the Chat Agent for one device, kept in this browser between visits. */
export function useChat(deviceId: string | null) {
  const storageKey = deviceId ? `greenpulse-chat:${deviceId}` : null;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState<{ question: string; error: string } | null>(null);

  useEffect(() => {
    if (!storageKey) return;
    let saved: ChatMessage[] = [];
    try {
      saved = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    } catch {
      // private window or blocked storage: start a fresh conversation
    }
    setMessages(Array.isArray(saved) ? saved : []);
    setLoadedKey(storageKey);
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || loadedKey !== storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages.slice(-KEEP)));
    } catch {
      // not saved; the conversation still works for this visit
    }
  }, [storageKey, loadedKey, messages]);

  const ask = useCallback(
    async (text: string, earlier: ChatMessage[]) => {
      const question = text.trim();
      if (!question || !deviceId) return;
      const history: ChatTurn[] = earlier.slice(-CONTEXT).map(({ role, content }) => ({ role, content: content.slice(0, 4000) }));
      setMessages([...earlier, { id: newId(), role: "user", content: question }]);
      setPending(true);
      setFailed(null);
      try {
        const answer = await api<ChatAnswer>(`/api/devices/${encodeURIComponent(deviceId)}/chat`, {
          method: "POST",
          body: JSON.stringify({ message: question.slice(0, 1000), history }),
        });
        setMessages((current) => [
          ...current,
          { id: newId(), role: "assistant", content: answer.answer, source: answer.source, tools: answer.tools },
        ]);
      } catch (e) {
        setFailed({ question, error: e instanceof Error ? e.message : String(e) });
      } finally {
        setPending(false);
      }
    },
    [deviceId],
  );

  const send = useCallback((text: string) => !pending && ask(text, messages), [ask, messages, pending]);

  /** Ask the failed question again, in place of the unanswered copy. */
  const retry = useCallback(() => {
    if (!failed || pending) return;
    const earlier = messages.at(-1)?.role === "user" ? messages.slice(0, -1) : messages;
    ask(failed.question, earlier);
  }, [ask, failed, messages, pending]);

  const clear = useCallback(() => {
    setMessages([]);
    setFailed(null);
  }, []);

  return { messages, pending, failed, send, retry, clear };
}

export type Chat = ReturnType<typeof useChat>;
