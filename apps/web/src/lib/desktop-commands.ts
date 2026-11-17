import type { AppId } from "./desktop-apps";

/**
 * Desktop commands Darius can carry out directly, typed or spoken: "open the library",
 * "generate the forest gate board", "compare the last two versions". Deliberately
 * bounded: the whole message must be one command, otherwise it goes to the normal
 * conversation. Commands never invent prompts or change a board's draft.
 */
export type BoardRef = { id: string; name: string };
export type DesktopCommand =
  | { kind: "open-app"; app: AppId }
  | { kind: "close-app"; app: AppId }
  | { kind: "show-canvas" }
  | { kind: "open-board"; boardId: string }
  | { kind: "generate-board"; boardId: string }
  | { kind: "compare-board"; boardId: string }
  | { kind: "new-board"; board: "moss" | "fibo" | "image" | "video" | "note" | "frame" };

const appWords: [AppId, RegExp][] = [
  ["chat", /^(?:the\s+)?(?:chat|conversations?|messages)$/],
  ["library", /^(?:the\s+|my\s+)?(?:library|media|assets|images|renders)$/],
  ["ideas", /^(?:the\s+|my\s+)?ideas?$/],
  ["characters", /^(?:the\s+)?(?:characters?|cast)$/],
  ["scenes", /^(?:the\s+)?scenes?$/],
  ["shots", /^(?:the\s+)?shots?(?:\s+list)?$/],
  ["map", /^(?:the\s+)?(?:world\s+)?map$/],
  ["edit", /^(?:the\s+)?(?:edit|editor|edit\s+desk|timeline|cut)$/],
  ["settings", /^(?:the\s+)?(?:settings|preferences)$/],
  ["cloud", /^(?:the\s+)?(?:cloud|flux(?:\s*3)?)$/],
  ["workflows", /^(?:the\s+)?(?:trusted\s+)?workflows?$/],
];

