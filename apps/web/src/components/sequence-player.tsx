"use client";
/* eslint-disable @next/next/no-img-element -- native media playback uses project-scoped URLs */
import { Maximize2, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import { assetName, clipAt, pictureClips, sequenceDuration, sourceTime } from "@/lib/edit-timeline";
import type { Asset, TimelineClip, TimelineTrack } from "@/lib/types";
import { useDariusStore } from "@/lib/store";
import { audioGain } from "@/lib/timeline-audio";

export const editClock = (value: number) => `${String(Math.floor(Math.max(0, value) / 60)).padStart(2, "0")}:${(Math.max(0, value) % 60).toFixed(1).padStart(4, "0")}`;

function AudioClip({ asset, clip, time, playing, onError }: { asset: Asset; clip: TimelineClip; time: number; playing: boolean; onError: (message: string) => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  const active = time >= clip.timeline_in && time < clip.timeline_out && !clip.muted;
  const latest = useRef({ time, playing, active });
  const failure = useRef(onError);
  useEffect(() => { latest.current = { time, playing, active }; failure.current = onError; });
  useEffect(() => {
    const element = audio.current; if (!element) return;
    let cancelled = false;
    const sync = () => {
      const state = latest.current;
      element.volume = audioGain(clip, state.time);
      if (!state.active) { element.pause(); return; }
      if (element.readyState < 1) return;
      const desired = sourceTime(clip, state.time);
      if (Math.abs(element.currentTime - desired) > (state.playing ? .2 : .001)) element.currentTime = desired;
      if (!state.playing) { element.pause(); return; }
      if (element.paused) void element.play().catch(() => { if (!cancelled) failure.current("Audio playback was blocked or failed. Press Play to retry."); });
    };
    sync(); element.addEventListener("loadedmetadata", sync);
    return () => { cancelled = true; element.removeEventListener("loadedmetadata", sync); };
  }, [time, playing, active, clip]);
  useEffect(() => { const element = audio.current; return () => { element?.pause(); }; }, []);
  return <audio ref={audio} src={api.assetContentUrl(asset.id)} preload="metadata" onError={() => { if (latest.current.active) failure.current(`Could not load audio: ${assetName(asset)}.`); }} />;
}

export function SequencePlayer({ tracks, assets, time, playing, onTime, onPlaying, issue = "" }: { tracks: TimelineTrack[]; assets: Asset[]; time: number; playing: boolean; onTime: (time: number) => void; onPlaying: (playing: boolean) => void; issue?: string }) {
  const stage = useRef<HTMLDivElement>(null), video = useRef<HTMLVideoElement>(null);
  const resolution = useDariusStore((state) => state.projects.find((project) => project.id === state.activeProjectId)?.default_resolution ?? "1920x1080");
  const [width, height] = resolution.split("x").map(Number);
  const aspect = width > 0 && height > 0 ? width / height : 16 / 9;
  const clips = pictureClips(tracks), duration = sequenceDuration(tracks);
  const active = clipAt(clips, Math.min(time, Math.max(0, duration - .00001)));
  const asset = assets.find((item) => item.id === active?.source_asset_id);
  const [error, setError] = useState("");
  const latest = useRef({ time, playing, active, asset, onTime, onPlaying, duration });
  useEffect(() => { latest.current = { time, playing, active, asset, onTime, onPlaying, duration }; });
  const fail = (message: string) => { setError(message); onPlaying(false); };
  function syncVideo() {
    const element = video.current, state = latest.current;
    if (!element || !state.active || element.readyState < 1) return;
    element.muted = Boolean(state.active.muted);
    element.volume = audioGain(state.active, state.time);
    const desired = sourceTime(state.active, state.time);
    if (Math.abs(element.currentTime - desired) > (state.playing ? .2 : .001)) element.currentTime = desired;
    if (state.playing) {
      if (element.paused) void element.play().catch(() => { if (video.current === element && latest.current.playing) { setError("Playback was blocked or the codec is unsupported. Press Play to retry, or use a browser-compatible source."); latest.current.onPlaying(false); } });
    } else element.pause();
  }
  useEffect(() => { syncVideo(); }, [time, playing, active, asset?.id]);
  useEffect(() => {
    if (!playing || issue) return;
    let frame = 0, previous = performance.now();
    const tick = (now: number) => {
      const state = latest.current;
      let next = state.time;
      if (state.asset?.kind === "video" && state.active) {
        const element = video.current;
        if (element && element.readyState >= 2 && !element.seeking && !element.paused) next = state.active.timeline_in + Math.max(0, element.currentTime - (state.active.source_in ?? 0));
        next = Math.min(next, state.active.timeline_out);
      } else next += Math.min(.1, (now - previous) / 1000);
      previous = now;
      if (next >= state.duration) { state.onTime(state.duration); state.onPlaying(false); return; }
      if (next !== state.time) state.onTime(next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, issue, active?.id, asset?.id]);
  useEffect(() => { const element = video.current; return () => { element?.pause(); }; }, [asset?.id]);
  const seek = (value: number) => { setError(""); onTime(Math.max(0, Math.min(duration, value))); };
  return <section className="desk-player" aria-label="Sequence preview">
    <div className="desk-player-heading"><span>Sequence preview</span><span>{asset ? assetName(asset) : "Black / gap"}</span></div>
    <div className="desk-screen" ref={stage}>
      <div className="desk-picture-frame" style={{ aspectRatio: aspect, width: `min(100%, ${320 * aspect}px)` }}>
      {issue ? <p role="alert">{issue}</p> : asset?.kind === "video" ? <video key={active?.id} ref={video} aria-label={`Sequence video: ${assetName(asset)}`} src={api.assetContentUrl(asset.id)} muted={Boolean(active?.muted)} playsInline preload="auto" onLoadedMetadata={syncVideo} onCanPlay={syncVideo} onEnded={() => { if (active) seek(active.timeline_out); }} onError={() => fail(`Could not play ${assetName(asset)}. Try a browser-compatible video.`)} /> : asset?.kind === "image" ? <img alt={assetName(asset)} src={api.assetContentUrl(asset.id)} onError={() => fail(`Could not load ${assetName(asset)}.`)} /> : <div className="desk-player-empty"><Play size={36} /><span>{duration ? "Black / gap" : "Add a take to start your cut"}</span></div>}
      </div>
      {error ? <p className="desk-playback-error" role="alert">{error}</p> : null}
    </div>
    <div className="desk-transport"><span className="timecode">{editClock(time)} / {editClock(duration)}</span><div><button className="icon-button" aria-label="Previous clip" type="button" onClick={() => seek([...clips].reverse().find((clip) => clip.timeline_in < time - .1)?.timeline_in ?? 0)}><SkipBack size={17} /></button><button className="play-button" aria-label={playing ? "Pause sequence" : "Play sequence"} disabled={!duration || Boolean(issue)} type="button" onClick={() => { setError(""); if (!playing && time >= duration - .001) onTime(0); onPlaying(!playing); }} >{playing ? <Pause size={19} /> : <Play size={19} />}</button><button className="icon-button" aria-label="Next clip" type="button" onClick={() => seek(clips.find((clip) => clip.timeline_in > time + .1)?.timeline_in ?? duration)}><SkipForward size={17} /></button></div><button className="icon-button" aria-label="Fullscreen sequence preview" type="button" onClick={() => { if (stage.current?.requestFullscreen) void stage.current.requestFullscreen().catch(() => setError("Fullscreen is unavailable on this browser.")); else setError("Fullscreen is unavailable on this browser."); }}><Maximize2 size={17} /></button></div>
    <label className="desk-scrubber"><span className="sr-only">Sequence position</span><input aria-label="Sequence position" type="range" min={0} max={duration || 1} step={.01} value={Math.min(time, duration)} disabled={!duration || Boolean(issue)} onChange={(event) => seek(Number(event.target.value))} /></label>
    {!issue ? tracks.filter((track) => track.kind === "audio").flatMap((track, index) => track.clips.filter((clip) => !clip.muted && time >= clip.timeline_in && time < clip.timeline_out).map((clip) => {
      const source = assets.find((item) => item.id === clip.source_asset_id);
      return source ? <AudioClip key={`${index}:${clip.id}`} asset={source} clip={clip} time={time} playing={playing} onError={fail} /> : null;
    })) : null}
    <small className="desk-sound-note">Video sound stays linked to its picture. Clip mute, volume and fades apply to preview and render.</small>
  </section>;
}
