"use client";
/* eslint-disable @next/next/no-img-element -- project-owned local assets */
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, ImagePlus, PanelRightOpen, Save, Sparkles } from "lucide-react";
import { api, request } from "@/lib/api-client";
import { canvasApi } from "@/lib/canvas-api";
import { canvasProfiles, IMAGE_FLUX, IMAGE_KREA, IMAGE_QWEN, IMAGE_EDIT } from "@/lib/canvas-profile";
import { mossApi, type ImageProfile, type ImageDraft, type ImageRecipeConfig, type MossBoard, type BoardSettings } from "@/lib/moss-workspace";
import { emptyCanvas, type CanvasViewport } from "@/lib/canvas-document";
import { useWorkspaceState } from "@/lib/workspace-session";
import type { Asset } from "@/lib/types";
import type { CanvasHosts } from "./canvas-workspace";
import { CanvasUtilityPanel, useCanvasNarrow, type CanvasUtilityTab } from "./canvas-utility-panel";
const CanvasStage = dynamic(() => import("./canvas-stage"), { ssr: false });

export const imageRecipes: ImageProfile[] = [IMAGE_FLUX, IMAGE_KREA, IMAGE_QWEN, IMAGE_EDIT];
export const isImageRecipeBoard = (board: MossBoard) => board.kind === "image-recipe";
export function imageRecipeDefaults(profile: ImageProfile = IMAGE_FLUX): ImageRecipeConfig {
 const draft = (id: ImageProfile): ImageDraft => ({ prompt: "", negativePrompt: id === IMAGE_FLUX ? "out of frame head" : "", inputs: [], preset: id === IMAGE_FLUX ? "poster" : "square", megapixels: 1, steps: id === IMAGE_FLUX ? 50 : id === IMAGE_KREA ? 8 : 25, cfg: id === IMAGE_FLUX ? 3.5 : 1, seed: null, enhance: id === IMAGE_FLUX || id === IMAGE_KREA, styleEnabled: false, styleLora: "krea2_darkbrush.safetensors", styleStrength: .8, styleText: "muted minimalist sketch style", followSource: true, referenceResolution: 0 });
 return { schemaVersion: 1, activeProfile: profile, drafts: { [IMAGE_FLUX]: draft(IMAGE_FLUX), [IMAGE_KREA]: draft(IMAGE_KREA), [IMAGE_QWEN]: draft(IMAGE_QWEN), [IMAGE_EDIT]: draft(IMAGE_EDIT) } };
}
function useImageDraft(board: MossBoard) {
 const key = `image-recipe:${board.projectId}:${board.id}`;
 const [form, setForm] = useWorkspaceState<ImageRecipeConfig>(`${key}:draft`, board.settings.image ?? imageRecipeDefaults(board.settings.adapterVersion as ImageProfile));
 const [baseRevision, setBaseRevision] = useWorkspaceState(`${key}:base`, board.revision), baseline = useRef(board.settings.image);
 const [uploading, setUploading] = useWorkspaceState(`${key}:uploading`, false);
 useEffect(() => { if (JSON.stringify(baseline.current) !== JSON.stringify(board.settings.image)) { if (JSON.stringify(form) === JSON.stringify(baseline.current)) { setForm(board.settings.image ?? imageRecipeDefaults()); setBaseRevision(board.revision); } baseline.current = board.settings.image; } }, [board.settings.image, board.revision, form, setForm, setBaseRevision]);
 return { form, setForm, baseRevision, setBaseRevision, uploading, setUploading };
}
type Engine = { profiles: { id: ImageProfile; readiness: { ready: boolean; issues: string[] } | null }[]; presets: { id: ImageDraft["preset"]; name: string }[] };
const label = (asset?: Asset) => String(asset?.metadata.display_name ?? asset?.metadata.original_filename ?? "Pinned image version");

