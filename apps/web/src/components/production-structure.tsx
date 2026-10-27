"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Copy, LoaderCircle, MapPin, Pencil, Plus, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys, useCharacters, useScenes, useShots } from "@/lib/queries";
import type { Asset, Character, Scene, Shot } from "@/lib/types";
import { AssetPreview } from "./asset-preview";
import { AssetThumbnailPicker } from "./asset-thumbnail-picker";
import { useWorkspaceState } from "@/lib/workspace-session";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "The record could not be saved.";
}

type EditorState =
  | { kind: "character"; id: string; values: { name: string; description: string; canonical_prompt: string; continuity_notes: string } }
  | { kind: "scene"; id: string; values: { number: string; title: string; description: string; location: string; time_of_day: string; mood: string; status: string } }
  | { kind: "shot"; id: string; values: { number: string; description: string; shot_type: string; camera_motion: string; duration_target: string; dialogue: string; status: string; selected_asset_id: string } };

export function ProductionStructure({ projectId, assets, focus = "characters" }: { projectId: string; assets: Asset[]; focus?: "characters" | "scenes" | "shots" }) {
  const client = useQueryClient();
  const characters = useCharacters(projectId);
  const scenes = useScenes(projectId);
  const [chosenSceneId, setChosenSceneId] = useWorkspaceState(`structure:${projectId}:scene`, "");
  const [newShotAsset, setNewShotAsset] = useState("");
  const [editor, setEditor] = useWorkspaceState<EditorState | null>(`structure:${projectId}:editor`, null);
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);
  const selectedSceneId = scenes.data?.some((scene) => scene.id === chosenSceneId) ? chosenSceneId : (scenes.data?.[0]?.id ?? "");
  const shots = useShots(selectedSceneId || null);
  useEffect(() => {
    document.getElementById(`structure-${focus}`)?.scrollIntoView({ block: "nearest" });
  }, [focus]);

  const characterMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.createCharacter>[1]) => api.createCharacter(projectId, payload),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.characters(projectId) }),
  });
  const sceneMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.createScene>[1]) => api.createScene(projectId, payload),
    onSuccess: (scene) => {
      setChosenSceneId(scene.id);
      void client.invalidateQueries({ queryKey: queryKeys.scenes(projectId) });
    },
  });
  const shotMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.createShot>[1]) => api.createShot(selectedSceneId, payload),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.shots(selectedSceneId) }),
  });
  function editCharacter(character: Character) {
    setEditorError(null);
    setEditor({ kind: "character", id: character.id, values: { name: character.name, description: character.description, canonical_prompt: character.canonical_prompt, continuity_notes: character.continuity_notes } });
  }
  function editScene(scene: Scene) {
    setEditorError(null);
    setEditor({ kind: "scene", id: scene.id, values: { number: String(scene.number), title: scene.title, description: scene.description, location: scene.location, time_of_day: scene.time_of_day, mood: scene.mood, status: scene.status } });
  }
  function editShot(shot: Shot) {
    setEditorError(null);
    setEditor({ kind: "shot", id: shot.id, values: { number: String(shot.number), description: shot.description, shot_type: shot.shot_type, camera_motion: shot.camera_motion, duration_target: String(shot.duration_target), dialogue: shot.dialogue, status: shot.status, selected_asset_id: shot.selected_asset_id ?? "" } });
  }
  function updateEditorField(field: string, value: string) {
    setEditor((current) => current ? { ...current, values: { ...current.values, [field]: value } } as EditorState : current);
  }
  async function saveEditor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    setEditorSaving(true); setEditorError(null);
    try {
      if (editor.kind === "character") {
        const current = characters.data?.find((item) => item.id === editor.id);
        if (!current) return;
        await api.updateCharacter(projectId, editor.id, { ...editor.values, negative_prompt: current.negative_prompt, voice_profile_id: current.voice_profile_id, metadata: current.metadata, approved_reference_asset_ids: current.approved_reference_asset_ids });
        await client.invalidateQueries({ queryKey: queryKeys.characters(projectId) });
      } else if (editor.kind === "scene") {
        const current = scenes.data?.find((item) => item.id === editor.id);
        if (!current) return;
        await api.updateScene(projectId, editor.id, { ...editor.values, number: Number(editor.values.number), screenplay_text: current.screenplay_text, status: editor.values.status as "draft" | "planned" | "ready" | "complete" });
        await client.invalidateQueries({ queryKey: queryKeys.scenes(projectId) });
      } else {
        await api.updateShot(selectedSceneId, editor.id, { ...editor.values, number: Number(editor.values.number), duration_target: Number(editor.values.duration_target), status: editor.values.status as "planned" | "ready" | "complete" | "generated" | "selected", selected_asset_id: editor.values.selected_asset_id || null });
        await client.invalidateQueries({ queryKey: queryKeys.shots(selectedSceneId) });
      }
      setEditor(null);
    } catch (error) { setEditorError(errorMessage(error)); }
    finally { setEditorSaving(false); }
  }

  function createCharacter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    characterMutation.mutate({
      name: String(form.get("name") ?? ""), description: String(form.get("description") ?? ""),
      canonical_prompt: String(form.get("canonical_prompt") ?? ""), continuity_notes: String(form.get("continuity_notes") ?? ""),
      approved_reference_asset_ids: form.getAll("reference_asset_ids").map(String),
    }, { onSuccess: () => element.reset() });
  }

  function createScene(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    sceneMutation.mutate({
      number: Number(form.get("number")), title: String(form.get("title") ?? ""), description: String(form.get("description") ?? ""),
      location: String(form.get("location") ?? ""), time_of_day: String(form.get("time_of_day") ?? ""), mood: String(form.get("mood") ?? ""), status: "draft",
    }, { onSuccess: () => element.reset() });
  }

  function createShot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const selectedAsset = String(form.get("selected_asset_id") ?? "");
    shotMutation.mutate({
      number: Number(form.get("number")), description: String(form.get("description") ?? ""), shot_type: String(form.get("shot_type") ?? ""),
      camera_motion: String(form.get("camera_motion") ?? ""), duration_target: Number(form.get("duration_target")), dialogue: String(form.get("dialogue") ?? ""),
      selected_asset_id: selectedAsset || null, status: selectedAsset ? "selected" : "planned",
    }, { onSuccess: () => { element.reset(); setNewShotAsset(""); } });
  }

  return <section aria-labelledby="structure-title" className={`structure-panel structure-focus-${focus}`}>
    <div className="structure-heading"><div><span className="eyebrow">Production bible</span><h2 id="structure-title">{focus === "characters" ? "Characters" : focus === "scenes" ? "Scenes" : "Shots"}</h2><p>{focus === "characters" ? "Cast, visual identity and continuity references." : focus === "scenes" ? "Places, mood and the shots within each scene." : "Shot descriptions, timing and selected media."}</p></div>
      <label><span>Active scene</span><select aria-label="Active scene for shots" disabled={!scenes.data?.length} onChange={(event) => setChosenSceneId(event.target.value)} value={selectedSceneId}>{scenes.data?.length ? scenes.data.map((scene) => <option key={scene.id} value={scene.id}>Scene {scene.number} · {scene.title}</option>) : <option value="">Create a scene first</option>}</select></label>
    </div>
    {editor ? <form className="structure-editor" onSubmit={saveEditor}>
      <div className="structure-editor-heading"><div><span className="eyebrow">Editing {editor.kind}</span><h3>{editor.kind === "character" ? editor.values.name || "Untitled character" : editor.kind === "scene" ? editor.values.title || "Untitled scene" : `Shot ${editor.values.number || ""}`}</h3><p>Update the production record in context. Your changes stay with this project.</p></div><button className="icon-button" aria-label="Close editor" onClick={() => setEditor(null)} type="button">×</button></div>
      <div className="structure-editor-grid">
        {editor.kind === "character" ? <><label>Name<input required value={editor.values.name} onChange={(event) => updateEditorField("name", event.target.value)} /></label><label>Description<textarea rows={3} value={editor.values.description} onChange={(event) => updateEditorField("description", event.target.value)} /></label><label>Canonical visual prompt<textarea rows={3} value={editor.values.canonical_prompt} onChange={(event) => updateEditorField("canonical_prompt", event.target.value)} /></label><label>Continuity notes<textarea rows={3} value={editor.values.continuity_notes} onChange={(event) => updateEditorField("continuity_notes", event.target.value)} /></label></> : null}
        {editor.kind === "scene" ? <><label>Scene number<input min={1} required type="number" value={editor.values.number} onChange={(event) => updateEditorField("number", event.target.value)} /></label><label>Title<input required value={editor.values.title} onChange={(event) => updateEditorField("title", event.target.value)} /></label><label>Description<textarea rows={3} value={editor.values.description} onChange={(event) => updateEditorField("description", event.target.value)} /></label><label>Location<input value={editor.values.location} onChange={(event) => updateEditorField("location", event.target.value)} /></label><label>Time of day<input value={editor.values.time_of_day} onChange={(event) => updateEditorField("time_of_day", event.target.value)} /></label><label>Mood<input value={editor.values.mood} onChange={(event) => updateEditorField("mood", event.target.value)} /></label><label>Status<select value={editor.values.status} onChange={(event) => updateEditorField("status", event.target.value)}><option value="draft">Draft</option><option value="planned">Planned</option><option value="ready">Ready</option><option value="complete">Complete</option></select></label></> : null}
        {editor.kind === "shot" ? <><label>Shot number<input min={1} required type="number" value={editor.values.number} onChange={(event) => updateEditorField("number", event.target.value)} /></label><label>Duration (s)<input min={0.1} step={0.1} type="number" value={editor.values.duration_target} onChange={(event) => updateEditorField("duration_target", event.target.value)} /></label><label>Description<textarea rows={3} value={editor.values.description} onChange={(event) => updateEditorField("description", event.target.value)} /></label><label>Shot type<input value={editor.values.shot_type} onChange={(event) => updateEditorField("shot_type", event.target.value)} /></label><label>Camera motion<input value={editor.values.camera_motion} onChange={(event) => updateEditorField("camera_motion", event.target.value)} /></label><label>Dialogue<textarea rows={3} value={editor.values.dialogue} onChange={(event) => updateEditorField("dialogue", event.target.value)} /></label><AssetThumbnailPicker label="Selected media" assets={assets.filter(asset => ["image", "video"].includes(asset.kind))} projectId={projectId} value={editor.values.selected_asset_id} onChange={id => updateEditorField("selected_asset_id", id)} /></> : null}
      </div>
      {editorError ? <p className="form-error" role="alert">{editorError}</p> : null}<div className="structure-editor-actions"><button className="secondary-button" onClick={() => setEditor(null)} type="button">Cancel</button><button className="primary-button" disabled={editorSaving}>{editorSaving ? <LoaderCircle className="spin" size={15} /> : <Pencil size={15} />} Save changes</button></div>
    </form> : null}
    <div className="structure-columns">
      <div className="structure-list" id="structure-characters"><span><UserRound size={15} /> Characters <b>{characters.data?.length ?? 0}</b></span>{characters.data?.map((character) => <article key={character.id}><strong>{character.name}</strong><small>{character.description || "Continuity record"}</small><aside className="record-actions"><button aria-label={`Edit ${character.name}`} className="icon-button" onClick={() => void editCharacter(character)} type="button"><Pencil size={13} /></button><button aria-label={`Duplicate ${character.name}`} className="icon-button" onClick={() => characterMutation.mutate({ name: `${character.name} Copy`, description: character.description, canonical_prompt: character.canonical_prompt, negative_prompt: character.negative_prompt, continuity_notes: character.continuity_notes, voice_profile_id: character.voice_profile_id, metadata: character.metadata, approved_reference_asset_ids: character.approved_reference_asset_ids })} type="button"><Copy size={13} /></button></aside></article>)}
        <details><summary><Plus size={14} /> New character</summary><form className="compact-form" onSubmit={createCharacter}><label>Name *<input maxLength={200} name="name" required /></label><label>Description<textarea name="description" rows={2} /></label><label>Canonical visual prompt<textarea name="canonical_prompt" rows={2} /></label><label>Continuity notes<textarea name="continuity_notes" rows={2} /></label>{assets.filter((asset) => asset.kind === "image").length ? <fieldset><legend>Approved references</legend>{assets.filter((asset) => asset.kind === "image").slice(0, 6).map((asset) => <label className="check-row" key={asset.id}><input name="reference_asset_ids" type="checkbox" value={asset.id} /> {asset.id.slice(0, 8)}</label>)}</fieldset> : null}{characterMutation.error ? <p className="form-error" role="alert">{errorMessage(characterMutation.error)}</p> : null}<button className="primary-button compact" disabled={characterMutation.isPending}>{characterMutation.isPending ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />} Save character</button></form></details>
      </div>
      <div className="structure-list" id="structure-scenes"><span><MapPin size={15} /> Scenes <b>{scenes.data?.length ?? 0}</b></span>{scenes.data?.map((scene) => <button className={scene.id === selectedSceneId ? "selected" : ""} key={scene.id} onClick={() => setChosenSceneId(scene.id)} type="button"><strong>{scene.number}. {scene.title}</strong><small>{[scene.location, scene.time_of_day].filter(Boolean).join(" · ") || scene.status}</small><aside className="record-actions" onClick={(event) => event.stopPropagation()}><span role="button" aria-label={`Edit ${scene.title}`} className="icon-button" onClick={() => void editScene(scene)}><Pencil size={13} /></span><span role="button" aria-label={`Duplicate ${scene.title}`} className="icon-button" onClick={() => sceneMutation.mutate({ number: (scenes.data?.reduce((max, item) => Math.max(max, item.number), 0) ?? scene.number) + 1, title: `${scene.title} Copy`, description: scene.description, screenplay_text: scene.screenplay_text, location: scene.location, time_of_day: scene.time_of_day, mood: scene.mood, status: "draft" })}><Copy size={13} /></span></aside></button>)}
        <details><summary><Plus size={14} /> New scene</summary><form className="compact-form" onSubmit={createScene}><div className="form-pair"><label>Number *<input min={1} name="number" required type="number" /></label><label>Title *<input maxLength={300} name="title" required /></label></div><label>Description<textarea name="description" rows={2} /></label><div className="form-pair"><label>Location<input name="location" /></label><label>Time of day<input name="time_of_day" /></label></div><label>Mood<input name="mood" /></label>{sceneMutation.error ? <p className="form-error" role="alert">{errorMessage(sceneMutation.error)}</p> : null}<button className="primary-button compact" disabled={sceneMutation.isPending}><Plus size={14} /> Save scene</button></form></details>
      </div>
      <div className="structure-list" id="structure-shots"><span><Clapperboard size={15} /> Shots <b>{shots.data?.length ?? 0}</b></span><div className="structure-shot-thumbnails">{shots.data?.map((shot) => {
        const media = assets.find(asset => asset.project_id === projectId && asset.id === shot.selected_asset_id && ["image", "video"].includes(asset.kind));
        return <article className="structure-shot-tile" key={shot.id}><div className="structure-shot-media">{media ? <AssetPreview asset={media} compact /> : <div className="shot-thumbnail-empty"><Clapperboard size={24} /><small>No take chosen</small></div>}</div><strong>{shot.number}. {shot.shot_type || "Shot"}</strong><small>{shot.description || `${shot.duration_target}s · ${shot.status}`}</small><aside className="record-actions"><button aria-label={`Edit shot ${shot.number}`} className="icon-button" onClick={() => void editShot(shot)} type="button"><Pencil size={13} /></button><button aria-label={`Duplicate shot ${shot.number}`} className="icon-button" onClick={() => shotMutation.mutate({ number: ((shots.data?.reduce((max, item) => Math.max(max, item.number), 0) ?? shot.number) + 1), description: shot.description, shot_type: shot.shot_type, camera_motion: shot.camera_motion, duration_target: shot.duration_target, dialogue: shot.dialogue, status: "planned", selected_asset_id: shot.selected_asset_id })} type="button"><Copy size={13} /></button></aside></article>;
      })}</div>
        <details><summary><Plus size={14} /> New shot</summary><form className="compact-form" onSubmit={createShot}><div className="form-pair"><label>Number *<input min={1} name="number" required type="number" /></label><label>Duration (s)<input defaultValue={3} max={3600} min={0.1} name="duration_target" step={0.1} type="number" /></label></div><label>Description<textarea name="description" rows={2} /></label><div className="form-pair"><label>Shot type<input name="shot_type" placeholder="Wide, close-up…" /></label><label>Camera motion<input name="camera_motion" placeholder="Locked, dolly…" /></label></div><label>Dialogue<textarea name="dialogue" rows={2} /></label><input name="selected_asset_id" type="hidden" value={newShotAsset} /><AssetThumbnailPicker label="Selected media" assets={assets.filter(asset => ["image", "video"].includes(asset.kind))} projectId={projectId} value={newShotAsset} onChange={setNewShotAsset} />{shotMutation.error ? <p className="form-error" role="alert">{errorMessage(shotMutation.error)}</p> : null}<button className="primary-button compact" disabled={!selectedSceneId || shotMutation.isPending}><Plus size={14} /> Save shot</button></form></details>
      </div>
    </div>
  </section>;
}
