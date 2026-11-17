import React from "react";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDariusStore } from "@/lib/store";
import { useWindowStore } from "@/lib/window-store";
import type { ViewId } from "@/lib/types";
import { useKnownJobs } from "@/lib/queries";
import { AppShell } from "./app-shell";

vi.mock("@/lib/queries", () => ({
  useHealth: () => ({ data: { components: {} } }),
  useProjects: () => ({}),
  useWorkflows: () => ({}),
  useProjectWorkflows: () => ({}),
  useProjectEventStream: () => undefined,
  useKnownJobs: vi.fn(() => ({ jobs: [] })),
  useProjectJobs: () => ({}),
  useProjectAssets: () => ({}),
  useCharacters: () => ({ data: [] }),
}));
vi.mock("@/lib/creative-ideas", () => ({ ideasApi: { list: async () => [] } }));
vi.mock("./creative-message", () => ({ CreativeChatWelcome: () => <div>Talk content</div>, CreativeMessage: ({message}: {message: {content: string}}) => <p>{message.content}</p> }));
vi.mock("./moss-workspace", () => ({ MossWorkspace: () => <div data-testid="canvas">Canvas boards</div> }));
vi.mock("./home-desktop", () => ({ HomeDesktop: () => <div data-testid="launcher">Projects</div> }));
vi.mock("./library-app", () => ({ LibraryApp: () => <div>Library content</div> }));
vi.mock("./map-view", () => ({ MapView: () => <div>Map content</div> }));
vi.mock("./edit-view", () => ({ EditView: () => <div>Edit content</div> }));
vi.mock("./settings-view", () => ({ SettingsView: () => <div>Settings content</div> }));
vi.mock("./composer", () => ({ Composer: () => <textarea aria-label="Message Darius" /> }));
vi.mock("./project-selector", () => ({ ProjectSelector: () => <div>Projects</div> }));
vi.mock("./inspector", () => ({ Inspector: () => null }));
vi.mock("./job-tray", () => ({ JobTray: () => null }));
// Console behavior/auth is covered separately; navigation uses isolated children.
vi.mock("./diagnostic-console", () => ({ DiagnosticConsole: () => <button aria-label="Open diagnostic console">Console</button> }));
vi.mock("./ambient-background", () => ({ AmbientBackground: () => null }));

function show() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AppShell /></QueryClientProvider>);
}
const rail = () => within(screen.getByRole("navigation", { name: "Apps" }));

beforeEach(() => {
  useDariusStore.setState({ view: "create", activeProjectId: "project-a", projects: [], knownJobIds: [], inspectorOpen: false });
  useWindowStore.setState({ scopes: {} });
  window.history.replaceState({}, "", "/");
});
afterEach(() => vi.restoreAllMocks());

describe("Project desktop", () => {
  it("opens a project onto its canvas with Darius always present", async () => {
    show();
    expect(screen.getByTestId("canvas")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Darius" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start voice conversation" })).toBeInTheDocument();
    expect(await screen.findAllByRole("textbox", { name: "Message Darius" })).toHaveLength(1);
  });

  it("keeps several windows open at once and exactly one composer through project changes", async () => {
    const user = userEvent.setup();
    show();
    for (const project of ["project-b", "project-c", "project-a"]) {
      act(() => useDariusStore.getState().setActiveProject(project));
      for (const app of ["Library", "World map", "Edit", "Chat"]) {
        await user.click(rail().getByRole("button", { name: app === "World map" ? "World map" : app }));
        expect(screen.getByRole("region", { name: `${app} window` })).toBeVisible();
        expect(screen.getAllByRole("textbox", { name: "Message Darius" })).toHaveLength(1);
      }
      expect(screen.getByText("Library content")).toBeInTheDocument();
      expect(screen.getByText("Map content")).toBeInTheDocument();
      expect(screen.getByTestId("canvas")).toBeInTheDocument();
    }
  });

  it("minimizes to the rail, keeps the window mounted, and Canvas reveals the boards", async () => {
    const user = userEvent.setup();
    show();
    await user.click(rail().getByRole("button", { name: "Library" }));
    await user.click(screen.getByRole("button", { name: "Minimize Library" }));
    expect(screen.queryByRole("region", { name: "Library window" })).toBeNull();
    expect(screen.getByText("Library content")).not.toBeVisible();
    await user.click(rail().getByRole("button", { name: "Library" }));
    expect(screen.getByRole("region", { name: "Library window" })).toBeVisible();
    await user.click(rail().getByRole("button", { name: "Chat" }));
    await user.click(rail().getByRole("button", { name: "Canvas" }));
    expect(screen.queryByRole("region", { name: /window$/ })).toBeNull();
    expect(useDariusStore.getState().view).toBe("create");
  });

  it("closing the focused window names the next one in the URL", async () => {
    const user = userEvent.setup();
    show();
    await user.click(rail().getByRole("button", { name: "World map" }));
    await user.click(rail().getByRole("button", { name: "Chat" }));
    expect(new URLSearchParams(location.search).get("app")).toBe("talk");
    await user.click(screen.getByRole("button", { name: "Close Chat" }));
    expect(useDariusStore.getState().view).toBe("map");
    expect(new URLSearchParams(location.search).get("app")).toBe("map");
  });

  it.each<[ViewId, string]>([["talk", "Chat"], ["map", "World map"], ["edit", "Edit"]])("restores the %s view as an open window without React warnings", (view, title) => {
    useDariusStore.setState({ view });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    show();
    expect(screen.getByRole("region", { name: `${title} window` })).toBeVisible();
    expect(screen.getByTestId("canvas")).toBeInTheDocument();
    expect(errors).not.toHaveBeenCalled();
  });

  it("shows the launcher at home", async () => {
    useDariusStore.setState({ view: "home" });
    show();
    expect(screen.getByTestId("launcher")).toBeInTheDocument();
    expect(screen.queryByTestId("canvas")).toBeNull();
    expect(await screen.findAllByRole("textbox", { name: "Message Darius" })).toHaveLength(1);
  });
});

it("uses the project history without launching a read per remembered job", () => {
  useDariusStore.setState({ knownJobIds: Array.from({ length: 50 }, (_, i) => `past-${i}`) });
  show();
  expect(useKnownJobs).not.toHaveBeenCalled();
  expect(screen.getByRole("main")).toHaveClass("space-desktop");
});
