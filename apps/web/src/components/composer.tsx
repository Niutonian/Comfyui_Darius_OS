"use client";
/* eslint-disable @next/next/no-img-element -- object URL previews cannot use next/image */


import { ArrowUp, Camera, Check, ChevronDown, Keyboard as KeyboardIcon, Mic, Paperclip, RotateCcw, Square, X } from "lucide-react";
import { ChangeEvent, KeyboardEvent, ReactNode, useEffect, useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/queries";
import { useDariusStore } from "@/lib/store";
import type { Asset } from "@/lib/types";
import { microphoneProblem } from "@/lib/voice-connection";
import { useWorkspaceState } from "@/lib/workspace-session";

type CaptureMode = "audio" | "video" | null;
type Attachment = {
  id: string;
  file: File;
  source: "file" | "audio" | "video";
  previewUrl: string;
  status: "uploading" | "ready" | "error";
  progress: number;
  asset?: Asset;
  error?: string;
  controller: AbortController;
};

export function Composer({ disabled, projectId, draftKey, targetLabel, onSubmit, toolbarActions, beforeComposer, compact = false, onBeginTyping }: {
  draftKey?: string;
  targetLabel?: string;
  compact?: boolean;
  onBeginTyping?: () => void;
  disabled?: boolean;
  toolbarActions?: ReactNode;
  beforeComposer?: ReactNode;
  projectId: string | null;
  onSubmit: (text: string, assets: Asset[]) => void;
}) {
  const queryClient = useQueryClient();
  const contextView = useDariusStore((state) => state.view);
  const contextProject = useDariusStore((state) => state.projects.find((item) => item.id === state.activeProjectId));
  const idPrefix = useId();
  const attachmentSequence = useRef(0);
  const [text, setText] = useWorkspaceState(`composer:${draftKey ?? projectId}:text`, "");
  const [typingOpen, setTypingOpen] = useState(false);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const [attachments, setAttachments] = useWorkspaceState<Attachment[]>(`composer:${draftKey ?? projectId}:attachments`, []);
  const [captureMode, setCaptureMode] = useState<CaptureMode>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const expanded = !compact || typingOpen || attachments.length > 0 || captureMode !== null;
  const toggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (compact && typingOpen && !disabled) messageInput.current?.focus({ preventScroll: true });
  }, [compact, typingOpen, disabled]);

  useEffect(() => () => {
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  function updateAttachment(id: string, patch: Partial<Attachment>) {
    setAttachments((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  function stageFile(file: File, source: Attachment["source"]) {
    if (!projectId) return;
    const id = `${idPrefix}-${++attachmentSequence.current}`;
    const controller = new AbortController();
    const attachment: Attachment = {
      id, file, source, controller,
      previewUrl: URL.createObjectURL(file),
      status: "uploading", progress: 0,
    };
    setAttachments((current) => current.length >= 8 ? current : [...current, attachment]);
    const upload = source === "video"
      ? api.captureWebcamWithProgress(file, { project_id: projectId }, {
          signal: controller.signal,
          onProgress: ({ percent }) => updateAttachment(id, { progress: percent }),
        }).then((capture) => capture.asset)
      : api.uploadAssetWithProgress(file, { project_id: projectId, role: source === "file" ? "reference" : "source" }, {
          signal: controller.signal,
          onProgress: ({ percent }) => updateAttachment(id, { progress: percent }),
        });
    void upload.then((asset) => {
      updateAttachment(id, { asset, status: "ready", progress: 100 });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAssets(projectId) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      updateAttachment(id, { status: "error", error: error instanceof ApiError ? error.message : "Upload failed." });
    });
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const removed = current.find((item) => item.id === id);
      removed?.controller.abort();
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((item) => item.id !== id);
    });
  }

  function retryAttachment(item: Attachment) {
    removeAttachment(item.id);
    stageFile(item.file, item.source);
  }

  function send() {
    if (!text.trim() || disabled || attachments.some((item) => item.status !== "ready")) return;
    onSubmit(text.trim(), attachments.flatMap((item) => item.asset ? [item.asset] : []));
    attachments.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setAttachments([]);
    setText("");
    setTypingOpen(false);
  }

  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const room = Math.max(0, 8 - attachments.length);
    Array.from(event.target.files ?? []).slice(0, room).forEach((file) => stageFile(file, "file"));
    event.target.value = "";
  }

  async function startCapture(mode: Exclude<CaptureMode, null>) {
    setCaptureError(null);
    const problem = microphoneProblem();
    if (problem) { setCaptureError(problem); return; }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setCaptureError("Media capture is not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: mode === "video" });
      const recorder = new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const type = mode === "video" ? "video/webm" : "audio/webm";
        const file = new File([new Blob(chunksRef.current, { type })], `darius-${mode}-${Date.now()}.webm`, { type });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (file.size) stageFile(file, mode);
        else setCaptureError("No media was captured. Please try again.");
      };
      recorder.start();
      setCaptureMode(mode);
    } catch {
      setCaptureError("Camera or microphone permission was not granted.");
    }
  }

  function stopCapture() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setCaptureMode(null);
  }

  function retake(item: Attachment) {
    const mode = item.source === "file" ? null : item.source;
    removeAttachment(item.id);
    if (mode) void startCapture(mode);
  }

  function keyboardSubmit(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      send();
    }
  }

  const waiting = attachments.some((item) => item.status === "uploading");
  const failed = attachments.some((item) => item.status === "error");

  return (
    <section aria-label="Talk to Darius" className={`composer-wrap ${compact ? "mobile-composer " + (expanded ? "is-writing" : "is-collapsed") : ""}`}>
      {beforeComposer}
      {compact ? <button ref={toggle} className="mobile-compose-toggle icon-button" aria-label={expanded ? "Hide text input" : text ? "Continue writing" : "Type a message"} title={expanded ? "Hide text input" : text ? "Continue writing" : "Type a message"} aria-expanded={expanded} disabled={!projectId} onClick={() => {
        if (expanded) { messageInput.current?.blur(); setTypingOpen(false); toggle.current?.focus({ preventScroll: true }); }
        else { onBeginTyping?.(); setTypingOpen(true); }
      }} type="button">{expanded ? <ChevronDown size={22} /> : <KeyboardIcon size={22} />}{!expanded ? <span className="compact-command-label">{text ? "Continue draft" : "Ask Darius"}<small>{contextProject?.name ?? "Choose a project"}</small></span> : null}{!expanded && text ? <i className="mobile-draft-dot" aria-label="Unsent draft" /> : null}</button> : null}
      {attachments.length ? <div className="attachment-review" aria-label="Media ready to send">
        {attachments.map((item) => <article className="attachment-card" key={item.id}>
          <div className="attachment-preview">
            {item.file.type.startsWith("image/") ? <img alt={`Preview of ${item.file.name}`} src={item.previewUrl} /> : item.file.type.startsWith("video/") ? <video aria-label={`Preview of ${item.file.name}`} controls src={item.previewUrl} /> : <audio aria-label={`Preview of ${item.file.name}`} controls src={item.previewUrl} />}
          </div>
          <div className="attachment-copy"><strong title={item.file.name}>{item.file.name}</strong><small>{(item.file.size / 1024 / 1024).toFixed(1)} MB · {item.source === "file" ? "attachment" : `${item.source} capture`}</small>
            {item.status === "uploading" ? <><span>Uploading {item.progress}%</span><span aria-label={`${item.file.name} upload progress`} aria-valuemax={100} aria-valuemin={0} aria-valuenow={item.progress} className="upload-progress" role="progressbar"><i style={{ width: `${item.progress}%` }} /></span></> : null}
            {item.status === "ready" ? <span className="upload-ready"><Check size={12} /> Immutable asset ready</span> : null}
            {item.status === "error" ? <span className="upload-error" role="alert">{item.error}</span> : null}
          </div>
          <div className="attachment-actions">
            {item.status === "error" ? <button aria-label={`Retry ${item.file.name}`} className="icon-button" onClick={() => retryAttachment(item)} type="button"><RotateCcw size={14} /></button> : null}
            {item.source !== "file" ? <button aria-label={`Retake ${item.file.name}`} className="icon-button" onClick={() => retake(item)} type="button"><Camera size={14} /></button> : null}
            <button aria-label={`Remove ${item.file.name}`} className="icon-button" onClick={() => removeAttachment(item.id)} type="button"><X size={14} /></button>
          </div>
        </article>)}
      </div> : null}
      {captureMode ? <p className="capture-status" role="status">Recording {captureMode}. Review and retake the clip before sending.</p> : null}
      {captureError ? <p className="capture-error" role="alert">{captureError}</p> : null}
      <div className="composer" hidden={!expanded} style={expanded ? undefined : { display: "none" }}>
        <div className="composer-heading">
          <p className="composer-context" title={targetLabel}>To: {contextProject?.name ?? "Choose a project"}{targetLabel ? ` · ${targetLabel}` : ""}<span className="composer-origin"> · {contextView[0]?.toUpperCase()}{contextView.slice(1)}</span></p>
          {projectId ? <small className="composer-helper-label">Ideas and prompts</small> : null}
        </div>
        <textarea ref={messageInput} onBlur={(event) => { if (compact && !text.trim() && !event.currentTarget.closest(".composer-wrap")?.contains(event.relatedTarget as Node)) setTypingOpen(false); }} aria-label="Message Darius" disabled={disabled} onChange={(event) => setText(event.target.value)} onKeyDown={keyboardSubmit} placeholder={disabled ? (projectId ? "Your conversation continues above…" : "Create or choose a project to begin…") : compact ? "Message Darius…" : "Ask Darius, explore an idea, or describe what to create…"} rows={compact ? 1 : 2} value={text} />
        <div className="composer-tools"><div>
          <input accept="image/*,video/*,audio/*" hidden multiple onChange={addFiles} ref={fileInput} type="file" />
          <button aria-label="Attach media" className="icon-button" disabled={disabled || attachments.length >= 8} onClick={() => fileInput.current?.click()} type="button"><Paperclip size={18} /></button>
          <button aria-label={captureMode === "audio" ? "Stop microphone recording" : "Record with microphone"} className={`icon-button ${captureMode === "audio" ? "recording" : ""}`} disabled={disabled || (captureMode !== null && captureMode !== "audio")} onClick={() => captureMode === "audio" ? stopCapture() : void startCapture("audio")} type="button">{captureMode === "audio" ? <Square size={16} /> : <Mic size={18} />}</button>
          <button aria-label={captureMode === "video" ? "Stop webcam recording" : "Record with webcam"} className={`icon-button ${captureMode === "video" ? "recording" : ""}`} disabled={disabled || (captureMode !== null && captureMode !== "video")} onClick={() => captureMode === "video" ? stopCapture() : void startCapture("video")} type="button">{captureMode === "video" ? <Square size={16} /> : <Camera size={18} />}</button>
          {toolbarActions}
        </div><span className="composer-hint">{waiting ? "Uploading media…" : failed ? "Resolve upload errors" : "Ctrl ↵"}</span><button aria-label="Send message" className="send-button" disabled={disabled || !text.trim() || waiting || failed} onClick={send} type="button"><ArrowUp size={19} /></button></div>
      </div>
    </section>
  );
}
