import { render as renderView, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import { LocalRenderSetting } from "./local-render-setting";

afterEach(() => vi.restoreAllMocks());
function render(element: ReactElement) {
  return renderView(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{element}</QueryClientProvider>);
}

describe("local rendering permission", () => {
  it("shows the current project's mode after switching projects", async () => {
    vi.spyOn(api, "localRendering").mockImplementation(async (id) => ({ enabled: id === "project-a" }));
    const save = vi.spyOn(api, "setLocalRendering").mockResolvedValue({ enabled: true });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderView(<QueryClientProvider client={client}><LocalRenderSetting projectId="project-a" compact /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Full auto" })).toHaveAttribute("aria-pressed", "true"));
    view.rerender(<QueryClientProvider client={client}><LocalRenderSetting projectId="project-b" compact /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Manual" })).toHaveAttribute("aria-pressed", "true"));
    await userEvent.click(screen.getByRole("button", { name: "Full auto" }));
    expect(save).toHaveBeenCalledWith("project-b", true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Full auto" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("restores the project permission and persists turning it off during a reply", async () => {
    vi.spyOn(api, "localRendering").mockResolvedValue({ enabled: true });
    const save = vi.spyOn(api, "setLocalRendering").mockResolvedValue({ enabled: false });
    render(<LocalRenderSetting projectId="project-a" busy />);
    const checkbox = screen.getByRole("checkbox", { name: "Full auto · local rendering" });
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(checkbox).toBeEnabled();
    await userEvent.click(checkbox);
    expect(save).toHaveBeenCalledWith("project-a", false);
    await waitFor(() => expect(checkbox).not.toBeChecked());
  });

  it("keeps the old permission and explains a failed save", async () => {
    vi.spyOn(api, "localRendering").mockResolvedValue({ enabled: false });
    vi.spyOn(api, "setLocalRendering").mockRejectedValue(new Error("API unavailable"));
    render(<LocalRenderSetting projectId="project-b" />);
    const checkbox = screen.getByRole("checkbox");
    await waitFor(() => expect(checkbox).toBeEnabled());
    await userEvent.click(checkbox);
    expect(await screen.findByRole("alert")).toHaveTextContent("API unavailable");
    expect(checkbox).not.toBeChecked();
  });
});