export function ImageRecipeControls({ board, assets, onChange, onError }: { board: MossBoard; assets: Asset[]; onChange: (settings: BoardSettings) => Promise<unknown>; onError: (message: string) => void }) {
 const { form, setForm, baseRevision, setBaseRevision, uploading, setUploading } = useImageDraft(board);
 const [saving, setSaving] = useState(false), [picker, setPicker] = useState(false), upload = useRef<HTMLInputElement>(null), client = useQueryClient();
 const engine = useQuery({ queryKey: ["image-recipe-engine"], queryFn: () => request<Engine>("/canvas/image/engine?check=true"), staleTime: 60000 });
 const profile = form.activeProfile, draft = form.drafts[profile], edit = profile === IMAGE_EDIT, dirty = JSON.stringify(form) !== JSON.stringify(board.settings.image);
 const update = (patch: Partial<ImageDraft>) => setForm(old => ({ ...old, drafts: { ...old.drafts, [old.activeProfile]: { ...old.drafts[old.activeProfile], ...patch } } }));
 async function save(next = form) {
  if (baseRevision !== board.revision) { onError("This board changed on another device. Reload its saved draft before saving."); return; }
  setSaving(true);
  try { await onChange({ ...board.settings, adapterVersion: next.activeProfile, seed: next.drafts[next.activeProfile].seed, image: next }); setBaseRevision(board.revision + 1); }
  catch (error) { onError((error as Error).message); }
  finally { setSaving(false); }
 }
 function bind(asset: Asset) {
  setForm(old => { const d = old.drafts[IMAGE_EDIT]; if (d.inputs.length >= 10) return old; return { ...old, drafts: { ...old.drafts, [IMAGE_EDIT]: { ...d, inputs: [...d.inputs, { id: crypto.randomUUID(), assetId: asset.id, assetVersionId: asset.content_hash, mediaKind: "image", token: d.inputs.length + 1 }] } } }; });
  setPicker(false);
 }
 const status = engine.data?.profiles.find(p => p.id === profile)?.readiness;
 return <div className="h3-controls image-recipe-controls" aria-busy={saving || uploading}>
 <label>Board name<input key={`${board.id}:${board.name}`} defaultValue={board.name} maxLength={200} onBlur={async e => { const name = e.target.value.trim(); if (!name || name === board.name) return; try { const doc = await canvasApi.get(board.projectId, board.documentId); await canvasApi.save(board.projectId, board.documentId, doc.revision, { ...doc.content, name }); await client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] }); } catch (error) { onError((error as Error).message); } }} /></label>
 <label>Image workflow<select aria-label="Image workflow" value={profile} disabled={saving || uploading || board.archived} onChange={e => { const next = { ...form, activeProfile: e.target.value as ImageProfile }; setForm(next); void save(next); }}>{imageRecipes.map(id => <option key={id} value={id}>{canvasProfiles[id].name}</option>)}</select></label>
 <fieldset disabled={saving || uploading || board.archived}>
 <label>{edit ? "Edit instructions" : "Image prompt"}<textarea aria-label="Image recipe prompt" rows={6} value={draft.prompt} placeholder={edit ? "Describe the changes. Use <image1>, <image2> to identify references…" : "Describe the subject, composition, light and style…"} onChange={e => update({ prompt: e.target.value })} /></label>
 {edit ? <><div className="h3-inputs">{draft.inputs.map((input, index) => <div className="h3-input" key={input.id}><img src={api.assetContentUrl(input.assetId)} alt={`Image ${input.token}`} /><div><strong>{index === 0 ? "Source · <image1>" : `<image${input.token}>`}</strong><small>{label(assets.find(a => a.id === input.assetId))}</small><button className="text-button" onClick={() => { if (index !== draft.inputs.length - 1 || new RegExp(`<image\\s*${input.token}>`, "i").test(draft.prompt)) { onError("Remove the last reference first, and update its prompt label before removing it."); return; } update({ inputs: draft.inputs.filter(i => i.id !== input.id) }); }}>Remove</button></div></div>)}</div>
 <button type="button" className="secondary-button" disabled={draft.inputs.length >= 10} onClick={() => setPicker(p => !p)}>Choose input image</button><button type="button" className="secondary-button" disabled={draft.inputs.length >= 10} onClick={() => upload.current?.click()}>{uploading ? "Uploading…" : "Upload input image"}</button>
 <input ref={upload} type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label="Upload edit image" hidden onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; setUploading(true); try { const asset = await api.uploadAsset(file, { project_id: board.projectId, role: "reference" }); bind(asset); await client.invalidateQueries({ queryKey: ["assets"] }); } catch (error) { onError((error as Error).message); } finally { setUploading(false); } }} />
 {picker ? <div className="h3-asset-picker" aria-label="Edit input gallery">{assets.filter(a => a.kind === "image" && a.role !== "derivative").map(asset => <button key={asset.id} type="button" title={label(asset)} onClick={() => bind(asset)}><img src={api.assetContentUrl(asset.id)} alt={label(asset)} loading="lazy" /><span>{label(asset)}</span></button>)}</div> : null}
 <label className="image-recipe-check"><input type="checkbox" checked={draft.followSource} onChange={e => update({ followSource: e.target.checked })} />Follow source image size</label>
 <label>Reference image sizing<select aria-label="Reference image sizing" value={draft.referenceResolution} onChange={e => update({ referenceResolution: Number(e.target.value) as 0 | 1024 | 2048 })}><option value={0}>Keep original · align to 32 px</option><option value={1024}>1 MP · preserve aspect</option><option value={2048}>4 MP · preserve aspect</option></select></label><small>Image 1 defines the source canvas. Additional images are pinned references, not masks. Follow source preserves its aspect ratio.</small></> : null}
 {!edit || !draft.followSource ? <><label>Output aspect<select aria-label="Image output aspect" value={draft.preset} onChange={e => update({ preset: e.target.value as ImageDraft["preset"] })}>{(engine.data?.presets ?? [{ id: "square", name: "1:1" }, { id: "poster", name: "2:3" }, { id: "photo", name: "3:2" }, { id: "portrait", name: "3:4" }, { id: "standard", name: "4:3" }, { id: "vertical", name: "9:16" }, { id: "wide", name: "16:9" }, { id: "ultrawide", name: "21:9" }]).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
 {profile === IMAGE_QWEN || edit ? <label>Output size<select value={draft.megapixels} onChange={e => update({ megapixels: Number(e.target.value) as 1 | 4 })}><option value={1}>1 MP</option><option value={4}>4 MP · native 2K square</option></select></label> : <small>1 MP · imported recipe size</small>}</> : null}
 {profile === IMAGE_FLUX || profile === IMAGE_KREA ? <label className="image-recipe-check"><input type="checkbox" aria-label="Expand prompt locally" checked={draft.enhance} onChange={e => update({ enhance: e.target.checked })} />Expand prompt locally</label> : null}
 {profile === IMAGE_KREA ? <><label className="image-recipe-check"><input type="checkbox" checked={draft.styleEnabled} onChange={e => update({ styleEnabled: e.target.checked })} />Style LoRA</label>{draft.styleEnabled ? <><label>Style LoRA filename<input value={draft.styleLora} onChange={e => update({ styleLora: e.target.value })} /></label><label>Style strength<input type="number" min={-2} max={2} step={.05} value={draft.styleStrength} onChange={e => update({ styleStrength: Number(e.target.value) })} /></label><label>Style cue<input value={draft.styleText} onChange={e => update({ styleText: e.target.value })} /></label></> : null}</> : null}
 <details><summary>Generation settings</summary><label>Seed<input aria-label="Image seed" value={draft.seed ?? ""} inputMode="numeric" placeholder="Random once per generation" onChange={e => { const value = e.target.value.trim(); if (value && (!/^\d+$/.test(value) || BigInt(value) > BigInt("18446744073709551615"))) { onError("Seed must be an unsigned 64-bit integer"); return; } update({ seed: value || null }); }} /></label><label>Steps<input aria-label="Image steps" type="number" min={1} max={150} value={draft.steps} onChange={e => update({ steps: Number(e.target.value) })} /></label><label>CFG<input type="number" min={0} max={20} step={.1} value={draft.cfg} onChange={e => update({ cfg: Number(e.target.value) })} /></label>
 {profile !== IMAGE_KREA ? <label>Negative prompt<textarea rows={2} value={draft.negativePrompt} onChange={e => update({ negativePrompt: e.target.value })} /><small>Negative conditioning has no guidance effect at CFG 1.</small></label> : <small>Krea Turbo uses zeroed negative conditioning.</small>}<p className="canvas-help">euler / simple · denoise 1 · one output. Model and encoder settings follow the registered workflow. Enhancement is a visible local recipe option; history retains its actual resulting prompt.</p></details>
 </fieldset>
 {baseRevision !== board.revision && dirty ? <p role="alert">This board changed elsewhere. <button onClick={() => { setForm(board.settings.image ?? imageRecipeDefaults()); setBaseRevision(board.revision); }}>Reload saved draft</button></p> : null}
 <button className="secondary-button" disabled={!dirty || saving || uploading || board.archived} onClick={() => void save()}><Save size={15} />{saving ? "Saving…" : dirty ? "Save image draft" : "Draft saved"}</button>
 {status && !status.ready ? <p className="form-error">{status.issues.join(" · ")}</p> : null}{engine.isError ? <button onClick={() => void engine.refetch()}>Retry workflow check</button> : null}
 {board.jobs.map(job => <div className="moss-job" key={job.id}><strong>{job.statusMessage}</strong>{job.status === "queued" ? <><button onClick={() => void canvasApi.start(board.projectId, board.documentId, job.id).catch(error => onError(error.message))}>Start worker</button><button onClick={() => void mossApi.cancel(board.projectId, board.id, job.jobId).then(() => client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] })).catch(error => onError(error.message))}>Cancel queued job</button></> : null}</div>)}
 <button className="text-button" onClick={async () => { if (!confirm(board.archived ? "Restore this board?" : "Archive this board? Its drafts and results are retained.")) return; try { await mossApi.save(board.projectId, board, board.settings, !board.archived); await client.invalidateQueries({ queryKey: ["moss-workspace", board.projectId] }); } catch (error) { onError((error as Error).message); } }}>{board.archived ? "Restore board" : "Archive board"}</button>
 </div>;
}

