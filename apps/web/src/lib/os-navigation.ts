import type { ViewId } from "./types";

const views: ViewId[] = ["home", "talk", "create", "map", "edit", "settings"];

export function isViewId(value: string | null): value is ViewId {
  return views.includes(value as ViewId);
}

export function rememberAppUrl(view: ViewId, projectId: string | null, mode: "push" | "replace" = "replace") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("app", view);
  if (projectId) url.searchParams.set("project", projectId);
  else url.searchParams.delete("project");
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  if (mode === "push") window.history.pushState({ app: view, projectId }, "", next);
  else window.history.replaceState({ app: view, projectId }, "", next);
}

export function readAppUrl() {
  if (typeof window === "undefined") return { view: null as ViewId | null, projectId: null as string | null };
  const params = new URLSearchParams(window.location.search);
  const app = params.get("app");
  return { view: isViewId(app) ? app : null, projectId: params.get("project") };
}
