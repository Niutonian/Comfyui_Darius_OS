"use client";
import { useEffect, useRef, useState } from "react";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { api } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import { ConversationImages } from "./assistant-references";
import type { AssistantContext as Context, Character, Scene, Shot } from "@/lib/types";

export function AssistantContext({ projectId, busy, initiallyOpen = false, onSaved }: { projectId: string; busy: boolean; initiallyOpen?: boolean; onSaved?: () => void }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [value, setValue] = useState<Context | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [shots, setShots] = useState<Shot[]>([]);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const baseline = useRef("");
  const current = useRef(value);
  useEffect(() => { current.current = value; }, [value]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void Promise.all([api.assistantContext(projectId), api.characters(projectId), api.scenes(projectId)]).then(([memory, people, places]) => {
      if (!cancelled) { baseline.current = JSON.stringify(memory); setValue(memory); setCharacters(people); setScenes(places); }
    }).catch((error: Error) => { if (!cancelled) setStatus(error.message); });
    return () => { cancelled = true; };
  }, [open, projectId]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let request = 0;
    const unsubscribe = subscribeProjectRefresh(projectId, ({ full, types }) => {
      if (!full && !types.some((type) => /^(assistant\.context_updated|character\.|scene\.|shot\.)/.test(type))) return;
      const before = JSON.stringify(current.current);
      const serial = ++request;
      void Promise.all([api.assistantContext(projectId), api.characters(projectId), api.scenes(projectId), current.current?.scene_id ? api.shots(current.current.scene_id) : Promise.resolve([])]).then(([memory, people, places, shots]) => {
        if (cancelled || serial !== request) return;
        setCharacters(people); setScenes(places); setShots(shots);
        if (JSON.stringify(memory) === baseline.current) return;
        if (before !== baseline.current || JSON.stringify(current.current) !== before) {
          setStatus("Project context changed on another device. Your unsaved edits are kept; close and reopen context to load the saved version, or save your changes explicitly.");
          return;
        }
        baseline.current = JSON.stringify(memory); setValue(memory);
      }).catch(() => {});
    });
    return () => { cancelled = true; unsubscribe(); };
  }, [open, projectId]);
  useEffect(() => {
    let cancelled = false;
    if (value?.scene_id) void api.shots(value.scene_id).then((items) => { if (!cancelled) setShots(items); }).catch(() => { if (!cancelled) setStatus("Could not load shots for this scene. Close and reopen context to retry."); });
    return () => { cancelled = true; };
  }, [value?.scene_id]);
  async function save() {
    if (!value) return; setSaving(true); setStatus("");
    try { const saved = await api.saveAssistantContext(projectId, value); baseline.current = JSON.stringify(saved); setValue(saved); setStatus("Saved for future messages in this project."); onSaved?.(); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not save context."); }
    finally { setSaving(false); }
  }
  return <details className="assistant-context" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}><summary>Project context</summary>
    <p>Keep instructions and references for future conversations in this project. New message attachments take priority.</p>
    {value ? <fieldset disabled={busy || saving}><label>Project notes<textarea value={value.notes} maxLength={6000} rows={3} onChange={(event) => setValue({ ...value, notes: event.target.value })} /></label>
      <div className="context-records"><label>Character<select value={value.character_id ?? ""} onChange={(event) => setValue({ ...value, character_id: event.target.value || null })}><option value="">No active character</option>{characters.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Scene<select value={value.scene_id ?? ""} onChange={(event) => setValue({ ...value, scene_id: event.target.value || null, shot_id: null })}><option value="">No active scene</option>{scenes.map((item) => <option key={item.id} value={item.id}>{item.number} · {item.title}</option>)}</select></label>
      <label>Shot<select value={value.shot_id ?? ""} onChange={(event) => setValue({ ...value, shot_id: event.target.value || null })}><option value="">No active shot</option>{shots.filter(item => item.scene_id === value.scene_id).map((item) => <option key={item.id} value={item.id}>Shot {item.number} · {item.description.slice(0, 60)}</option>)}</select></label></div>
      <div className="control-row"><button type="button" className="secondary-button" onClick={() => setValue({ ...value, reference_asset_ids: useDariusStore.getState().referenceAssetIds.slice(0, 4) })}>Pin selected project images</button><button type="button" className="secondary-button" onClick={() => setValue({ ...value, reference_asset_ids: [] })}>Clear pinned images</button></div>
      <small>{value.reference_asset_ids.length} pinned image(s){value.reference_asset_ids.length ? ` · ${value.reference_asset_ids.map((id) => id.slice(0, 8)).join(", ")}` : ""}</small>
      <button type="button" className="primary-button" onClick={() => void save()}>{saving ? "Saving…" : "Save context"}</button></fieldset> : <p>Loading project context…</p>}
    {value?.reference_asset_ids.length ? <ConversationImages ids={value.reference_asset_ids} /> : null}
    <p role="status">{status}</p></details>;
}
