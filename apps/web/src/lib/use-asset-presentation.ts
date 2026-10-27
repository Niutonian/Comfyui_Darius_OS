"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "./api-client";
import type { Asset, Message } from "./types";

export type PlaybackControl = { id: string; action: "play" | "pause" | "stop" | "restart" | "mute" | "unmute" | "seek"; assetId: string; seconds?: number };
type Gallery = { assets: Asset[]; index: number; mode: "gallery" | "viewer" };

export function useAssetPresentation(projectId: string | null, conversationId: string | null, visible: boolean) {
  const [gallery, setGalleryState] = useState<Gallery | null>(null);
  const [playback, setPlayback] = useState<PlaybackControl | null>(null);
  const galleryRef = useRef(gallery);
  function setGallery(next: Gallery | null | ((state: Gallery | null) => Gallery | null)) {
    const value = typeof next === "function" ? next(galleryRef.current) : next;
    galleryRef.current = value;
    setGalleryState(value);
  }
  const [error, setError] = useState("");
  const scope = useRef({ projectId, conversationId, visible });
  const token = useRef(0);
  const seen = useRef(new Set<string>());
  // This external modal must close immediately when its owning UI scope changes.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { scope.current = { projectId, conversationId, visible }; token.current++; setGallery(null); setPlayback(null); setError(""); seen.current.clear(); }, [projectId, conversationId, visible]);
  useEffect(() => () => { token.current++; }, []);
  function close() { token.current++; setGallery(null); setPlayback(null); }
  async function present(message: Message) {
    const current = scope.current;
    if (!current.visible || !current.projectId || message.role !== "assistant" || message.conversation_id !== current.conversationId || seen.current.has(message.id)) return;
    const actions = message.metadata.presentation_actions;
    if (!Array.isArray(actions) || !actions.length) return;
    seen.current.add(message.id);
    if (seen.current.size > 256) seen.current.delete(seen.current.values().next().value!);
    const receipt = ++token.current; setError("");
    try {
      for (const action of actions.slice(0, 8)) {
        if (!action || typeof action !== "object" || action.project_id !== current.projectId) throw new Error("This preview does not belong to the active project.");
        if (["open", "gallery", "select"].includes(action.action)) {
          const ids: unknown = action.asset_ids;
          if (!Array.isArray(ids) || !ids.length || ids.length > (action.action === "open" ? 12 : 48) || ids.some((id) => typeof id !== "string" || !id || id.length > 100)) throw new Error("The asset preview request is invalid.");
          const requested = [...new Set(ids as string[])];
          const currentAssets = galleryRef.current?.assets;
          if (action.action === "select" && (!currentAssets || currentAssets.map(asset => asset.id).join("|") !== requested.join("|"))) throw new Error("The visible gallery changed. Open it again before selecting a number.");
          const assets = action.action === "select" && currentAssets ? currentAssets : await Promise.all(requested.map((id) => api.asset(id)));
          if (token.current !== receipt) return;
          if (assets.some((asset, index) => asset.id !== requested[index] || asset.project_id !== current.projectId || asset.role === "derivative" || !["image", "video", "audio"].includes(asset.kind))) throw new Error("The original asset is unavailable in this project.");
          const index = action.action === "select" ? action.index : 0;
          if (!Number.isInteger(index) || index < 0 || index >= assets.length) throw new Error("Choose a numbered item in the visible gallery.");
          if (action.autoplay !== undefined && typeof action.autoplay !== "boolean") throw new Error("Invalid playback request.");
          if (action.autoplay && !["video", "audio"].includes(assets[index].kind)) throw new Error("Only videos or audio can be played.");
          setGallery({ assets, index, mode: action.action === "gallery" ? "gallery" : "viewer" });
          setPlayback(action.autoplay ? { id: `${message.id}:${action.id ?? index}`, assetId: assets[index].id, action: "play" } : null);
        } else if (action.action === "close") { setGallery(null); setPlayback(null); }
        else if (action.action === "back") { setGallery(state => state ? { ...state, mode: "gallery" } : null); setPlayback(null); }
        else if (action.action === "next" || action.action === "previous") {
          const step = action.action === "next" ? 1 : -1;
          setGallery((state) => state ? { ...state, mode: "viewer", index: Math.max(0, Math.min(state.assets.length - 1, state.index + step)) } : null);
          setPlayback(null);
        } else if (["play", "pause", "stop", "restart", "mute", "unmute", "seek"].includes(action.action)) {
          const state = galleryRef.current, asset = state?.assets[state.index];
          if (!state || state.mode !== "viewer" || !asset || !["video", "audio"].includes(asset.kind) || !Array.isArray(action.asset_ids) || action.asset_ids.length !== 1 || action.asset_ids[0] !== asset.id) throw new Error("The selected video changed. Please repeat the control for the current video.");
          if (action.action === "seek" && (typeof action.seconds !== "number" || !Number.isFinite(action.seconds) || Math.abs(action.seconds) > 600)) throw new Error("Invalid video seek request.");
          setPlayback({ id: `${message.id}:${action.id ?? action.action}`, assetId: asset.id, action: action.action, seconds: action.seconds });
        } else throw new Error("Unknown asset preview action.");
      }
    } catch (reason) { if (token.current === receipt) { setGallery(null); setError(reason instanceof Error ? reason.message : "Could not open the original asset."); } }
  }
  return { gallery, playback, error, present, close, context: () => {
    const state = galleryRef.current;
    return state ? { asset_ids: state.assets.map(asset => asset.id), index: state.index, mode: state.mode } : null;
  }, browse: () => { setPlayback(null); setGallery(state => state ? { ...state, mode: "gallery" } : null); }, select: (asset: Asset) => { setPlayback(null); setGallery((state) => {
    const index = state?.assets.findIndex((item) => item.id === asset.id) ?? -1;
    return state && index >= 0 ? { ...state, index, mode: "viewer" } : state;
  }); } };
}
