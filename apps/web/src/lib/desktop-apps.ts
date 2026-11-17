import type { ViewId } from "./types";

/** Every tool that opens as a window over the project canvas. One window per app. */
export type AppId = "chat" | "library" | "ideas" | "characters" | "scenes" | "shots" | "cloud" | "workflows" | "map" | "edit" | "settings";

export type AppMeta = {
  title: string;
  /** The `?app=` value and store view this window represents when focused. */
  view: ViewId;
  size: { w: number; h: number };
  maximized?: boolean;
  /** Needs an active project. Settings is the only app available from the launcher. */
  project: boolean;
};

export const desktopApps: Record<AppId, AppMeta> = {
  chat: { title: "Chat", view: "talk", size: { w: 860, h: 640 }, project: true },
  library: { title: "Library", view: "create", size: { w: 980, h: 680 }, project: true },
  ideas: { title: "Ideas", view: "create", size: { w: 760, h: 620 }, project: true },
  characters: { title: "Characters", view: "create", size: { w: 900, h: 640 }, project: true },
  scenes: { title: "Scenes", view: "create", size: { w: 900, h: 640 }, project: true },
  shots: { title: "Shots", view: "create", size: { w: 1000, h: 680 }, project: true },
  cloud: { title: "Cloud · FLUX 3", view: "create", size: { w: 900, h: 680 }, project: true },
  workflows: { title: "Trusted workflows", view: "create", size: { w: 860, h: 640 }, project: true },
  map: { title: "World map", view: "map", size: { w: 1080, h: 720 }, project: true },
  edit: { title: "Edit", view: "edit", size: { w: 1280, h: 800 }, maximized: true, project: true },
  settings: { title: "Settings", view: "settings", size: { w: 900, h: 660 }, project: false },
};

/** Rail order: making things first, then structure, then finishing. */
export const railApps: AppId[] = ["chat", "library", "ideas", "characters", "scenes", "shots", "map", "edit", "cloud", "workflows"];

/** Views that name a window. `create` and `home` name the canvas and the launcher. */
export function appForView(view: ViewId): AppId | null {
  if (view === "talk") return "chat";
  if (view === "map") return "map";
  if (view === "edit") return "edit";
  if (view === "settings") return "settings";
  return null;
}
