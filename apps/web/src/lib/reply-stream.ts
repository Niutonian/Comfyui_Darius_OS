import type { Message } from "./types";
import { spokenText } from "./chat-labels";

export async function readReplyStream(response: Response, onDelta: (text: string) => void): Promise<Message> {
  if (!response.body) throw new Error("The reply stream is unavailable. Retry the saved message.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  function consume(line: string): Message | undefined {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "error") throw new Error(event.detail || "The reply was interrupted. Retry the saved message.");
    if (event.type === "delta" && typeof event.text === "string") onDelta(event.text);
    if (event.type === "done" && typeof event.message?.content === "string") return event.message;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      let boundary: number;
      while ((boundary = pending.indexOf("\n")) >= 0) {
        const message = consume(pending.slice(0, boundary));
        pending = pending.slice(boundary + 1);
        if (message) return message;
      }
      if (done) {
        const message = consume(pending);
        if (message) return message;
        throw new Error("The final reply was incomplete. Retry the saved message.");
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

/** Keep incomplete sentences until more text arrives; bound long punctuation-free speech. */
export function speechChunks(text: string, final = false): { chunks: string[]; rest: string } {
  const chunks: string[] = [];
  while (text.length) {
    const sentence = (final ? /[.!?。！？](?:["”')]*)(?:\s+|$)/ : /[.!?。！？](?:["”')]*)(?:\s+)/).exec(text);
    let end = sentence ? sentence.index + sentence[0].length : 0;
    if (end > 240) end = 0;
    if (!end && text.length > 240) end = text.lastIndexOf(" ", 240) > 0 ? text.lastIndexOf(" ", 240) + 1 : 240;
    if (!end && final) end = text.length;
    if (!end) break;
    const chunk = spokenText(text.slice(0, end));
    if (chunk) chunks.push(chunk);
    text = text.slice(end);
  }
  return { chunks, rest: text };
}
