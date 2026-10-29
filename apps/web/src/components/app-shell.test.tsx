import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDariusStore } from "@/lib/store";
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
}));
vi.mock("./talk-view", () => ({ TalkView: () => <div data-testid="space">Talk content</div> }));
vi.mock("./creative-message", () => ({ CreativeChatWelcome: () => <div data-testid="space">Talk content</div>, CreativeMessage: ({message}: {message: {content: string}}) => <p>{message.content}</p> }));
vi.mock("./create-view", () => ({ CreateView: () => <div data-testid="space">Create content</div> }));
vi.mock("./map-view", () => ({ MapView: () => <div data-testid="space">Map content</div> }));
vi.mock("./edit-view", () => ({ EditView: () => <div data-testid="space">Edit content</div> }));
vi.mock("./composer", () => ({ Composer: () => <textarea aria-label="Message Darius" /> }));
vi.mock("./project-selector", () => ({ ProjectSelector: () => <div>Projects</div> }));
vi.mock("./inspector", () => ({ Inspector: () => null }));
vi.mock("./job-tray", () => ({ JobTray: () => null }));
// Console behavior/auth is covered separately; navigation uses isolated children.
vi.mock("./diagnostic-console", () => ({ DiagnosticConsole: () => <button aria-label="Open diagnostic console">Console</button> }));
vi.mock("./ambient-background", () => ({ AmbientBackground: () => null }));

beforeEach(() => useDariusStore.setState({ view: "talk", activeProjectId: "project-a", projects: [], knownJobIds: [], inspectorOpen: false }));
afterEach(() => vi.restoreAllMocks());

describe("AppShell navigation", () => {
  it("keeps exactly one space and composer through project changes and repeated navigation", async () => {
    const user = userEvent.setup();
    render(<AppShell />);
    for (const project of ["project-b", "project-c", "project-a"]) {
      act(() => useDariusStore.getState().setActiveProject(project));
      for (const label of ["Create", "Map", "Edit", "Talk", "Create", "Talk"]) {
        await user.click(screen.getByRole("button", { name: label }));
        expect(screen.getAllByTestId("space")).toHaveLength(1);
        expect(screen.getByTestId("space")).toHaveTextContent(`${label} content`);
        expect(screen.getAllByRole("textbox", { name: "Message Darius" })).toHaveLength(1);
      }
    }
  });

  it.each<ViewId>(["talk", "create", "map", "edit"])("renders the restored %s view without React key warnings", (view) => {
    useDariusStore.setState({ view });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<AppShell />);
    expect(screen.getAllByTestId("space")).toHaveLength(1);
    expect(errors).not.toHaveBeenCalled();
  });
});


it("uses the project history without launching a read per remembered job", () => {
 useDariusStore.setState({ knownJobIds: Array.from({ length: 50 }, (_, i) => `past-${i}`) });
 render(<AppShell />);
 expect(useKnownJobs).not.toHaveBeenCalled();
 expect(screen.getByRole("main")).toHaveClass("space-talk");
});
