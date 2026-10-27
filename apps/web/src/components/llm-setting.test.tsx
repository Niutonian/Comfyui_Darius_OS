import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderView, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { LlmSettings } from "@/lib/types";
import { LlmSetting } from "./llm-setting";

const openaiSettings: LlmSettings = {
  provider: "openai",
  model: "gpt-test",
  ready: true,
  credential_configured: true,
  source: "environment",
  providers: [
    { id: "openai", label: "OpenAI", models: ["gpt-test"], credential_configured: true },
    { id: "deepseek", label: "DeepSeek", models: ["deepseek-flash", "deepseek-v4-pro"], credential_configured: false },
    { id: "ollama", label: "Ollama (local)", models: ["qwen3:14b"], credential_configured: true },
    { id: "llamacpp", label: "llama.cpp (local)", models: ["qwen-test"], credential_configured: true },
  ],
};

function render(element: ReactElement) {
  return renderView(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{element}</QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe("LLM setting", () => {
  it("refreshes installed Ollama models and saves a newly downloaded model only on request", async () => {
    const settings: LlmSettings = { ...openaiSettings, provider: "ollama", model: "qwen3:14b" };
    vi.spyOn(api, "llmSettings").mockResolvedValue(settings);
    const option = { id: "ollama" as const, label: "Ollama (local)", models: ["qwen3:14b", "local-new:9b"], credential_configured: true };
    const refresh = vi.spyOn(api, "refreshLlmModels").mockResolvedValue(option);
    const save = vi.spyOn(api, "setLlmSettings").mockResolvedValue({ ...settings, model: "local-new:9b", source: "saved" });
    const user = userEvent.setup();
    render(<LlmSetting />);
    await user.click(await screen.findByRole("button", { name: "Refresh models" }));
    expect(refresh).toHaveBeenCalledWith("ollama");
    expect(await screen.findByRole("status")).toHaveTextContent("Refreshed 2 installed models");
    const model = screen.getByRole("combobox", { name: "Model" });
    expect(model).toHaveValue("qwen3:14b");
    expect(save).not.toHaveBeenCalled();
    await user.selectOptions(model, "local-new:9b");
    await user.click(screen.getByRole("button", { name: "Save AI model" }));
    expect(save).toHaveBeenCalledWith("ollama", "local-new:9b", undefined);
    expect(await screen.findByRole("status")).toHaveTextContent("ollama / local-new:9b");
  });

  it("keeps the current Ollama choice and list when refresh fails", async () => {
    vi.spyOn(api, "llmSettings").mockResolvedValue({ ...openaiSettings, provider: "ollama", model: "qwen3:14b" });
    vi.spyOn(api, "refreshLlmModels").mockRejectedValue(new Error("Ollama is offline. Your current selection was kept."));
    const user = userEvent.setup();
    render(<LlmSetting />);
    await user.click(await screen.findByRole("button", { name: "Refresh models" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ollama is offline");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("qwen3:14b");
    expect(screen.getByRole("button", { name: "Refresh models" })).toBeEnabled();
  });

  it("explains an empty installed catalog without changing the saved selection", async () => {
    vi.spyOn(api, "llmSettings").mockResolvedValue({ ...openaiSettings, provider: "ollama", model: "qwen3:14b" });
    vi.spyOn(api, "refreshLlmModels").mockResolvedValue({ id: "ollama", label: "Ollama (local)", models: [], credential_configured: true });
    const user = userEvent.setup();
    render(<LlmSetting />);
    await user.click(await screen.findByRole("button", { name: "Refresh models" }));
    expect(await screen.findByText(/No installed Ollama models were found/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("qwen3:14b");
    expect(screen.getByRole("button", { name: "Save AI model" })).toBeDisabled();
  });

  it("selects and persists a provider and model without exposing key inputs", async () => {
    vi.spyOn(api, "llmSettings").mockResolvedValue(openaiSettings);
    const saved: LlmSettings = {
      ...openaiSettings,
      provider: "deepseek",
      model: "deepseek-v4-pro",
      ready: false,
      credential_configured: false,
      source: "saved",
    };
    const save = vi.spyOn(api, "setLlmSettings").mockResolvedValue(saved);
    const user = userEvent.setup();
    render(<LlmSetting />);

    expect(await screen.findByRole("radio", { name: /OpenAI Server key configured/i })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /DeepSeek Server key missing/i }));
    const model = screen.getByRole("combobox", { name: "Model" });
    expect(model).toHaveValue("deepseek-flash");
    await user.selectOptions(model, "deepseek-v4-pro");
    await user.click(screen.getByRole("button", { name: "Save AI model" }));

    expect(save).toHaveBeenCalledWith("deepseek", "deepseek-v4-pro", undefined);
    expect(await screen.findByRole("status")).toHaveTextContent("deepseek / deepseek-v4-pro");
  });

  it("keeps the draft and explains a failed save", async () => {
    vi.spyOn(api, "llmSettings").mockResolvedValue(openaiSettings);
    vi.spyOn(api, "setLlmSettings").mockRejectedValue(new Error("API unavailable"));
    const user = userEvent.setup();
    render(<LlmSetting />);

    await user.click(await screen.findByRole("radio", { name: /DeepSeek/i }));
    await user.click(screen.getByRole("button", { name: "Save AI model" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("API unavailable");
    await waitFor(() => expect(screen.getByRole("radio", { name: /DeepSeek/i })).toHaveAttribute("aria-checked", "true"));
  });
});
