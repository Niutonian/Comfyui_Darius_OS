"use client";

import { ArrowLeft, BrainCircuit, Check, Layers3, Moon, Server, Sun, Volume2, WandSparkles } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useWorkspaceState } from "@/lib/workspace-session";
import { useDariusStore } from "@/lib/store";
import { useHealth } from "@/lib/queries";
import type { ThemeMode } from "@/lib/types";
import { LlmSetting } from "./llm-setting";
import { TranscriptionSetting } from "./transcription-setting";
import { VoicePreferences } from "./voice-preferences";
import { TrustedWorkflows } from "./trusted-workflows";

export function SettingsView() {
  const [category, setCategory] = useWorkspaceState("settings:category", "workflows");
  const [mobilePane, setMobilePane] = useState(false);
  const categoryNav = useRef<HTMLElement>(null);
  const openCategory = (id: string) => { setCategory(id); setMobilePane(true); requestAnimationFrame(() => { const back = document.querySelector<HTMLButtonElement>(".settings-back"); if (back?.getClientRects().length) back.focus({ preventScroll: true }); }); };
  const [pending, setPending] = useState<Record<string, { dirty: boolean; error: string }>>({});
  const report = useCallback((key: string, state: { dirty: boolean; error: string }) => setPending(current => current[key]?.dirty === state.dirty && current[key]?.error === state.error ? current : { ...current, [key]: state }), []);
  const reportGlobal = useCallback((state: { dirty: boolean; error: string }) => report("Global workflows", state), [report]);
  const reportProject = useCallback((state: { dirty: boolean; error: string }) => report("Project workflows", state), [report]);
  const reportModel = useCallback((state: { dirty: boolean; error: string }) => report("AI model", state), [report]);
  const categories = [
    { id: "workflows", label: "Workflows", scope: "Global defaults & project overrides", icon: Layers3 },
    { id: "appearance", label: "Appearance", scope: "This browser", icon: Sun },
    { id: "model", label: "AI model", scope: "Darius server", icon: BrainCircuit },
    { id: "services", label: "Services", scope: "Darius server · status", icon: Server },
    { id: "voice", label: "Voice", scope: "Browser preferences & local services", icon: Volume2 },
    { id: "execution", label: "Execution", scope: "Active project", icon: WandSparkles },
  ];
  const health = useHealth();
  const projectId = useDariusStore((state) => state.activeProjectId);
  const projectName = useDariusStore((state) => state.projects.find((project) => project.id === state.activeProjectId)?.name);
  const theme = useDariusStore((state) => state.theme);
  const setTheme = useDariusStore((state) => state.setTheme);
  const options: { id: ThemeMode; label: string; description: string; icon: typeof Sun }[] = [
    { id: "light", label: "Light", description: "Soft sage canvas for daytime work.", icon: Sun },
    { id: "dark", label: "Dark", description: "Low-glare charcoal canvas for focused sessions.", icon: Moon },
  ];
  return <section className={`settings-view view settings-focused ${mobilePane ? "settings-pane-open" : ""}`} aria-labelledby="settings-title">
    <header className="view-heading settings-heading">
      <div><span className="eyebrow">Darius / preferences</span><h1 id="settings-title">Settings</h1><p>Shape how Darius feels, speaks, and works on this device.</p></div>
    </header>
    {Object.entries(pending).some(([, state]) => state.dirty || state.error) ? <div className="settings-pending" role="status">{Object.entries(pending).filter(([, state]) => state.dirty || state.error).map(([name, state]) => <button className="text-button" key={name} type="button" onClick={() => { setCategory(name === "AI model" ? "model" : "workflows"); setMobilePane(true); }}>{name}: {state.error ? state.error : "unsaved changes"}</button>)}</div> : null}
    <div className="settings-layout">
    <nav className="settings-categories" aria-label="Preference categories" ref={categoryNav}>{categories.map(({ id, label, scope, icon: Icon }) => <button key={id} aria-current={category === id ? "page" : undefined} onClick={() => openCategory(id)} type="button"><Icon size={18} /><span><strong>{label}</strong><small>{scope}</small></span></button>)}</nav>
    <div className="settings-preferences">
    <button className="text-button settings-back" type="button" onClick={() => { setMobilePane(false); requestAnimationFrame(() => categoryNav.current?.querySelector<HTMLButtonElement>('[aria-current="page"]')?.focus()); }}><ArrowLeft size={18} />All settings</button>
    <p className="settings-scope" role="status">{categories.find(item => item.id === category)?.scope}{category === "workflows" || category === "execution" ? ` · ${projectName ?? "No active project"}` : ""}</p>
    <div className="settings-grid">
      <article hidden={category !== "workflows"} className="settings-card settings-trusted-workflows"><TrustedWorkflows scope="global" onStateChange={reportGlobal} /></article>
      {projectId ? <article hidden={category !== "workflows"} className="settings-card settings-trusted-workflows"><TrustedWorkflows key={projectId} projectId={projectId} onStateChange={reportProject} /></article> : null}
      <article hidden={category !== "appearance"} className="settings-card">
        <div className="settings-card-heading"><span className="settings-icon"><Sun size={17} /></span><div><h2>Appearance</h2><p>Choose the atmosphere for your creative space.</p></div></div>
        <div className="theme-options" role="radiogroup" aria-label="Theme">
          {options.map(({ id, label, description, icon: Icon }) => <button className={`theme-option ${theme === id ? "selected" : ""}`} aria-checked={theme === id} key={id} onClick={() => setTheme(id)} role="radio" type="button"><span className={`theme-preview theme-preview-${id}`}><Icon size={18} /></span><span><strong>{label}</strong><small>{description}</small></span>{theme === id ? <Check size={16} aria-label="Selected" /> : null}</button>)}
        </div>
      </article>
      <article hidden={category !== "model"} className="settings-card settings-llm-card">
        <div className="settings-card-heading"><span className="settings-icon"><BrainCircuit size={17} /></span><div><h2>AI model</h2><p>Choose the provider and model Darius uses for new Talk replies.</p></div></div>
        <LlmSetting onStateChange={reportModel} />
      </article>
      <article hidden={category !== "services"} className="settings-card settings-status-card">
        <div className="settings-card-heading"><span className="settings-icon"><Check size={17} /></span><div><h2>Services</h2><p>See which local and optional providers are ready.</p></div></div>
        <div className="service-status-list">
          {Object.entries(health.data?.components ?? {}).filter(([key]) => key !== "database").map(([key, value]) => <div className="service-status" key={key}><span className={value.ready ? "service-dot ready" : "service-dot"} /><strong>{key.replaceAll("_", " ")}</strong><small>{value.ready ? "Ready" : value.configured ? "Configured · unavailable" : "Not configured"}</small></div>)}
          {!health.data ? <p className="muted">Checking local services…</p> : null}
        </div>
      </article>
      <article hidden={category !== "voice"} className="settings-card">
        <div className="settings-card-heading"><span className="settings-icon"><Volume2 size={17} /></span><div><h2>Voice</h2><p>Manage how Darius listens and responds.</p></div></div>
        <div className="settings-note"><strong>Transcription</strong><span>Vosk still detects the wake word and the end of a turn. The engine below writes that turn into the chat.</span></div>
        <TranscriptionSetting />
        <VoicePreferences />
        <div className="settings-note"><strong>Local voice</strong><span>Wake-word detection, transcription, and OmniVoice playback stay on this PC. Start listening from Talk.</span></div>
        <div className="settings-note"><strong>GPT-Live 1</strong><span>Optional full-duplex cloud voice. Sessions use your server API key and are billed by duration.</span></div>
      </article>
      <article hidden={category !== "execution"} className="settings-card">
        <div className="settings-card-heading"><span className="settings-icon"><WandSparkles size={17} /></span><div><h2>Chat and rendering</h2><p>Ideas in chat. Generation on boards.</p></div></div>
        <div className="settings-note"><strong>Creative helper</strong><span>Voice and text chat develop concepts and prompts. Use in board lets you review and apply a prompt. Generate on the board starts the render.</span></div>
      </article>
    </div>
    </div>
    </div>
  </section>;
}
