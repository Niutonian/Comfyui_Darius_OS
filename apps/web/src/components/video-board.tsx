"use client";
/* eslint-disable @next/next/no-img-element -- authenticated project media */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Film, PanelRightOpen, Save, Sparkles } from "lucide-react";
import { api, request } from "@/lib/api-client";
import { canvasApi, type CanvasGeneration } from "@/lib/canvas-api";
import { mossApi, type BoardSettings, type MossBoard, type VideoConfig, type VideoDraft, type VideoMode } from "@/lib/moss-workspace";
import { H3_ANIMATE, H3_CAMERA, H3_REFERENCE, H3_BODY_SWAP } from "@/lib/canvas-profile";
import { useWorkspaceState } from "@/lib/workspace-session";
import type { Asset } from "@/lib/types";
import type { CanvasHosts } from "./canvas-workspace";
import { ProjectImagePicker } from "./project-image-picker";
import { CanvasUtilityPanel, useCanvasNarrow, type CanvasUtilityTab } from "./canvas-utility-panel";

export const videoModes: { id: VideoMode; name: string; profile: typeof H3_ANIMATE | typeof H3_CAMERA | typeof H3_REFERENCE | typeof H3_BODY_SWAP }[] = [
 { id: "body-swap", name: "Body swap", profile: H3_BODY_SWAP }, { id: "animate-image", name: "Animate image", profile: H3_ANIMATE }, { id: "camera-direction", name: "Camera direction", profile: H3_CAMERA }, { id: "reference-video", name: "Reference video", profile: H3_REFERENCE },
];
export const isVideoBoard = (board: MossBoard) => board.kind === "minimax-h3-video";
export function videoDefaults(): VideoConfig { return { schemaVersion: 1, family: "minimax-h3", activeMode: "animate-image", modeDrafts: Object.fromEntries(videoModes.map(m => [m.id, { prompt: "", camera: "", audio: "", inputs: [], seconds: ["camera-direction", "body-swap"].includes(m.id) ? 5 : 10, turbo: true, preset: "wide", resolution: "native" }])) as unknown as VideoConfig["modeDrafts"] }; }

function useVideoBoardDraft(board: MossBoard) {
 const [form, setForm] = useWorkspaceState<VideoConfig>(`h3:${board.projectId}:${board.id}:draft`, board.settings.video ?? videoDefaults());
 const [baseRevision, setBaseRevision] = useWorkspaceState(`h3:${board.projectId}:${board.id}:base`, board.revision);
 const baseline = useRef(board.settings.video);
 useEffect(() => { if (JSON.stringify(baseline.current) !== JSON.stringify(board.settings.video)) { if (JSON.stringify(form) === JSON.stringify(baseline.current)) { setForm(board.settings.video ?? videoDefaults()); setBaseRevision(board.revision); } baseline.current = board.settings.video; } }, [board.settings.video, board.revision, form, setForm, setBaseRevision]);
 return { form, setForm, baseRevision, setBaseRevision };
}

function useVideoInputPicker(board: MossBoard) {
 return useWorkspaceState(`h3:${board.projectId}:${board.id}:input-picker`, { open: false, request: 0, mediaKind: "image" as "image" | "video" });
}

