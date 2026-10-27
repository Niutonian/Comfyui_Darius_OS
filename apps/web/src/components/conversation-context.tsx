"use client";
/* eslint-disable @next/next/no-img-element -- immutable project media */
import { useEffect, useState } from "react";
import { Focus, SlidersHorizontal, X } from "lucide-react";
import { api } from "@/lib/api-client";
import { assetName } from "@/lib/chat-labels";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { useDariusStore } from "@/lib/store";
import type { AssistantContext as Context, Asset, Character, Scene, Shot } from "@/lib/types";
import { AssistantContext } from "./assistant-context";

export function ConversationContext({ projectId, busy, lastIntent }: { projectId: string; busy: boolean; lastIntent?: unknown }) {
  const [memory, setMemory] = useState<Context | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [shot, setShot] = useState<Shot | null>(null);
  const [references, setReferences] = useState<Asset[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const selected = useDariusStore(state => state.referenceAssetIds);
  const activeProject = useDariusStore(state => state.activeProjectId);
  const projectName = useDariusStore(state => state.projects.find(item => item.id === projectId)?.name ?? "Current project");
  useEffect(() => {
    let cancelled = false, serial = 0;
    async function load() {
      const request = ++serial;
      try {
        const [value, people, places] = await Promise.all([api.assistantContext(projectId), api.characters(projectId), api.scenes(projectId)]);
        const shots = value.scene_id && value.shot_id ? await api.shots(value.scene_id) : [];
        if (cancelled || request !== serial) return;
        setMemory(value); setCharacters(people); setScenes(places); setShot(shots.find(item => item.id === value.shot_id) ?? null); setError("");
      } catch { if (!cancelled && request === serial) setError("Context could not be refreshed. Open Project context to check it before generating."); }
    }
    void load();
    const unsubscribe = subscribeProjectRefresh(projectId, ({ full, types }) => {
      if (full || types.some(type => /^(assistant\.context_updated|character\.|scene\.|shot\.)/.test(type))) void load();
    });
    return () => { cancelled = true; unsubscribe(); };
  }, [projectId, refresh]);
  const localIds = activeProject === projectId ? selected : [];
  const ids = localIds.length ? localIds : memory?.reference_asset_ids ?? [];
  const referenceKey = ids.join("|");
  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled(referenceKey ? referenceKey.split("|").map(id => api.asset(id)) : []).then(items => {
      if (!cancelled) setReferences(items.flatMap(item => item.status === "fulfilled" && item.value.project_id === projectId && item.value.kind === "image" ? [item.value] : []));
    });
    return () => { cancelled = true; };
  }, [projectId, referenceKey]);
  const character = characters.find(item => item.id === memory?.character_id);
  const scene = scenes.find(item => item.id === memory?.scene_id);
  async function clearFocus() {
    setSaving(true); setError("");
    try {
      // Read the latest record so clearing focus cannot reset workflow defaults
      // or overwrite notes changed on a different device.
      const latest = await api.assistantContext(projectId);
      const saved = await api.saveAssistantContext(projectId, { ...latest, character_id: null, scene_id: null, shot_id: null, reference_asset_ids: [] });
      setMemory(saved); setShot(null);
      const store = useDariusStore.getState();
      if (store.activeProjectId === projectId) for (const id of store.referenceAssetIds) store.removeReferenceAsset(id);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not clear focus. Your context is unchanged."); }
    finally { setSaving(false); }
  }
  const intent = lastIntent && typeof lastIntent === "object" ? lastIntent as { scene?: { title?: string; number?: number }; shot?: { number?: number }; subject_ids?: string[] } : null;
  const lastLabels = intent ? [characters.filter(item => intent.subject_ids?.includes(item.id)).map(item => item.name).join(", "), intent.scene?.title, intent.shot ? `Shot ${intent.shot.number}` : ""].filter(Boolean) : [];
  return <section className="conversation-context" aria-label="Active conversation context">
    <div className="conversation-context-heading"><span><Focus size={15} aria-hidden /><strong>{projectName}</strong><small>Next message</small></span><button className="text-button" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}><SlidersHorizontal size={14} />{open ? "Close context" : "Change context"}</button></div>
    <div className="context-focus-chips" aria-label="Saved project focus">
      {!memory ? <small>{error ? "Saved focus unavailable" : "Loading saved focus…"}</small> : <>
        {character ? <span>{character.name}</span> : null}{scene ? <span>Scene {scene.number} · {scene.title}</span> : null}{shot ? <span>Shot {shot.number}</span> : null}
        {!character && !scene && !shot ? <small>No saved focus · use the conversation</small> : null}
        {memory.notes ? <span title={memory.notes}>Project notes active</span> : null}
        {ids.length ? <span>{ids.length} {localIds.length ? "selected" : "pinned"} reference{ids.length === 1 ? "" : "s"}</span> : <small>No selected references</small>}
      </>}
    </div>
    {ids.length ? <div className="context-reference-thumbnails" aria-label="References for the next message">{references.filter(asset => ids.includes(asset.id)).map(asset => <span key={asset.id} title={assetName(asset)}><img src={api.assetContentUrl(asset.id)} alt={assetName(asset)} loading="lazy" /><small>{assetName(asset)}</small>{localIds.includes(asset.id) ? <button type="button" className="icon-button" aria-label={`Remove selected reference ${assetName(asset)}`} disabled={busy || saving} onClick={() => useDariusStore.getState().removeReferenceAsset(asset.id)}><X size={12} /></button> : null}</span>)}</div> : null}
    {lastLabels.length ? <small className="last-request-context">Last request used: {lastLabels.join(" · ")}</small> : null}
    {open ? <div className="conversation-context-editor"><p>Saved focus guides future messages. Explicit instructions and attachments take priority. Clearing focus keeps your notes and chat history.</p><AssistantContext key={projectId} projectId={projectId} busy={busy || saving} initiallyOpen onSaved={() => setRefresh(value => value + 1)} /><button className="secondary-button" disabled={busy || saving || !memory} type="button" onClick={() => void clearFocus()}>{saving ? "Clearing…" : "Clear saved focus & references"}</button></div> : null}
    {error ? <small role="status" className="form-error">{error}</small> : null}
  </section>;
}