const clean = (text: string) => text.toLowerCase().replace(/[“”"’']/g, "").replace(/[.!?,]+\s*$/g, "").replace(/^\s*(?:hey\s+)?darius[,\s]+/, "").replace(/^(?:please|can you|could you|would you)\s+/, "").replace(/\s+please$/, "").replace(/\s+/g, " ").trim();
const appFor = (phrase: string) => appWords.find(([, pattern]) => pattern.test(phrase))?.[0] ?? null;

/** Best board for a spoken name: exact, then every word present. "this"/"it" means the selected board. */
export function findBoard(phrase: string, boards: BoardRef[], selectedId: string | null): string | null {
  const name = phrase.replace(/^(?:the|my)\s+/, "").replace(/\s+(?:board|composition|image|video)$/, "").trim();
  if (!name || /^(?:this|it|that|selected|current|this one)$/.test(name)) return selectedId;
  const exact = boards.find(board => board.name.toLowerCase() === name);
  if (exact) return exact.id;
  const words = name.split(" ").filter(word => word.length > 1);
  const matches = boards.filter(board => words.every(word => board.name.toLowerCase().includes(word)));
  return matches.length === 1 ? matches[0].id : null;
}

export function parseCommand(input: string, boards: BoardRef[], selectedId: string | null): DesktopCommand | null {
  const text = clean(input);
  if (!text || text.length > 80) return null;
  let m = text.match(/^(?:open|show(?: me)?|go to|bring up|switch to)\s+(.+)$/);
  if (m) {
    const target = m[1];
    if (/^(?:the\s+)?(?:canvas|boards|desktop)$/.test(target)) return { kind: "show-canvas" };
    const app = appFor(target);
    if (app) return { kind: "open-app", app };
    const board = findBoard(target, boards, selectedId);
    if (board && /^open\b/.test(text)) return { kind: "open-board", boardId: board };
    return null;
  }
  m = text.match(/^(?:close|hide)\s+(.+)$/);
  if (m) { const app = appFor(m[1]); return app ? { kind: "close-app", app } : null; }
  if (/^(?:back to|return to)\s+(?:the\s+)?(?:canvas|boards|desktop)$/.test(text)) return { kind: "show-canvas" };
  m = text.match(/^(?:generate|render|run)(?:\s+(.+))?$/);
  if (m) { const board = findBoard(m[1] ?? "this", boards, selectedId); return board ? { kind: "generate-board", boardId: board } : null; }
  m = text.match(/^compare(?:\s+the)?(?:\s+(?:last|latest)\s+two)?\s+versions(?:\s+(?:of|on|for)\s+(.+))?$/);
  if (m) { const board = findBoard(m[1] ?? "this", boards, selectedId); return board ? { kind: "compare-board", boardId: board } : null; }
  m = text.match(/^(?:new|add|create)\s+(?:a\s+)?(moss|fibo|image|video)\s+board$/) ?? text.match(/^(?:new|add|create)\s+(?:a\s+)?(?:sticky\s+)?(note|frame)$/);
  if (m) return { kind: "new-board", board: m[1] as "moss" };
  return null;
}

/** Parts of the desktop register what they can do; the shell and the canvas each own some. */
export type DesktopActions = {
  openApp: (app: AppId) => void;
  closeApp: (app: AppId) => void;
  showCanvas: () => void;
  boards: () => BoardRef[];
  selectedBoard: () => string | null;
  openBoard: (id: string, compare?: boolean) => void;
  generateBoard: (id: string) => void;
  newBoard: (kind: Extract<DesktopCommand, { kind: "new-board" }>["board"]) => void;
  /** Send free text to the conversation and show the chat. */
  ask: (text: string) => void;
};
const actions: Partial<DesktopActions> = {};
export function registerDesktopActions(part: Partial<DesktopActions>) {
  Object.assign(actions, part);
  return () => { for (const key of Object.keys(part) as (keyof DesktopActions)[]) if (actions[key] === part[key]) delete actions[key]; };
}
export function desktopActions() { return actions; }

const appTitles: Record<AppId, string> = { chat: "Chat", library: "Library", ideas: "Ideas", characters: "Characters", scenes: "Scenes", shots: "Shots", map: "World map", edit: "Edit", settings: "Settings", cloud: "Cloud · FLUX 3", workflows: "Trusted workflows" };

/** Carry out a parsed command. Returns what happened, for a short confirmation. */
export function runCommand(command: DesktopCommand): string | null {
  const a = actions, name = (id: string) => a.boards?.().find(board => board.id === id)?.name ?? "the board";
  switch (command.kind) {
    case "open-app": if (!a.openApp) return null; a.openApp(command.app); return `Opened ${appTitles[command.app]}.`;
    case "close-app": if (!a.closeApp) return null; a.closeApp(command.app); return `Closed ${appTitles[command.app]}.`;
    case "show-canvas": if (!a.showCanvas) return null; a.showCanvas(); return "Here are your boards.";
    case "open-board": if (!a.openBoard) return null; a.openBoard(command.boardId); return `Opened ${name(command.boardId)}.`;
    case "compare-board": if (!a.openBoard) return null; a.openBoard(command.boardId, true); return `Comparing the last two versions of ${name(command.boardId)}.`;
    case "generate-board": if (!a.generateBoard) return null; a.generateBoard(command.boardId); return `Generating ${name(command.boardId)}.`;
    case "new-board": if (!a.newBoard) return null; a.newBoard(command.board); return command.board === "note" ? "Added a note." : command.board === "frame" ? "Added a frame." : `Added a ${command.board === "moss" ? "MOSS" : command.board === "fibo" ? "FIBO" : command.board} board.`;
  }
}

/** Parse and run in one step; null when the text is ordinary conversation. */
export function tryDesktopCommand(text: string): string | null {
  const command = parseCommand(text, actions.boards?.() ?? [], actions.selectedBoard?.() ?? null);
  return command ? runCommand(command) : null;
}