type VideoSize = { preset: string; resolution: string; width: number; height: number; generationWidth: number; generationHeight: number };
const videoPresets = [{ id: "wide", name: "16:9 · Landscape" }, { id: "vertical", name: "9:16 · Portrait" }, { id: "square", name: "1:1 · Square" }, { id: "standard", name: "4:3 · Standard" }, { id: "portrait", name: "3:4 · Portrait" }, { id: "photo", name: "3:2 · Photo" }, { id: "poster", name: "2:3 · Poster" }, { id: "ultrawide", name: "21:9 · Ultrawide" }];
const videoResolutions = [{ id: "native", name: "Workflow default" }, { id: "480p", name: "480p class" }, { id: "720p", name: "720p class" }, { id: "1080p", name: "1080p class" }];
type Engine = { durations?: number[]; modes: { id: VideoMode; width: number; height: number; sizes?: VideoSize[]; durations?: number[]; timings: { requestedSeconds: number; frames: number; nominalSeconds: number }[]; readiness: { ready: boolean; issues: string[] } | null }[] };
export function VideoBoardControls({ board, assets, onChange, onError }: { board: MossBoard; assets: Asset[]; onChange: (settings: BoardSettings) => Promise<unknown>; onError: (message: string) => void }) {
 const { form, setForm, baseRevision, setBaseRevision } = useVideoBoardDraft(board);
 const [saving, setSaving] = useState(false);
 const [picker, setPicker] = useVideoInputPicker(board);
 const pickerRef = useRef<HTMLDivElement>(null);
 useEffect(() => {
  if (!picker.open) return;
  // Place focus after the mobile sheet's initial focus on its close button.
  let focusFrame = 0;
  const frame = requestAnimationFrame(() => { focusFrame = requestAnimationFrame(() => { pickerRef.current?.scrollIntoView?.({ block: "nearest" }); pickerRef.current?.focus({ preventScroll: true }); }); });
  return () => { cancelAnimationFrame(frame); cancelAnimationFrame(focusFrame); };
 }, [picker.open, picker.request]);
 const [uploading, setUploading] = useWorkspaceState(`h3:${board.projectId}:${board.id}:uploading`, false);
 const upload = useRef<HTMLInputElement>(null);
 const videoUpload = useRef<HTMLInputElement>(null);
 const client = useQueryClient();
 const engine = useQuery({ queryKey: ["h3-engine"], queryFn: () => request<Engine>("/canvas/video/engine?check=true"), staleTime: 60000 });
 const mode = form.activeMode, draft = form.modeDrafts[mode], dirty = JSON.stringify(form) !== JSON.stringify(board.settings.video);
 const capability = engine.data?.modes.find(m => m.id === mode), clock = capability?.timings.find(t => t.requestedSeconds === draft.seconds);
 const preset = draft.preset ?? "wide", resolution = draft.resolution ?? "native";
 const selectedSize = capability?.sizes?.find(size => size.preset === preset && size.resolution === resolution);
 const update = (patch: Partial<typeof draft>) => setForm(old => ({ ...old, modeDrafts: { ...old.modeDrafts, [old.activeMode]: { ...old.modeDrafts[old.activeMode], ...patch } } }));
 function bindImage(asset: Asset, targetMode = mode) {
  setForm(old => {
   const draft = old.modeDrafts[targetMode];
   if (targetMode === "body-swap" ? draft.inputs.some(i => i.mediaKind === asset.kind) : draft.inputs.length >= (targetMode === "reference-video" ? 9 : 1)) return old;
   return { ...old, modeDrafts: { ...old.modeDrafts, [targetMode]: { ...draft, inputs: [...draft.inputs, { id: crypto.randomUUID(), assetId: asset.id, assetVersionId: asset.content_hash, mediaKind: asset.kind as "image" | "video", role: targetMode === "body-swap" ? (asset.kind === "video" ? "source-video" : "replacement-character") : targetMode === "animate-image" ? "starting-frame" : targetMode === "camera-direction" ? "camera-source" : "subject", token: targetMode === "body-swap" ? (asset.kind === "video" ? 2 : 1) : draft.inputs.length + 1 }] } } };
  });
  setPicker(old => ({ ...old, open: false }));
 }
 async function save(next = form) {
  setSaving(true);
  try { if (baseRevision !== board.revision) throw new Error("This video draft changed on another device. Reload the saved draft before updating."); await onChange({ ...board.settings, adapterVersion: videoModes.find(m => m.id === next.activeMode)!.profile, video: next }); setBaseRevision(board.revision + 1); }
  catch (error) { onError(error instanceof Error ? error.message : "Video draft could not save"); throw error; }
  finally { setSaving(false); }
 }
 return <div className="h3-controls" aria-busy={saving}>
  <label>Board name<input key={`${board.id}:${board.name}`} defaultValue={board.name} maxLength={200} disabled={saving} onBlur={async e => { const name = e.target.value.trim(); if (!name || name === board.name) return; try { const doc = await canvasApi.get(board.projectId, board.documentId); await canvasApi.save(board.projectId, board.documentId, doc.revision, { ...doc.content, name }); await client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] }); } catch (error) { onError((error as Error).message); } }} /></label>
  <p className="canvas-help">MiniMax H3 · {mode === "body-swap" ? "character replacement with source audio" : "generated video and audio"}</p>
  <label>Mode<select aria-label="Video mode" value={mode} disabled={saving || uploading || board.archived} onChange={e => { const next = { ...form, activeMode: e.target.value as VideoMode, modeDrafts: { ...videoDefaults().modeDrafts, ...form.modeDrafts } }; setForm(next); void save(next).catch(() => {}); }}>{videoModes.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
  <fieldset disabled={saving || uploading || board.archived}>
  {mode !== "body-swap" ? <label>Scene and action<textarea aria-label="Video scene prompt" rows={5} value={draft.prompt} placeholder="Describe the scene, action and style…" onChange={e => update({ prompt: e.target.value })} /></label> : <><p className="canvas-help">Replace the main character in a source clip. Ollama describes the replacement image automatically; the scene, performance and source soundtrack guide the result.</p><label>Ollama vision model<input aria-label="Body swap vision model" value={draft.visionModel ?? "robit/ornith-vision:9b"} onChange={e => update({ visionModel: e.target.value })} /></label><label>Clip start (seconds)<input aria-label="Body swap clip start" type="number" min="0" max="86400" step="0.1" value={draft.clipStart ?? 0} onChange={e => update({ clipStart: Number(e.target.value) })} /></label><label>Processing size<select aria-label="Body swap processing size" value={draft.swapLongEdge ?? 896} onChange={e => update({ swapLongEdge: Number(e.target.value) as VideoDraft["swapLongEdge"] })}>{[512,640,768,896].map(edge => <option key={edge} value={edge}>{edge}px long edge</option>)}</select></label><p className="canvas-help">Source aspect is preserved with fit/padding. At most five seconds are selected, rounded down to H3 frames (107 frames / 4.458s for a full five-second selection). Shorter sources use their available interval.</p></>}
  {mode === "camera-direction" ? <><label>Camera direction<textarea rows={3} value={draft.camera} placeholder="Slow dolly in, gentle pan…" onChange={e => update({ camera: e.target.value })} /></label><label>Speed<select value={draft.turbo ? "turbo" : "base"} onChange={e => update({ turbo: e.target.value === "turbo" })}><option value="turbo">Turbo · 8 steps</option><option value="base">Base · 20 steps</option></select></label><p className="canvas-help">Written camera guidance with a camera-motion LoRA. Timing follows the selected duration at 24 fps.</p></> : null}
  {mode !== "body-swap" ? <label>Audio direction<textarea rows={2} value={draft.audio} placeholder="Room ambience, footsteps, no music…" onChange={e => update({ audio: e.target.value })} /></label> : null}
  <div className="h3-inputs">{draft.inputs.map((binding, index) => { const asset = assets.find(a => a.id === binding.assetId); return <div className="h3-input" key={binding.id}>{binding.mediaKind === "video" ? <video src={api.assetContentUrl(binding.assetId)} controls muted playsInline preload="metadata" /> : <img src={api.assetContentUrl(binding.assetId)} alt={(asset ? String(asset.metadata.display_name ?? asset.metadata.original_filename ?? "Image") : undefined) ?? `Picture ${binding.token}`} />}<div><strong>{mode === "body-swap" ? (binding.mediaKind === "video" ? "Source video" : "Replacement character") : mode === "reference-video" ? `Picture ${binding.token}` : mode === "camera-direction" ? "Camera source" : "Starting frame"}</strong><small>{(asset ? String(asset.metadata.display_name ?? asset.metadata.original_filename ?? "Image") : undefined) ?? "Pinned image version"}</small>{mode === "reference-video" ? <select aria-label={`Role for Picture ${binding.token}`} value={binding.role} onChange={e => update({ inputs: draft.inputs.map(b => b.id === binding.id ? { ...b, role: e.target.value as typeof b.role } : b) })}><option value="subject">Subject</option><option value="environment">Environment</option><option value="style">Style</option></select> : null}<button type="button" className="text-button" onClick={() => { if (mode !== "body-swap" && (new RegExp(`<Picture\\s+${binding.token}>`, "i").test(draft.prompt) || index !== draft.inputs.length - 1)) { onError("Update Picture labels in the prompt before removing references. Remove the last picture first to keep labels stable."); return; } update({ inputs: draft.inputs.filter(b => b.id !== binding.id) }); }}>Remove</button></div></div>; })}</div>
  <button type="button" className="secondary-button" disabled={mode === "body-swap" ? draft.inputs.some(b => b.mediaKind === "image") : draft.inputs.length >= (mode === "reference-video" ? 9 : 1)} onClick={() => setPicker(old => ({ open: !old.open, request: old.request + 1, mediaKind: "image" }))}>Choose {mode === "reference-video" ? "reference image" : mode === "body-swap" ? "character image" : "source image"}</button>
  <button type="button" className="secondary-button" disabled={mode === "body-swap" ? draft.inputs.some(b => b.mediaKind === "image") : draft.inputs.length >= (mode === "reference-video" ? 9 : 1)} onClick={() => upload.current?.click()}>{uploading ? "Uploading image…" : "Upload image"}</button>
  <input ref={upload} type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label="Upload video input image" hidden onChange={async e => {
   const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
   const targetMode = mode; setUploading(true);
   try { const asset = await api.uploadAsset(file, { project_id: board.projectId, role: "reference" }); bindImage(asset, targetMode); await client.invalidateQueries({ queryKey: ["assets"] }); }
   catch (error) { onError(error instanceof Error ? error.message : "Image upload failed"); }
   finally { setUploading(false); }
  }} />
 {mode === "body-swap" ? <><button type="button" className="secondary-button" disabled={draft.inputs.some(b => b.mediaKind === "video")} onClick={() => setPicker(old => ({ ...old, open: true, request: old.request + 1, mediaKind: "video" }))}>Choose source video</button><button type="button" className="secondary-button" disabled={draft.inputs.some(b => b.mediaKind === "video")} onClick={() => videoUpload.current?.click()}>Upload source video</button><input ref={videoUpload} hidden type="file" accept="video/mp4,video/webm,video/quicktime,video/x-matroska" aria-label="Upload body swap source video" onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; const targetMode = mode; setUploading(true); try { const asset = await api.uploadAsset(file, { project_id: board.projectId, role: "reference" }); if (asset.kind !== "video") throw new Error("Choose a video file"); bindImage(asset, targetMode); await client.invalidateQueries({ queryKey: ["assets"] }); } catch(error) { onError(error instanceof Error ? error.message : "Video upload failed"); } finally { setUploading(false); } }} /></> : null}
 {picker.open ? <ProjectImagePicker pickerRef={pickerRef} mediaKind={picker.mediaKind} assets={assets} projectId={board.projectId} onChoose={bindImage} /> : null}
  {mode !== "body-swap" ? <><label>Aspect ratio<select aria-label="Video aspect ratio" value={preset} onChange={e => update({ preset: e.target.value as VideoDraft["preset"] })}>{videoPresets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
  <label>Output resolution<select aria-label="Video resolution" value={resolution} onChange={e => update({ resolution: e.target.value as VideoDraft["resolution"] })}>{videoResolutions.map(item => { const size = capability?.sizes?.find(size => size.preset === preset && size.resolution === item.id); return <option key={item.id} value={item.id}>{item.name}{size ? ` · ${size.width} × ${size.height}` : ""}</option>; })}</select></label>
  </> : null}
  <label>Requested duration<select aria-label="Video duration" value={draft.seconds} onChange={e => update({ seconds: Number(e.target.value) })}>{(capability?.durations ?? (mode === "body-swap" ? [5] : engine.data?.durations) ?? Array.from({ length: 11 }, (_, i) => i + 5)).map(seconds => <option key={seconds} value={seconds}>{seconds} seconds</option>)}</select></label>
  <p className="canvas-help">Larger frames use more GPU memory. Timing follows the selected workflow.</p>
  {mode !== "body-swap" ? <><p className="canvas-help">{selectedSize ? `${selectedSize.width} × ${selectedSize.height} final${mode === "reference-video" ? ` · ${selectedSize.generationWidth} × ${selectedSize.generationHeight} first pass` : ""}` : "Checking output dimensions…"}{clock ? ` · ${clock.frames} frames · ${clock.nominalSeconds.toFixed(3)}s nominal` : ""} · 24 fps</p>
  <p className="canvas-help">{mode === "reference-video" ? "Reference aspect preserved; max reference sizing. Two-stage sampling with generated audio. Motion and audio reference inputs are awaiting runtime validation." : "Starting image stretches to the output aspect ratio. Playback starts muted; generated audio is kept."}</p></> : null}
  <label>Seed<input aria-label="Video seed" defaultValue={board.settings.seed ?? ""} inputMode="numeric" placeholder="Random once per request" onBlur={e => { const value = e.target.value.trim(); if (value && (!/^\d+$/.test(value) || BigInt(value) > BigInt("18446744073709551615"))) { onError("Use an unsigned 64-bit seed"); return; } if ((value || null) !== board.settings.seed) void onChange({ ...board.settings, seed: value || null }).then(() => setBaseRevision(board.revision + 1)).catch(e => onError(e.message)); }} /></label>
  </fieldset>
  {baseRevision !== board.revision && dirty ? <p role="alert">This board changed elsewhere. Your local draft is retained. <button type="button" onClick={() => { setForm(board.settings.video ?? videoDefaults()); setBaseRevision(board.revision); }}>Reload saved draft</button></p> : null}
  <button type="button" className="secondary-button" disabled={!dirty || saving || board.archived} onClick={() => void save().catch(() => {})}><Save size={15} />{saving ? "Saving…" : dirty ? "Save video draft" : "Draft saved"}</button>
  {engine.isError ? <p role="alert">Could not check ComfyUI. <button onClick={() => void engine.refetch()}>Retry check</button></p> : capability?.readiness && !capability.readiness.ready ? <p className="form-error">{capability.readiness.issues.join(" · ")}</p> : null}
  {board.jobs.map(job => <div className="moss-job" key={job.id}><strong>{job.statusMessage}</strong>{job.status === "queued" ? <><button className="text-button" onClick={() => void canvasApi.start(board.projectId, board.documentId, job.id).catch(error => onError(error.message))}>Start worker</button><button className="text-button" onClick={() => void mossApi.cancel(board.projectId, board.id, job.jobId).then(() => client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] })).catch(error => onError(error.message))}>Cancel queued job</button></> : null}</div>)}
  <button type="button" className="text-button" onClick={async () => { if (!confirm(board.archived ? "Restore this board?" : "Archive this board? Its drafts, inputs and results are retained.")) return; try { await mossApi.save(board.projectId, board, board.settings, !board.archived); await client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] }); } catch (error) { onError((error as Error).message); } }}>{board.archived ? "Restore board" : "Archive board"}</button>
 {mode === "reference-video" ? <label>Final-stage upscaler<select aria-label="Final-stage upscaler" value={draft.upscaleDevice ?? "cuda"} onChange={e => update({ upscaleDevice: e.target.value as "cuda" | "cpu" })}><option value="cuda">GPU · faster</option><option value="cpu">CPU · save upscale VRAM</option></select><small>CPU changes only the latent upscaler. Final refinement still uses the GPU. Retrying reruns the workflow; no durable latent checkpoint is stored.</small></label> : null}
 <p className="canvas-help">{mode === "body-swap" ? "Try the 512px processing size for a lower-memory draft. The source clip is retained for comparison." : "Longer clips and larger resolutions require more memory. Hardware fit is unknown until tested. A 5-second 480p draft is a lower-memory starting point; settings are never lowered automatically."}</p>
  <details><summary>Effective prompt and recipe</summary><pre>{draft.prompt}{mode === "camera-direction" && draft.camera.trim() ? `\n\nCamera direction:\n${draft.camera.trim()}` : ""}{draft.audio.trim() ? `\n\nAudio direction:\n${draft.audio.trim()}` : ""}</pre><p className="canvas-help">{mode === "body-swap" ? "H3 Ref2VA · Character Swap v1.1 · Turbo 8-step · original source audio. Ollama prepares the fixed task prompt from the character image." : mode === "reference-video" ? "Singularity ref2va · beta 12, split at 8 · euler · spatial latent upscale 1.5× · audio retained between stages." : mode === "camera-direction" ? "FL2VA INT8 · camera LoRA 0.8 · Turbo LoRA 1 when enabled · res_multistep / simple." : "FL2VA INT8 · LightX2V LoRA 1 · shift video 12 / audio 3 · comfy kitchen attention · euler / simple · 4 steps. Scheduler uses the raw base model."}</p></details>
 </div>;
}

