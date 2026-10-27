export type EditShortcut = "undo" | "redo" | "save" | "play" | "split" | "trim-start" | "trim-end" | "delete" | "ripple-delete" | "mute" | "snap" | "help" | "cancel" | "home" | "end" | "previous-frame" | "next-frame" | "move-left" | "move-right" | "in-left" | "in-right" | "out-left" | "out-right";
type Key = { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean; repeat?: boolean };
export function editShortcut(event: Key): EditShortcut | null {
  const key = event.key.toLowerCase(), command = event.ctrlKey || event.metaKey;
  if (command) {
    if (event.altKey) return null;
    if (key === "z") return event.shiftKey ? "redo" : "undo";
    if (key === "y" && !event.shiftKey) return "redo";
    if (key === "s" && !event.shiftKey && !event.repeat) return "save";
    return null;
  }
  if (key === "arrowleft" || key === "arrowright") return event.altKey ? key === "arrowleft" ? "move-left" : "move-right" : key === "arrowleft" ? "previous-frame" : "next-frame";
  if (event.altKey) return null;
  if (key === "[" || key === "]" || key === "{" || key === "}") return event.shiftKey ? key === "[" || key === "{" ? "out-left" : "out-right" : key === "[" ? "in-left" : "in-right";
  if (event.repeat) return null;
  if (key === "escape") return "cancel";
  if (key === "?" || key === "f1") return "help";
  if (key === "home") return "home";
  if (key === "end") return "end";
  if (key === "delete" || key === "backspace") return event.shiftKey ? "ripple-delete" : "delete";
  if (event.shiftKey) return null;
  return ({ " ": "play", k: "play", s: "split", q: "trim-start", w: "trim-end", m: "mute", n: "snap" } as Record<string, EditShortcut>)[key] ?? null;
}
