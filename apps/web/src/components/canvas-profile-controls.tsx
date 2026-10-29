"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { definitiveGenerationError, canvasApi, type CanvasGeneration } from "@/lib/canvas-api";
import { canvasProfiles, canvasSeed, switchCanvasProfile, MOSS, FIBO_FAST, LEGACY_FIBO_FAST, FIBO_DEV, type CanvasProfile } from "@/lib/canvas-profile";
import { loadCanvasIntent, saveCanvasIntent, type CanvasIntent } from "@/lib/canvas-intent";
import type { MossBoard, BoardSettings } from "@/lib/moss-workspace";

export function CanvasProfileControls({ board, onChange, onError }: { board: MossBoard; onChange: (settings: BoardSettings) => Promise<unknown>; onError: (message: string) => void }) {
  const [saving, setSaving] = useState(false);
  const profile = board.settings.adapterVersion, fibo = profile !== MOSS;
  async function update(settings: BoardSettings) {
    setSaving(true);
    try { await onChange(settings); } catch (error) { onError(error instanceof Error ? error.message : "Could not save workflow settings"); }
    finally { setSaving(false); }
  }
  return <div className="canvas-profile-controls">
    <label>Workflow<select aria-label="Board workflow" disabled={saving || board.archived} value={fibo ? "fibo" : "moss"} onChange={e => void update(switchCanvasProfile(board.settings, e.target.value === "fibo" ? FIBO_DEV : MOSS))}><option value="moss">MOSS</option><option value="fibo">FIBO</option></select></label>
    {fibo ? <><label>FIBO preset<select aria-label="FIBO preset" value={profile} disabled={saving || board.archived} onChange={e => void update(switchCanvasProfile(board.settings, e.target.value as CanvasProfile))}><option value={FIBO_FAST}>Fast preview · Turbo · experimental</option><option value={FIBO_DEV}>Dev render</option></select></label><p className="canvas-help">{board.artboard.width} × {board.artboard.height} · {canvasProfiles[profile].settings}. {profile === FIBO_FAST ? "Four-step sampling with Turbo weights; this text-to-image preview remains experimental." : "Generate directly, or render a saved preview with Dev."}</p></> : null}
    <label>Seed<input key={`${board.id}:${board.revision}`} aria-label="Board seed" defaultValue={board.settings.seed ?? ""} disabled={saving || board.archived} inputMode="numeric" placeholder="Random once per request" onBlur={e => { try { const seed = canvasSeed(e.target.value.trim(), profile); if (seed !== board.settings.seed) void update({ ...board.settings, seed }); } catch (error) { onError((error as Error).message); } }} /></label>
    {fibo ? <details><summary>Actual model & sampling</summary><p className="canvas-help">{profile === FIBO_FAST ? "fibo2_edit_turbo_int8_convrot.safetensors" : "fibo2_dev_int8_convrot.safetensors"}<br />qwen3vl_4b_bf16.safetensors<br />flux2-vae.safetensors<br />{canvasProfiles[profile].settings} · denoise 1 · batch 1 · empty negative prompt. Whole-image generation; pinned visual notes are not conditioning inputs.</p></details> : null}
  </div>;
}

export function CanvasGenerationDetails({ result, board, projectId, generations, onError }: { result: CanvasGeneration; board?: MossBoard; projectId: string; generations: CanvasGeneration[]; onError: (message: string) => void }) {
  const client = useQueryClient(), [busy, setBusy] = useState(false), [accepted, setAccepted] = useState<CanvasGeneration>();
  const p = result.provenance, profile = p.profileId as CanvasProfile | undefined;
  const model = (p.models as Record<string, Record<string, unknown>> | undefined)?.diffusion?.unet_name;
  const dev = accepted ? generations.find(g => g.id === accepted.id) ?? accepted : generations.find(g => g.provenance.promotedFromGenerationId === result.id);
  const compatible = p.compilerVersion === "fibo-layout-string-v1";
  const eligible = (profile === FIBO_FAST || profile === LEGACY_FIBO_FAST) && compatible && result.status === "completed" && result.assetIds.length > 0 && p.conditioningPromptVerified === true && Boolean(p.documentSnapshot) && Boolean(board) && !board?.archived;
  async function promote() {
    if (!board || busy) return;
    setBusy(true);
    const scope = `${board.documentId}:promote:${result.id}`;
    let intent: CanvasIntent | undefined;
    try {
      intent = loadCanvasIntent(projectId, scope) ?? { documentId: board.documentId, revision: result.revision, seed: result.seed, key: crypto.randomUUID(), boardId: board.id, boardRevision: board.revision, profileId: FIBO_DEV, promotedFromGenerationId: result.id };
      saveCanvasIntent(projectId, scope, intent);
      const receipt = await canvasApi.generate(projectId, board.documentId, intent.revision, intent.key, intent.seed, { boardId: intent.boardId!, boardRevision: intent.boardRevision!, profileId: FIBO_DEV, promotedFromGenerationId: result.id });
      setAccepted(receipt);
      await Promise.all([client.invalidateQueries({ queryKey: ["canvas", projectId, board.documentId] }), client.invalidateQueries({ queryKey: ["moss-workspace", projectId] }), client.invalidateQueries({ queryKey: ["jobs"] })]);
    } catch (error) { if (definitiveGenerationError(error)) saveCanvasIntent(projectId, scope); onError(error instanceof Error ? error.message : "Dev submission failed. The preview and draft are retained."); }
    finally { setBusy(false); }
  }
  return <div className="canvas-generation-details">
    <small>{String(p.profileName ?? (profile && canvasProfiles[profile] ? canvasProfiles[profile].name : "MOSS"))}{p.promotedFromGenerationId ? " · from saved preview" : ""}</small>
    {profile ? <details><summary>Generation details</summary><p className="canvas-help">{String(p.steps)} steps · CFG {String(p.cfg)} · {String(p.width)} × {String(p.height)}<br />{String(model ?? "Model identity unavailable")}<br />Layout r{result.revision} · seed {result.seed}<br />Prompt receipt: {p.conditioningPromptVerified ? "verified" : "awaiting execution"}</p><details><summary>Exact conditioning prompt</summary><pre>{String(p.conditioningPrompt ?? "Unavailable")}</pre></details></details> : null}
    {profile === FIBO_FAST || profile === LEGACY_FIBO_FAST ? <><button className="secondary-button" disabled={!eligible || busy || Boolean(dev && ["queued", "running", "cancelling"].includes(dev.status))} onClick={() => void promote()}>{busy ? "Preparing Dev…" : dev && ["queued", "running", "cancelling"].includes(dev.status) ? `Dev ${dev.status}` : dev ? "Render another Dev version" : "Render this preview with Dev"}</button><p className="canvas-help">Uses the same saved layout and seed; the image may change.{!eligible ? " Available after a completed preview with a verified prompt receipt." : ""}</p></> : null}
  </div>;
}