export function VideoCardPreview({ board, visible = true }: { board: MossBoard; visible?: boolean }) {
 const video = useRef<HTMLVideoElement>(null), [playing, setPlaying] = useState(false), [started, setStarted] = useState(false), result = board.activeResult ?? (board.latest?.status === "completed" && board.latest.assetIds.length ? board.latest : null), partial = !result && board.latest?.intermediateAssetIds?.[0], asset = result?.assetIds[0] ?? (partial || undefined);
 const thumb = useQuery({ queryKey: ["moss-thumbnail", asset], enabled: Boolean(asset && !(board.activeResult?.id === result?.id && board.previewAssetId)), staleTime: Infinity, queryFn: async () => (await request<{ derivatives: Asset[] }>(`/assets/${asset}/derivatives?thumbnail_only=true`, { method: "POST" })).derivatives.find(a => a.metadata.derivative_type === "thumbnail")?.id ?? null });
 const poster = (board.activeResult?.id === result?.id ? board.previewAssetId : null) ?? thumb.data;
 useEffect(() => { if (!visible) video.current?.pause(); }, [visible]);
 useEffect(() => { const node = video.current; if (!node) return; const observer = new IntersectionObserver(entries => { if (!entries[0]?.isIntersecting) node.pause(); }); observer.observe(node); return () => { observer.disconnect(); node.pause(); }; }, [asset]);
 const { form: config } = useVideoBoardDraft(board), input = config.modeDrafts[config.activeMode].inputs.find(i => i.mediaKind === "image") ?? config.modeDrafts[config.activeMode].inputs[0];
 return <div className="moss-preview h3-card-preview">{partial ? <span className="h3-partial-label">Stage-one preview · final failed</span> : null}{asset ? <><video ref={video} src={started ? api.assetContentUrl(asset) : undefined} poster={poster ? api.assetContentUrl(poster) : undefined} controls={playing} muted preload="none" playsInline onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onPointerDown={e => e.stopPropagation()} />{!playing ? <button type="button" className="h3-play" aria-label={`Play ${board.name}`} onClick={e => { e.stopPropagation(); setStarted(true); setPlaying(true); const node = video.current; if (node) { node.src = api.assetContentUrl(asset); node.muted = true; void node.play().catch(() => setPlaying(false)); } }}>▶ Play</button> : null}</> : input?.mediaKind === "video" ? <video src={api.assetContentUrl(input.assetId)} muted playsInline preload="metadata" /> : input ? <img className="moss-image-artwork" src={api.assetContentUrl(input.assetId)} alt="Pinned video input" /> : <div className="h3-empty"><Film size={30} /><span>Choose an image. Bring it to life.</span></div>}</div>;
}

