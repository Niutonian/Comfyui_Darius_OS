"use client";

import { Check, KeyRound, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { queryKeys, useLlmSettings } from "@/lib/queries";
import type { LlmProviderId } from "@/lib/types";
import { useWorkspaceState } from "@/lib/workspace-session";

const openCodeVisionModels = new Set([
  "muse-spark-1.3-contributor-free",
]);

const thinkingLabels: Record<string, string> = { auto: "Model default", none: "Off", minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Maximum" };

export function LlmSetting({ onStateChange }: { onStateChange?: (state: { dirty: boolean; error: string }) => void } = {}) {
  const client = useQueryClient();
  const setting = useLlmSettings();
  const [draft, setDraft] = useWorkspaceState<{ provider: LlmProviderId; model: string; effort?: string } | null>("settings:model:draft", null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState("");
  const provider = draft?.provider ?? setting.data?.provider ?? "openai";
  const model = draft?.model ?? setting.data?.model ?? "";
  const selected = setting.data?.providers.find((item) => item.id === provider);
  const thinkingLevels = selected?.reasoning_efforts?.[model] ?? ["auto"];
  const requestedEffort = draft?.effort ?? setting.data?.reasoning_effort ?? "auto";
  const effort = thinkingLevels.includes(requestedEffort) ? requestedEffort : "auto";
  const dirty = Boolean(setting.data && (provider !== setting.data.provider || model !== setting.data.model || (provider === "openai" && effort !== (setting.data.reasoning_effort ?? "auto"))));
  useEffect(() => { onStateChange?.({ dirty, error }); }, [dirty, error, onStateChange]);

  function chooseProvider(next: LlmProviderId) {
    const option = setting.data?.providers.find((item) => item.id === next);
    const nextModel = next === setting.data?.provider && option?.models.includes(setting.data.model)
      ? setting.data.model
      : option?.models[0] ?? "";
    setDraft({ provider: next, model: nextModel });
    setSaved(false);
    setError("");
    setRefreshStatus("");
  }

  async function refreshModels() {
    if (provider !== "openai" && provider !== "opencode" && provider !== "ollama") return;
    setRefreshing(true); setError(""); setRefreshStatus(""); setSaved(false);
    try {
      const result = await api.refreshLlmModels(provider);
      client.setQueryData<typeof setting.data>(queryKeys.llmSettings, (current) => current ? {
        ...current, providers: current.providers.map((item) => item.id === result.id ? result : item),
      } : current);
      if (!model && result.models.length) setDraft({ provider, model: result.models[0] });
      const kept = model && !result.models.includes(model) ? " Your current model is no longer listed; choose another model before saving." : " Your saved selection has not changed.";
      setRefreshStatus(`Refreshed ${result.models.length} ${provider === "opencode" ? "free " : provider === "ollama" ? "installed " : ""}models.${kept}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh models. Your current selection was kept.");
    } finally { setRefreshing(false); }
  }

  async function save() {
    if (!model) return;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const result = await api.setLlmSettings(provider, model, provider === "openai" ? effort : undefined);
      client.setQueryData(queryKeys.llmSettings, result);
      void client.invalidateQueries({ queryKey: queryKeys.health });
      setDraft(null);
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the AI model");
    } finally {
      setSaving(false);
    }
  }

  if (!setting.data) {
    return <div className="llm-setting"><p className="settings-body">{setting.isError ? "Could not load AI model settings." : "Loading AI model settings…"}</p>{setting.isError ? <button className="secondary-button" type="button" onClick={() => void setting.refetch()}>Retry</button> : null}</div>;
  }

  return <div className="llm-setting">
    <div className="llm-provider-options" role="radiogroup" aria-label="AI provider">
      {setting.data.providers.map((option) => <button
        aria-checked={provider === option.id}
        className={`llm-provider-option ${provider === option.id ? "selected" : ""}`}
        disabled={saving || refreshing}
        key={option.id}
        onClick={() => chooseProvider(option.id)}
        role="radio"
        type="button"
      >
        <span className="llm-provider-mark">{option.label.slice(0, 1)}</span>
        <span><strong>{option.label}</strong><small>{option.id === "ollama" || option.id === "llamacpp" ? "Local server" : option.id === "opencode" ? "Free cloud models" : option.credential_configured ? "Server key configured" : "Server key missing"}</small></span>
        {provider === option.id ? <Check aria-label="Selected" size={16} /> : null}
      </button>)}
    </div>
    <div className="llm-model-heading"><label htmlFor="llm-model">Model</label>{provider === "openai" || provider === "opencode" || provider === "ollama" ? <button className="secondary-button" type="button" disabled={saving || refreshing || (provider === "openai" && !selected?.credential_configured)} onClick={() => void refreshModels()}><RefreshCw size={14} className={refreshing ? "spin" : undefined} />{refreshing ? "Refreshing…" : provider === "opencode" ? "Refresh free models" : "Refresh models"}</button> : null}</div>
    <div className="llm-model-field">
      <select id="llm-model" value={model} disabled={saving || refreshing || !selected?.models.length} onChange={(event) => { const next = event.target.value; setDraft({ provider, model: next, effort: selected?.reasoning_efforts?.[next]?.includes(effort) ? effort : "auto" }); setSaved(false); setError(""); setRefreshStatus(""); }}>
        {model && !selected?.models.includes(model) ? <option value={model} disabled>{model} · not in latest list</option> : null}
        {!selected?.models.length ? <option value="">No server model configured</option> : null}
        {selected?.models.map((item) => <option key={item} value={item}>{item}{provider === "opencode" && (selected.model_capabilities?.[item]?.vision ?? openCodeVisionModels.has(item)) ? " · vision" : ""}{selected.model_capabilities?.[item]?.tools ? " · tools" : ""}</option>)}
      </select>
    </div>
    {provider === "openai" ? <div className="llm-model-field">
      <label htmlFor="llm-thinking">Thinking level</label>
      <select id="llm-thinking" value={effort} disabled={saving || refreshing || thinkingLevels.length <= 1} onChange={(event) => { setDraft({ provider, model, effort: event.target.value }); setSaved(false); setError(""); }}>
        {thinkingLevels.map((level) => <option key={level} value={level}>{thinkingLabels[level] ?? level}</option>)}
      </select>
      <small className="settings-body">{thinkingLevels.length > 1 ? "Higher levels can take longer and use more tokens. Model default leaves the choice to OpenAI." : "This model uses its default thinking behavior; configurable levels have not been verified."}</small>
    </div> : null}
    {!selected?.models.length ? <p className="settings-body">{provider === "openai" ? "Configure the OpenAI API key on the server, then refresh the model list." : provider === "opencode" ? "No free models are listed. Refresh the catalog to try again." : provider === "ollama" ? "No installed Ollama models were found. Download a model on the Darius server, then refresh." : "No local server model is configured."}</p> : null}
    {provider === "ollama" ? <p className="settings-body">Lists models downloaded on the Darius server. Refresh does not download models or load them into GPU memory. Chat and tool support depend on the selected model.</p> : null}
    {provider === "openai" ? <p className="settings-body">Lists text-model candidates available to your server API key. Image generation and live voice use their own model settings.</p> : null}
    <div className="llm-setting-footer">
      <span className={`llm-key-state ${selected?.credential_configured ? "ready" : ""}`}><KeyRound size={13} />{provider === "ollama" || provider === "llamacpp" ? "Local server configured" : provider === "opencode" ? "Free tier · no key required" : selected?.credential_configured ? "Credential available on server" : "Add this provider’s API key to the server .env"}</span>
      <button className="secondary-button" disabled={!dirty || !model || saving || refreshing || !selected?.models.includes(model)} onClick={() => void save()} type="button">{saving ? "Saving…" : "Save AI model"}</button>
    </div>
    <p className="settings-body">Applies to new Talk replies. GPT-Live voice keeps its independent OpenAI model and key.</p>
    {saved ? <p className="llm-save-status success-note" role="status">AI model saved. New replies will use {setting.data.provider} / {setting.data.model}.</p> : null}
    {refreshStatus ? <p className="llm-save-status" role="status">{refreshStatus}</p> : null}
    {error ? <p className="llm-save-status form-error" role="alert">{error}</p> : null}
  </div>;
}
