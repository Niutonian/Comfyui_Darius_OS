import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { DiagnosticConsole, diagnosticReport, type Diagnostics } from "./diagnostic-console";

const sample: Diagnostics = { generated_at: "2026-10-08T12:00:00Z", project_id: "own", provider: "llamacpp", model: "qwen",
  failures: [{ id: "failed", time: "now", source: "model", detail: "Context check /tokenize timed out" }],
  checks: [{ name: "ComfyUI", state: "ready", detail: "0 running" }],
  logs: { backend: "backend activity", comfyui: "GPU model loaded", jobs: "worker activity" }, activities: [] };

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(sample))));
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><DiagnosticConsole projectId="own" /></QueryClientProvider>);
}

it("requires unlock, sends credentials only in headers, and opens beside its launcher", async () => {
  mount();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open diagnostic console" }));
  expect(screen.getByRole("dialog")).toHaveAttribute("open");
  fireEvent.change(screen.getByLabelText("Local access code"), { target: { value: "local-private-code" } });
  fireEvent.click(screen.getByRole("button", { name: "Unlock console" }));
  await screen.findByText("backend activity");
  const [url, options] = vi.mocked(fetch).mock.calls[0];
  expect(String(url)).toContain("project_id=own");
  expect(String(url)).not.toContain("local-private-code");
  expect(options?.headers).toEqual({ "X-Darius-Diagnostics-Key": "local-private-code" });
  fireEvent.click(screen.getByRole("tab", { name: "ComfyUI" }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("GPU model loaded");
  fireEvent.click(screen.getByRole("button", { name: "Close diagnostic console" }));
  await waitFor(() => expect(screen.getByRole("dialog", { hidden: true })).not.toHaveAttribute("open"));
});

it("reports include failure and service evidence but no stored access code", () => {
  sessionStorage.setItem("darius-diagnostics-key", "private-access-code");
  const report = diagnosticReport(sample);
  expect(report).toContain("/tokenize timed out");
  expect(report).toContain("GPU model loaded");
  expect(report).toContain("llamacpp / qwen");
  expect(report).not.toContain("private-access-code");
});

it("shows saved failures after authentication and supports dismissing notification", async () => {
  sessionStorage.setItem("darius-diagnostics-key", "code");
  mount();
  await screen.findByText("Local task needs attention");
  fireEvent.click(screen.getByRole("button", { name: "Dismiss failure notification" }));
  expect(screen.queryByText("Local task needs attention")).not.toBeInTheDocument();
});

it("notifies when a local service goes offline", async () => {
  sessionStorage.setItem("darius-diagnostics-key", "code");
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ...sample, failures: [],
    checks: [{ name: "ComfyUI", state: "offline", detail: "Connection refused" }] })));
  mount();
  await screen.findByText("ComfyUI is offline");
});

it("uses the replacement code after a failed unlock without reusing the rejected request", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(new Response('{}', { status: 401 }))
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify(sample))));
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open diagnostic console' }));
  fireEvent.change(screen.getByLabelText('Local access code'), { target: { value: 'old-code' } });
  fireEvent.click(screen.getByRole('button', { name: 'Unlock console' }));
  await screen.findByText('Incorrect access code. Unlock the console again.');
  fireEvent.change(screen.getByLabelText('Local access code'), { target: { value: 'replacement-code' } });
  fireEvent.click(screen.getByRole('button', { name: 'Unlock console' }));
  await screen.findByText('backend activity');
  expect(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers).toEqual({ 'X-Darius-Diagnostics-Key': 'replacement-code' });
});
