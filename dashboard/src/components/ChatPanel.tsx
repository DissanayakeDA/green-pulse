"use client";

import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Sparkles, X } from "lucide-react";
import type { Chat } from "@/lib/chat";

const SUGGESTIONS = [
  "How is my plant doing?",
  "Does it need water today?",
  "How did the soil change today?",
  "When was it last watered?",
  "Is the weather a problem for it?",
];

export const TOOL_NAMES: Record<string, string> = {
  current_status: "live readings",
  plant_doctor_report: "Plant Doctor report",
  sensor_history: "sensor history",
  watering_log: "watering log",
};

/** Ask the Chat Agent about the plant. It answers from the live readings, the Plant Doctor's report,
 * the sensor history and the watering log, and says which of them it looked at. */
export function ChatPanel({ chat, plant, onClose }: { chat: Chat; plant: string; onClose?: () => void }) {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [chat.messages.length, chat.pending, chat.failed]);

  function submit(text: string) {
    if (!text.trim() || chat.pending) return;
    chat.send(text);
    setDraft("");
    input.current?.focus();
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex items-center gap-3">
          <Avatar />
          <div>
            <h2 className="text-sm font-semibold text-ink">GreenPulse assistant</h2>
            <p className="text-xs text-ink-3">Ask anything about your {plant}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {chat.messages.length > 0 && (
            <button type="button" onClick={chat.clear} className="rounded-md px-2.5 py-1 text-xs font-medium text-ink-3 hover:bg-hover hover:text-ink">
              Clear chat
            </button>
          )}
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-ink-3 hover:bg-hover hover:text-ink">
              <X className="size-5" />
            </button>
          )}
        </div>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-5 overflow-y-auto bg-sunk/60 px-5 py-5" aria-live="polite">
        {chat.messages.length === 0 && (
          <div className="rounded-xl border border-line bg-surface p-4">
            <p className="text-sm font-medium text-ink">Hi! I can check on your {plant} for you.</p>
            <p className="mt-1 text-xs text-ink-3">
              I look at the live sensors, the Plant Doctor&apos;s advice and the watering log before I answer. Try:
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => submit(suggestion)}
                  className="rounded-full border border-brand/25 bg-brand-softer px-3 py-1.5 text-left text-xs font-medium text-brand-ink transition-colors hover:border-brand/50 hover:bg-brand-soft"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {chat.messages.map((message) =>
          message.role === "user" ? (
            <p key={message.id} className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3.5 py-2 text-sm text-white">
              {message.content}
            </p>
          ) : (
            <div key={message.id} className="flex gap-2.5">
              <Avatar small />
              <div className="min-w-0 max-w-[92%]">
                <div className="rounded-2xl rounded-tl-sm border border-line bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-ink">
                  <Answer text={message.content} />
                </div>
                <AnswerMeta source={message.source} tools={message.tools} />
              </div>
            </div>
          ),
        )}

        {chat.pending && (
          <div className="flex items-center gap-2.5">
            <Avatar small />
            <p className="thinking flex items-center gap-1 rounded-2xl border border-line bg-surface px-3.5 py-2 text-sm text-ink-3" role="status">
              Checking your plant
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </p>
          </div>
        )}

        {chat.failed && !chat.pending && (
          <div role="alert" className="rounded-xl border border-critical/30 bg-critical-bg px-3.5 py-2.5 text-sm">
            <p className="text-critical-ink">{chat.failed.error}</p>
            <button type="button" onClick={chat.retry} className="mt-1 font-semibold text-ink underline underline-offset-2">
              Ask again
            </button>
          </div>
        )}
      </div>

      <form
        className="border-t border-line bg-surface p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
      >
        <div className="flex items-end gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2 transition-colors focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/15">
          <label htmlFor={inputId} className="sr-only">
            Your question
          </label>
          <textarea
            id={inputId}
            ref={input}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit(draft);
              }
            }}
            rows={1}
            maxLength={1000}
            placeholder={`Ask how your ${plant} is doing…`}
            className="field-sizing-content max-h-32 min-h-6 flex-1 resize-none bg-transparent py-1 text-sm outline-none placeholder:text-ink-3 focus-visible:outline-none"
          />
          <button
            type="submit"
            disabled={!draft.trim() || chat.pending}
            aria-label="Send"
            className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-white transition-colors hover:bg-brand-strong disabled:bg-line-strong"
          >
            <ArrowUp className="size-4" />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[0.7rem] text-ink-3">The assistant can&apos;t water the plant; use the Water now button for that.</p>
      </form>
    </div>
  );
}

function Avatar({ small = false }: { small?: boolean }) {
  return (
    <span className={`grid shrink-0 place-items-center rounded-full bg-brand text-white ${small ? "size-7" : "size-9"}`} aria-hidden>
      <Sparkles className={small ? "size-3.5" : "size-4"} />
    </span>
  );
}

function AnswerMeta({ source, tools }: { source?: string; tools?: string[] }) {
  const looked = [...new Set(tools ?? [])].map((tool) => TOOL_NAMES[tool] ?? tool);
  const note =
    source === "rules" ? "Quick answer: the AI is switched off" : source === "rules-fallback" ? "Quick answer: the AI couldn't be reached" : null;
  if (!looked.length && !note) return null;
  return (
    <p className="mt-1 px-1 text-[0.7rem] text-ink-3">
      {looked.length > 0 && `Looked at ${looked.join(" · ")}`}
      {looked.length > 0 && note && " — "}
      {note}
    </p>
  );
}

/** Plain text with the little Markdown the model tends to use: paragraphs, "-" / "1." lists and **bold**. */
function Answer({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length} className="list-decimal space-y-1 pl-5">{items}</ol>
      ) : (
        <ul key={blocks.length} className="list-disc space-y-1 pl-5">{items}</ul>
      ),
    );
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else {
      flush();
      if (line) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ""))}</p>);
    }
  }
  flush();
  return <div className="space-y-2">{blocks}</div>;
}

function inline(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}