export function VideoBoardEditor({ board, assets, projectId, onExit, onGenerate, ...hosts }: CanvasHosts & { board: MossBoard; assets: Asset[]; projectId: string; onExit: () => void; onGenerate: () => Promise<void> }) {
 const client = useQueryClient(), narrow = useCanvasNarrow(), [open, setOpen] = useState(!narrow), [tab, setTab] = useState<CanvasUtilityTab>("board"), [error, setError] = useState("");
 const doc = useQuery({ queryKey: ["canvas", projectId, board.documentId], queryFn: () => canvasApi.get(projectId, board.documentId), refetchInterval: 2500 });
 const { form, setForm, setBaseRevision } = useVideoBoardDraft(board);
 const [uploading] = useWorkspaceState(`h3:${board.projectId}:${board.id}:uploading`, false);
 const latest = doc.data?.generations[0];
 const failed = latest?.status === "failed" && latest.provenance.partial ? latest : undefined;
 async function recover(generation: CanvasGeneration, kind: "cpu" | "smaller") {
  const original = generation.provenance.videoConfig as VideoConfig | undefined;
  if (!original || !confirm("Load the original failed request as a saved recovery draft? Current unsaved video settings will be replaced. Nothing renders until you press Generate.")) return;
  const next = structuredClone(original), draft = next.modeDrafts[next.activeMode];
  if (kind === "cpu") draft.upscaleDevice = "cpu";
  else { draft.seconds = 5; draft.resolution = "480p"; }
  try {
   const adapterVersion = videoModes.find(mode => mode.id === next.activeMode)!.profile;
   const saved = await mossApi.save(projectId, board, { ...board.settings, adapterVersion, seed: generation.seed, video: next });
   setForm(next); setBaseRevision(saved.revision); setOpen(true); setTab("board"); setError("");
   client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(item => item.id === saved.id ? saved : item) } : old);
   await client.invalidateQueries({ queryKey: ["moss-workspace", projectId] });
  } catch (error) { setError(error instanceof Error ? error.message : "Recovery draft could not save. Your draft is retained."); }
 }
 const inputs = form.modeDrafts[form.activeMode].inputs;
 function openInputs() { setTab("board"); setOpen(true); if (hosts.assistantOpen) hosts.onToggleAssistant?.(); }
 const [, setInputPicker] = useVideoInputPicker(board);
 function chooseInputs() { openInputs(); setInputPicker(old => ({ ...old, open: true, request: old.request + 1, mediaKind: form.activeMode === "body-swap" && !inputs.some(i => i.mediaKind === "video") ? "video" : "image" })); }
 const result = doc.data?.generations.find(g => g.id === doc.data?.activeGenerationId) ?? (!doc.data?.activeGenerationId ? doc.data?.generations.find(g => g.status === "completed" && g.assetIds.length && !g.provenance.partial && String(g.provenance.profileId ?? "").startsWith("minimax-h3-")) : undefined), assetId = result?.assetIds[0], asset = assets.find(a => a.id === assetId);
 const inputKey = JSON.stringify([form.activeMode, inputs]);
 const [display, setDisplay] = useState({ kind: "result", inputKey, resultId: result?.id });
 if (display.resultId !== result?.id) setDisplay({ kind: "result", inputKey, resultId: result?.id });
 const showInputs = !assetId || (display.resultId === result?.id && (display.kind === "inputs" || display.inputKey !== inputKey));
 async function save(settings: BoardSettings) { const saved = await mossApi.save(projectId, board, settings); client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); await client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }); }
 return <section className="canvas-workspace canvas-refined h3-editor" aria-label="Video board editor"><header className="canvas-header"><button className="icon-button" aria-label="Back to boards" onClick={onExit}><ArrowLeft size={17} /></button><div><strong>{board.name}</strong><small>MiniMax H3 · {videoModes.find(m => m.id === board.settings.video?.activeMode)?.name}</small></div><button className="icon-button" aria-label="Open Video settings" onClick={openInputs}><PanelRightOpen size={17} /></button><button className="primary-button" disabled={Boolean(board.jobs.length) || uploading || board.archived} onClick={() => void onGenerate().catch(e => setError(e.message))}><Sparkles size={15} />{board.jobs[0]?.statusMessage ?? "Generate video"}</button></header>
 {failed ? <VideoFailureRecovery generation={failed} onRecover={kind => void recover(failed, kind)} disabled={board.archived || Boolean(board.jobs.length)} /> : null}
 {error || board.latest?.error ? <div className="canvas-notice is-error" role="alert">{error || board.latest?.error}</div> : null}<div className="moss-body"><main className="h3-viewer">
 {assetId ? <nav className="h3-view-tabs" aria-label="Video preview"><button className="secondary-button" aria-pressed={showInputs} onClick={() => setDisplay({ kind: "inputs", inputKey, resultId: result?.id })}>Input media</button><button className="secondary-button" aria-pressed={!showInputs} onClick={() => setDisplay({ kind: "result", inputKey, resultId: result?.id })}>Generated video</button></nav> : null}
 {assetId && !showInputs ? <><video key={assetId} src={api.assetContentUrl(assetId)} controls muted playsInline preload="metadata" /><p>{asset?.width} × {asset?.height} · {asset?.duration?.toFixed(2)}s · {String(result?.provenance.profileName ?? "Video")}<a href={api.assetContentUrl(assetId)} download><Download size={15} /> Download</a></p></> : inputs.length ? <div className={`h3-input-preview ${inputs.length > 1 ? "is-multiple" : ""}`}>{inputs.map(input => <figure key={input.id}>{input.mediaKind === "video" ? <video src={api.assetContentUrl(input.assetId)} controls muted playsInline preload="metadata" /> : <img src={api.assetContentUrl(input.assetId)} alt={form.activeMode === "reference-video" ? `Picture ${input.token} preview` : "Pinned source image"} />}{form.activeMode === "reference-video" ? <figcaption>Picture {input.token}</figcaption> : null}</figure>)}</div> : <div className="h3-empty"><Film size={44} /><h3>A little motion for your idea.</h3><p>Choose a mode, pin an image and describe what happens next.</p><button className="secondary-button" disabled={board.archived || uploading} onClick={chooseInputs}>Choose video inputs</button></div>}</main>
 <CanvasUtilityPanel open={open} tab={tab} onTabChange={value => { setTab(value); setOpen(true); }} onClose={() => setOpen(false)} context={`Video board: ${board.name} · ${board.settings.video?.activeMode}`} primary={<VideoBoardControls board={board} assets={assets} onChange={save} onError={setError} />} history={<div className="h3-history">{doc.data?.generations.map(g => <article key={g.id}><strong>{String(g.provenance.profileName ?? "Video")}</strong><small>{g.status} · seed {g.seed}</small>{g.error ? <p>{g.error}</p> : null}{g.status === "failed" && g.provenance.partial ? <VideoFailureRecovery generation={g} onRecover={kind => void recover(g, kind)} disabled={board.archived || Boolean(board.jobs.length)} /> : null}{g.assetIds.map((id, i) => <div key={id}><span>{g.provenance.mode === "body-swap" && i > 0 ? "Source comparison" : g.provenance.partial || i > 0 ? "Stage 1 · intermediate" : "Final"}</span><video controls muted playsInline preload="none" src={api.assetContentUrl(id)} /></div>)}{g.status === "completed" ? <button className="secondary-button" onClick={async () => { await canvasApi.select(projectId, board.documentId, g.id); await doc.refetch(); }}>Display this result</button> : null}</article>)}</div>} hosts={hosts} /></div><footer className="canvas-footer"><span>Saved mode: {board.settings.video?.activeMode}</span><span>{board.jobs[0]?.statusMessage ?? "Ready"}</span></footer></section>;
}


export function VideoFailureRecovery({ generation, onRecover, disabled = false }: { generation: CanvasGeneration; onRecover: (kind: "cpu" | "smaller") => void; disabled?: boolean }) {
 const recovery = generation.provenance.recovery as { message?: string } | undefined;
 const ids = (generation.provenance.intermediateAssetIds as string[] | undefined) ?? generation.assetIds;
 return <section className="video-recovery" aria-label="Video recovery"><strong>{recovery?.message ?? "Preview saved; the final video stage failed."}</strong>
 <p>The saved preview is an intermediate, not a finished render. Recovery loads the original prompt, references and seed into a draft. Generate reruns the workflow; no durable latent checkpoint is available.</p>
 {ids.length ? <details><summary>View saved stage-one preview</summary><video controls muted playsInline preload="metadata" src={api.assetContentUrl(ids[0])} /><a href={api.assetContentUrl(ids[0])} download>Download saved preview</a></details> : null}
 <div className="creative-prompt-actions"><button type="button" className="secondary-button" disabled={disabled} onClick={() => onRecover("cpu")}>Use CPU final upscale</button><button type="button" className="secondary-button" disabled={disabled} onClick={() => onRecover("smaller")}>Use a 5-second 480p draft</button></div></section>;
}