function ImageRecipeViewer({ board, assetId, assets, onError }: { board: MossBoard; assetId: string; assets: Asset[]; onError: (value: string) => void }) {
 const asset = assets.find(a => a.id === assetId);
 const [viewport, setViewport] = useWorkspaceState<CanvasViewport>(`image-recipe:${board.id}:view:${assetId}`, { x: 0, y: 0, scale: 0 });
 const [fit, setFit] = useState(0);
 const content = { ...emptyCanvas(), artboard: { preset: "square", width: asset?.width ?? board.artboard.width, height: asset?.height ?? board.artboard.height } };
 return <div className="image-recipe-stage"><button className="secondary-button image-recipe-fit" onClick={() => setFit(f => f + 1)}>Fit image</button><CanvasStage content={content} selectedId={null} tool="pan" drawParent={null} viewport={viewport} onViewport={setViewport} fitToken={fit} onSelect={() => {}} onRect={() => {}} onDraw={() => {}} onError={onError} readOnly imageUrl={api.assetContentUrl(assetId)} showLayout={false} showResult onSize={() => {}} /></div>;
}

export function ImageRecipeEditor({ board, assets, projectId, onExit, onGenerate, onVideo, ...hosts }: CanvasHosts & { board: MossBoard; assets: Asset[]; projectId: string; onExit: () => void; onGenerate: () => Promise<void>; onVideo: () => void }) {
 const client = useQueryClient(), narrow = useCanvasNarrow(), [open, setOpen] = useState(!narrow), [tab, setTab] = useState<CanvasUtilityTab>("board"), [error, setError] = useState("");
 const { form, uploading } = useImageDraft(board), profile = form.activeProfile, draft = form.drafts[profile];
 const doc = useQuery({ queryKey: ["canvas", projectId, board.documentId], queryFn: () => canvasApi.get(projectId, board.documentId), refetchInterval: 2500 });
 const result = doc.data?.generations.find(g => g.id === doc.data?.activeGenerationId), assetId = result?.assetIds[0], inputKey = JSON.stringify([profile, draft.inputs]);
 const [display, setDisplay] = useState({ kind: "result", inputKey, resultId: result?.id });
 if (display.resultId !== result?.id) setDisplay({ kind: "result", inputKey, resultId: result?.id });
 const showInputs = !assetId || (display.resultId === result?.id && (display.kind === "inputs" || display.inputKey !== inputKey));
 async function save(settings: BoardSettings) { const saved = await mossApi.save(projectId, board, settings); client.setQueryData<import("@/lib/moss-workspace").ProjectWorkspace>(["moss-workspace", projectId], old => old ? { ...old, boards: old.boards.map(b => b.id === saved.id ? saved : b) } : old); await client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }); }
 return <section className="canvas-workspace canvas-refined h3-editor image-recipe-editor" aria-label="Image board editor"><header className="canvas-header"><button className="icon-button" aria-label="Back to boards" onClick={onExit}><ArrowLeft size={17} /></button><div><strong>{board.name}</strong><small>{canvasProfiles[profile].name}</small></div><button className="icon-button" aria-label="Open Image settings" onClick={() => setOpen(o => !o)}><PanelRightOpen size={17} /></button><button className="primary-button" disabled={uploading || Boolean(board.jobs.length) || board.archived} onClick={() => void onGenerate().catch(e => setError(e.message))}><Sparkles size={15} />{board.jobs[0]?.statusMessage ?? (profile === IMAGE_EDIT ? "Generate edit" : "Generate image")}</button></header>
 {error || board.latest?.error ? <div className="canvas-notice is-error" role="alert">{error || board.latest?.error}</div> : null}
 <div className="moss-body"><main className="image-recipe-main">
 {assetId ? <nav className="h3-view-tabs" aria-label="Image preview"><button className="secondary-button" aria-pressed={showInputs} onClick={() => setDisplay({ kind: "inputs", inputKey, resultId: result?.id })}>Input images</button><button className="secondary-button" aria-pressed={!showInputs} onClick={() => setDisplay({ kind: "result", inputKey, resultId: result?.id })}>Generated image</button></nav> : null}
 {assetId && !showInputs ? <><ImageRecipeViewer key={assetId} board={board} assetId={assetId} assets={assets} onError={setError} /><div className="image-recipe-result-actions"><a href={api.assetContentUrl(assetId)} download><Download size={15} /> Download</a><button className="text-button" onClick={onVideo}>Create video board from result</button><small>{String(result?.provenance.profileName ?? "Image")}</small></div></> : draft.inputs.length === 1 ? <ImageRecipeViewer key={draft.inputs[0].assetId} board={board} assetId={draft.inputs[0].assetId} assets={assets} onError={setError} /> : draft.inputs.length ? <div className="h3-input-preview is-multiple">{draft.inputs.map(input => <figure key={input.id}><img src={api.assetContentUrl(input.assetId)} alt={`Image ${input.token} preview`} /><figcaption>{`<image${input.token}>`}</figcaption></figure>)}</div> : <div className="h3-empty"><ImagePlus size={42} /><h3>{profile === IMAGE_EDIT ? "Give an image a new direction." : "A fresh image starts with an idea."}</h3><p>{profile === IMAGE_EDIT ? "Pin the source image and describe the changes." : "Describe the subject, choose the image workflow and generate."}</p><button className="secondary-button" onClick={() => setOpen(true)}>Open image settings</button></div>}
 </main><CanvasUtilityPanel open={open} tab={tab} onTabChange={value => { setTab(value); setOpen(true); }} onClose={() => setOpen(false)} context={`Image board: ${board.name} · ${canvasProfiles[profile].name}`} primary={<ImageRecipeControls board={board} assets={assets} onChange={save} onError={setError} />} history={<div className="h3-history">{doc.data?.generations.map(g => <article key={g.id}><strong>{String(g.provenance.profileName ?? "Image")}</strong><small>{g.status} · seed {g.seed}</small>{g.assetIds.map(id => <button className="image-recipe-history-image" key={id} onClick={async () => { await canvasApi.select(projectId, board.documentId, g.id); await doc.refetch(); }}><img src={api.assetContentUrl(id)} alt={String(g.provenance.profileName ?? "Saved result")} loading="lazy" /></button>)}{g.error ? <p>{g.error}</p> : null}<details><summary>Prompt and recipe</summary><p>{String(g.provenance.steps)} steps · CFG {String(g.provenance.cfg)} · {String(g.provenance.actualWidth ?? g.provenance.width)} × {String(g.provenance.actualHeight ?? g.provenance.height)}</p><pre>{String(g.provenance.conditioningPrompt ?? "")}</pre>{g.provenance.effectiveConditioningPrompt ? <><small>Actual conditioning prompt</small><pre>{String(g.provenance.effectiveConditioningPrompt)}</pre></> : null}</details></article>)}</div>} hosts={hosts} /></div>
 <footer className="canvas-footer"><span>{JSON.stringify(form) === JSON.stringify(board.settings.image) ? "Image draft saved" : "Unsaved image draft"}</span><span>{board.jobs[0]?.statusMessage ?? "Ready"}</span></footer></section>;
}

export function ImageRecipeInputPreview({ board }: { board: MossBoard }) {
 const { form } = useImageDraft(board), input = form.drafts[form.activeProfile].inputs[0];
 return input ? <div className="moss-preview"><img className="moss-image-artwork" src={api.assetContentUrl(input.assetId)} alt="Pinned edit source" /></div> : <div className="moss-preview h3-empty"><ImagePlus size={28} /><span>{canvasProfiles[form.activeProfile].name}</span><small>Describe an image, or open to choose inputs.</small></div>;
}
