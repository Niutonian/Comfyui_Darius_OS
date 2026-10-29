"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowDown, MessagesSquare, MessageSquarePlus, Mic, Search, Square, Settings2, Maximize2, X } from "lucide-react";
import { api } from "@/lib/api-client";
import type { Asset, Conversation, DariusMood, Message, Workflow } from "@/lib/types";
import { useDariusStore } from "@/lib/store";
import { useLocalVoiceConversation } from "@/lib/use-local-voice-conversation";
import { usePipecatVoiceConversation } from "@/lib/use-pipecat-voice-conversation";
import { useVoicePreferences } from "@/lib/voice-preferences";
import { useLiveVoiceConversation } from "@/lib/use-live-voice-conversation";
import { Composer } from "./composer";
import { AssistantReferences, ConversationImages } from "./assistant-references";
import { CreativeChatWelcome } from "./creative-message";
import { LiquidOrb } from "./liquid-orb";
import { ConversationRender } from "./conversation-render";
import { messageJobIds, RenderMessageText } from "./render-job-status";
import { AssistantTaskCard } from "./assistant-task-card";
import { ChatRecovery } from "./chat-recovery";
import { ConversationContext } from "./conversation-context";
import { ResultFollowup, type ResultAction, type ResultFollowupDraft } from "./result-followup";
import { ConversationRow } from "./conversation-row";
import { FullscreenVoice } from "./fullscreen-voice";
import { AssetViewer } from "./asset-preview";
import { VoiceGallery } from "./voice-gallery";
import { useAssetPresentation } from "@/lib/use-asset-presentation";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { MovableSurface } from "./movable-surface";
import { useMobileSheetFocus } from "@/lib/use-mobile-shell";
import { readWorkspaceValue, rememberWorkspaceValue } from "@/lib/workspace-session";

export function AssistantWorkspace({ projectId, visible, onRetry, voiceHost, workspaceHost, composerHost, stayInView, onInteract, canvasBoard, compact = false }: {
  compact?: boolean; canvasBoard?: import("@/lib/moss-workspace").SelectedBoardContext | null;
  workspaceHost?: HTMLDivElement | null;
  composerHost?: HTMLDivElement | null;
  stayInView?: boolean;
  onInteract?: () => void;
  voiceHost?: HTMLDivElement | null;
  projectId: string | null; visible: boolean; workflows: Workflow[]; workflowsLoading: boolean;
  workflowsError: Error | null; onRetry: () => void;
}) {
  const [imageTriggerHost, setImageTriggerHost] = useState<HTMLSpanElement | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamedReply, setStreamedReply] = useState("");
  const [threads, setThreads] = useState<Conversation[]>([]);
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [mobileThreadsOpen, setMobileThreadsOpen] = useState(false);
  const closeThreads = useCallback(() => setMobileThreadsOpen(false), []);
  useMobileSheetFocus(compact && visible && mobileThreadsOpen ? ".talk-thread-list" : null, closeThreads);
  const presentation = useAssetPresentation(projectId, activeThread, visible);
  const originatingMessages = useRef(new Set<string>());
  const presentReply = useRef(presentation.present);
  const stopClassicRef = useRef<() => void>(() => {});
  const stopPipecatRef = useRef<() => void>(() => {});
  const stopLiveRef = useRef<() => void>(() => {});
  useEffect(() => { presentReply.current = presentation.present; }, [presentation.present]);
  const [threadQuery, setThreadQuery] = useState("");
  const [loading, setLoading] = useState(Boolean(projectId));
  const [busy, setBusy] = useState(false);
  const [slowReply, setSlowReply] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [taskHistory, setTaskHistory] = useState<unknown>([]);
  const [error, setError] = useState("");
  const [resultDraft, setResultDraft] = useState<ResultFollowupDraft | null>(null);
  const conversation = useRef<string | null>(null);
  const [pending, setPending] = useState<Message | null>(null);
  const [taskState, setTaskState] = useState("");
  const [controlling, setControlling] = useState(false);
  const requestedControl = useRef<"pause" | "cancel" | null>(null);
  const [failedInput, setFailedInput] = useState<{ text: string; assets: Asset[]; exactReferences: boolean } | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [remoteWorking, setRemoteWorking] = useState(false);
  const [liveVoiceEnabled, setLiveVoiceEnabled] = useState(false);
  const [fullscreenVoice, setFullscreenVoice] = useState(false);
  const [fullscreenChat, setFullscreenChat] = useState(false);
  const voiceProjectName = useDariusStore((state) => state.projects.find((project) => project.id === projectId)?.name ?? "Current project");
  const inFlight = useRef(false);
  const syncDeferred = useRef(false);
  const alive = useRef(true);
  const hydrated = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);
  const scrollArea = useRef<HTMLDivElement>(null);
  const scrollContent = useRef<HTMLDivElement>(null);
  const [showLatest, setShowLatest] = useState(false);
  const followLatest = useRef(true);
  const [enterIds, setEnterIds] = useState<Set<string>>(() => new Set());

  function rememberEnter(id: string) {
    if (!hydrated.current) return;
    setEnterIds((current) => current.has(id) ? current : new Set(current).add(id));
  }

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    if (projectId) {
      void api.conversations(projectId).then(async (items) => {
        // A fresh device opens the most recently active conversation, not an old default thread.
        const remembered = readWorkspaceValue<string>(`conversation:${projectId}`);
        const current = items.find(item => item.id === remembered) ?? items[0];
        if (cancelled) return;
        setThreads(items); setLoadError(false); setError("");
        if (!current) return;
        setActiveThread(current.id);
        const history = await api.messages(current.id);
        if (cancelled) return;
        conversation.current = current.id;
        setMessages(history);
        hydrated.current = true;
        const last = history.at(-1);
        if (last?.role === "user") {
          setPending(last);
          const task = last.metadata.task as { state?: string; error?: string } | undefined;
          setTaskState(task?.state ?? "ready");
          if (task?.state === "cancelled") setPending(null);
          if (task?.state === "failed") setError(task.error || "Darius paused before completing this reply. Resume the saved task to continue.");
        }
      }).catch((err: Error) => { if (!cancelled) { setError(err.message); setLoadError(true); } })
        .finally(() => { if (!cancelled) { setLoading(false); hydrated.current = true; } });
    }
    return () => { cancelled = true; alive.current = false; };
  }, [projectId, loadAttempt]);

  useEffect(() => {
    if (!projectId || loading) return;
    let cancelled = false;
    let refreshing = false;
    let again = false;
    const refresh = async () => {
      if (inFlight.current) { syncDeferred.current = true; return; } // Keep this device's streamed reply.
      if (refreshing) { again = true; return; }
      refreshing = true;
      const id = conversation.current;
      try {
        const [items, history] = await Promise.all([api.conversations(projectId), id ? api.messages(id).catch(() => null) : Promise.resolve(null)]);
        if (cancelled || inFlight.current || conversation.current !== id) return;
        setThreads(items);
        if (id && !items.some((item) => item.id === id)) {
          stopClassicRef.current(); stopPipecatRef.current(); stopLiveRef.current();
          conversation.current = null; setActiveThread(null); setMessages([]); setPending(null);
          setRemoteWorking(false); setTaskState(""); setError("This conversation was deleted on another device. Your unsent text is kept; choose a chat or send it in a new one.");
        } else if (history) {
          // Canonical history only: never speak or open media in response to another device.
          setMessages((current) => JSON.stringify(current) === JSON.stringify(history) ? current : history);
          const last = history.at(-1);
          const task = last?.metadata.task as { state?: string } | undefined;
          setRemoteWorking(last?.role === "user" && ["running", "pause_requested"].includes(task?.state ?? ""));
        } else if (!id && items[0]) {
          // An already-open empty project can receive its first chat from another device.
          const first = items[0];
          const firstHistory = await api.messages(first.id);
          if (cancelled || inFlight.current || conversation.current !== null) return;
          conversation.current = first.id; setActiveThread(first.id); setMessages(firstHistory);
        }
      } catch { /* The sync indicator reports connection trouble; keep the last good history. */ }
      finally {
        refreshing = false;
        if (again && !cancelled) { again = false; void refresh(); }
      }
    };
    const unsubscribe = subscribeProjectRefresh(projectId, ({ full, types }) => {
      if (full || types.some((type) => type.startsWith("conversation.") || type.startsWith("assistant."))) void refresh();
    });
    if (syncDeferred.current && !inFlight.current) { syncDeferred.current = false; void refresh(); }
    return () => { cancelled = true; unsubscribe(); };
  }, [projectId, activeThread, busy, loading]);

  function scrollToLatest() {
    const area = scrollArea.current;
    if (area) area.scrollTop = area.scrollHeight;
    setShowLatest(false);
  }
  useEffect(() => {
    if (projectId && activeThread) rememberWorkspaceValue(`conversation:${projectId}`, activeThread);
  }, [projectId, activeThread]);
  useEffect(() => {
    if (!visible || loading) return;
    const frame = requestAnimationFrame(() => {
      // Opening/reparenting an embedded panel should reveal the current turn,
      // not inherit an old reading position from the full Talk workspace.
      const saved = stayInView && workspaceHost ? undefined : readWorkspaceValue<{ top: number; follow: boolean }>(`chat-scroll:${projectId}:${activeThread}`);
      followLatest.current = saved?.follow ?? true;
      if (saved && !saved.follow && scrollArea.current) scrollArea.current.scrollTop = saved.top;
      else scrollToLatest();
    });
    return () => cancelAnimationFrame(frame);
  }, [projectId, activeThread, loading, visible, workspaceHost, stayInView]);
  useEffect(() => {
    if (!visible || !followLatest.current) return;
    const frame = requestAnimationFrame(scrollToLatest);
    return () => cancelAnimationFrame(frame);
  }, [messages, loading, visible]);
  useEffect(() => {
    if (!visible || !scrollArea.current || !scrollContent.current) return;
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { if (followLatest.current) scrollToLatest(); });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(follow);
    observer?.observe(scrollArea.current); observer?.observe(scrollContent.current);
    follow();
    return () => { observer?.disconnect(); cancelAnimationFrame(frame); };
  }, [visible, workspaceHost]);
  useEffect(() => {
    if (!visible || !followLatest.current) return;
    const frame = requestAnimationFrame(scrollToLatest);
    return () => cancelAnimationFrame(frame);
  }, [streamedReply, busy, error, visible]);
  useEffect(() => {
    if (!visible || !bottom.current || !scrollArea.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setShowLatest(!entry.isIntersecting), { root: scrollArea.current });
    observer.observe(bottom.current);
    return () => observer.disconnect();
  }, [visible, workspaceHost]);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const clock = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    const timer = setTimeout(() => setSlowReply(true), 12_000);
    return () => { clearTimeout(timer); clearInterval(clock); };
  }, [busy]);
  useEffect(() => {
    if (!pending) return;
    const id = conversation.current;
    if (!id) return;
    let cancelled = false;
    let polling = false;
    const timer = setInterval(() => {
      if (polling) return;
      polling = true;
      void api.messages(id).then((items) => {
        const completed = items.find((item) => item.role === "assistant" && item.metadata.reply_to === pending.id);
        if (!cancelled && completed) {
          if (originatingMessages.current.has(pending.id)) void presentReply.current(completed);
          setMessages(items); setPending(null); setFailedInput(null); setError(""); setBusy(false);
          if (completed.metadata.workflow_id) onRetry();
        }
        const metadata = items.find((item) => item.id === pending.id)?.metadata;
        const task = metadata?.task as { state?: string; error?: string } | undefined;
        if (!cancelled && task?.state) setTaskState(task.state);
        if (!cancelled && !busy && task?.state === "failed") {
          setError(task.error || "Darius paused before completing this reply. Resume the saved task to continue.");
        }
        const activity = metadata?.tool_activity;
        const jobId = metadata?.local_render_job_id;
        if (!cancelled && originatingMessages.current.has(pending.id) && typeof jobId === "string" && !useDariusStore.getState().knownJobIds.includes(jobId)) {
          void api.job(jobId).then((job) => { if (!cancelled) useDariusStore.getState().rememberJob(job); }).catch(() => {});
        }
        if (!cancelled && activity && typeof activity === "object" && "operation" in activity && typeof activity.operation === "string") {
          setTaskHistory(Array.isArray(metadata?.activity_history) ? metadata.activity_history : [activity]);
        }
      }).catch(() => {}).finally(() => { polling = false; });
    }, 1500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [busy, pending, onRetry]);

  async function send(text: string, assets: Asset[] = [], retry = false, onDelta?: (text: string) => void, savedUser?: Message, exactReferences = false): Promise<string> {
    if (!projectId || inFlight.current || loading) throw new Error("Conversation is not ready");
    inFlight.current = true;
    followLatest.current = true; // Applies to voice turns as well as typed submissions.
    requestedControl.current = null; setTaskState("running");
    setBusy(true); setSlowReply(false); setElapsed(0); setTaskHistory([]); setError("");
    setStreamedReply("");
    // A new conversation turn takes priority over an older generation review.
    // Close the proposal so the incoming reply remains visible in the chat.
    const input = retry && failedInput ? failedInput : { text, assets, exactReferences }; const capturedBoard = canvasBoard;
    // Snapshot before any awaited request: a project switch must never attach
    // the newly active project's references to this departing request.
    const assetIds = [...new Set([...input.assets.map(asset => asset.id), ...(input.exactReferences ? [] : useDariusStore.getState().referenceAssetIds)])];
    setFailedInput(input);
    if (stayInView) onInteract?.();
    else useDariusStore.getState().setView("talk");
    try {
      const boardContext = capturedBoard && !retry ? { boardId: capturedBoard.boardId, documentId: capturedBoard.documentId, documentRevision: capturedBoard.documentRevision, boardRevision: capturedBoard.boardRevision, name: capturedBoard.name } : undefined;
      if (!conversation.current) {
        const created = await api.createConversation(projectId, "Darius assistant");
        conversation.current = created.id;
        if (alive.current) { setActiveThread(created.id); setThreads((items) => [created, ...items]); }
      }
      const user = savedUser ?? (retry && pending ? pending : await api.createMessage(conversation.current, { role: "user", content: input.text, metadata: { ...(boardContext ? { canvas_board: boardContext } : {}), asset_ids: assetIds, presentation_context: presentation.context() } }));
      originatingMessages.current.add(user.id);
      if (originatingMessages.current.size > 256) originatingMessages.current.delete(originatingMessages.current.values().next().value!);
      if (alive.current) setPending(user);
      if (alive.current && !(retry && pending)) {
        rememberEnter(user.id);
        setMessages((items) => [...items.filter((item) => item.id !== user.id), user]);
      }
      if (retry && ["paused", "pause_requested", "interrupted"].includes(taskState)) await api.controlTask(conversation.current, user.id, "resume");
      const answer = await api.assistantReplyStream(conversation.current, user.id, (delta) => {
        if (!alive.current || requestedControl.current) return;
        setStreamedReply((text) => text + delta);
        onDelta?.(delta);
      });
      if (alive.current && typeof answer.metadata.job_id === "string") {
        void api.job(answer.metadata.job_id).then((job) => {
          if (alive.current) useDariusStore.getState().rememberJob(job);
        }).catch(() => {});
      }
      if (alive.current && answer.metadata.workflow_id) onRetry();
      if (alive.current) { setPending(null); setFailedInput(null); }
      if (alive.current) {
        rememberEnter(answer.id);
        setMessages((items) => [...items.filter((item) => item.id !== answer.id), answer]);
        void presentReply.current(answer);
      }
      return answer.content;
    } catch (err) {
      if (requestedControl.current) {
        const cancelled = requestedControl.current === "cancel";
        if (alive.current) { setError(""); setTaskState(cancelled ? "cancelled" : "paused"); if (cancelled) { setPending(null); setFailedInput(null); } }
        return cancelled ? "Task cancelled." : "Task paused. You can resume it from chat.";
      }
      if (alive.current) setError(err instanceof Error ? err.message : "Darius could not reply. Please try again.");
      throw err;
    } finally {
      inFlight.current = false;
      if (alive.current) { setBusy(false); setStreamedReply(""); }
    }
  }

  async function controlTask(action: "pause" | "cancel") {
    if (!pending || !conversation.current) return;
    setControlling(true);
    try {
      const updated = await api.controlTask(conversation.current, pending.id, action);
      requestedControl.current = action;
      setTaskState(action === "pause" ? "pause_requested" : "cancelled");
      setMessages((items) => items.map((item) => item.id === updated.id ? updated : item));
      if (!busy && action === "cancel") { setPending(null); setFailedInput(null); setError(""); }
    } catch (err) { setError(err instanceof Error ? err.message : "Could not update this task."); }
    finally { setControlling(false); }
  }

  async function retrySavedRequest(message: Message) {
    if (!conversation.current || busy || controlling || inFlight.current || typeof message.metadata.reply_to !== "string") return;
    setControlling(true); setBusy(true); setError("");
    try {
      const updated = await api.retryPreparation(conversation.current, message.metadata.reply_to);
      if (!alive.current) return;
      setMessages((items) => items.filter((item) => item.id !== message.id).map((item) => item.id === updated.id ? updated : item));
      setPending(updated);
      await send("", [], true, undefined, updated);
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Could not recover the saved request."); }
    finally { if (alive.current) { setControlling(false); setBusy(false); } }
  }

  const voiceBackend = useVoicePreferences((state) => state.conversationBackend);
  const setVoiceBackend = useVoicePreferences((state) => state.setConversationBackend);
  const classicVoice = useLocalVoiceConversation((text, onDelta) => send(text, [], false, onDelta), busy || loading || loadError || liveVoiceEnabled);
  const pipecatVoice = usePipecatVoiceConversation((text, onDelta) => send(text, [], false, onDelta), busy || loading || loadError || liveVoiceEnabled);
  const localVoice = voiceBackend === "pipecat" ? pipecatVoice : classicVoice;
  useEffect(() => { stopClassicRef.current = classicVoice.stop; stopPipecatRef.current = pipecatVoice.stop; });
  useEffect(() => { stopClassicRef.current(); stopPipecatRef.current(); }, [voiceBackend]);
  const liveVoice = useLiveVoiceConversation((text) => send(text), busy || loading || loadError || !liveVoiceEnabled, projectId);
  useEffect(() => { stopLiveRef.current = liveVoice.stop; });
  const voice = liveVoiceEnabled ? liveVoice : localVoice;
  useEffect(() => {
    if (visible && voice.phase === "listening" && voice.transcript && followLatest.current) {
      scrollToLatest();
    }
  }, [visible, voice.phase, voice.transcript]);
  const setDariusMood = useDariusStore((state) => state.setDariusMood);
  const mood: DariusMood = busy || voice.phase === "thinking" ? "thinking" : voice.phase === "listening" ? "listening" : voice.phase === "speaking" ? "speaking" : "idle";
  useEffect(() => {
    if (!visible) {
      setDariusMood("idle");
      return;
    }
    setDariusMood(mood);
    return () => setDariusMood("idle");
  }, [mood, visible, setDariusMood]);
  async function openThread(id: string) {
    setMobileThreadsOpen(false);
    if (!projectId || busy || loading || id === conversation.current) return;
    voice.stop(); followLatest.current = true;
    setError(""); setResultDraft(null);
    setPending(null);
    conversation.current = id;
    setActiveThread(id);
    setLoading(true);
    let history: Message[];
    try { history = await api.messages(id); }
    catch (error) { if (alive.current && conversation.current === id) { setError(error instanceof Error ? error.message : "The conversation could not load. Reload to reconnect."); setLoadError(true); } return; }
    finally { if (alive.current) setLoading(false); }
    if (!alive.current || conversation.current !== id) return;
    setMessages(history); setLoadError(false);
    const last = history.at(-1);
    const task = last?.metadata.task as { state?: string; error?: string } | undefined;
    setTaskState(task?.state ?? "ready");
    if (last?.role === "user" && task?.state !== "cancelled") setPending(last);
    if (task?.state === "failed") setError(task.error || "Resume this saved task to continue.");
  }
  async function newThread() {
    setMobileThreadsOpen(false);
    if (!projectId || busy || loading) return;
    setLoading(true);
    let created: Conversation;
    try { created = await api.createConversation(projectId, "New chat"); }
    finally { if (alive.current) setLoading(false); }
    if (!alive.current) return;
    voice.stop(); followLatest.current = true;
    setThreads((items) => [created, ...items.filter((item) => item.id !== created.id)]);
    conversation.current = created.id;
    setActiveThread(created.id);
    setMessages([]);
    setPending(null);
    setResultDraft(null);
    setError("");
  }
  async function renameThread(thread: Conversation, title: string) {
    if (!projectId) return;
    const updated = await api.renameConversation(projectId, thread.id, title);
    if (alive.current) setThreads((items) => items.map((item) => item.id === thread.id ? updated : item));
  }
  async function deleteThread(thread: Conversation) {
    if (!projectId || busy || inFlight.current) return;
    if (conversation.current === thread.id) voice.stop();
    setLoading(true);
    try { await api.deleteConversation(projectId, thread.id); }
    finally { if (alive.current) setLoading(false); }
    if (!alive.current) return;
    const remaining = threads.filter((item) => item.id !== thread.id);
    setThreads(remaining);
    if (conversation.current === thread.id) {
      voice.stop(); conversation.current = null; setActiveThread(null);
      setMessages([]); setPending(null); setFailedInput(null); setResultDraft(null); setError(""); setTaskState("");
      if (remaining[0]) await openThread(remaining[0].id);
    }
  }
  function submit(text: string, assets: Asset[] = [], retry = false) {
    voice.clearError();
    return send(text, assets, retry);
  }
  const stopVoice = useRef(voice.stop);
  const stopLocalVoice = useRef(localVoice.stop);
  const stopLiveVoice = useRef(liveVoice.stop);
  useEffect(() => {
    stopVoice.current = voice.stop;
    stopLocalVoice.current = localVoice.stop;
    stopLiveVoice.current = liveVoice.stop;
  });
  useEffect(() => {
    if (visible) return;
    stopVoice.current();
    const frame = requestAnimationFrame(() => setFullscreenVoice(false));
    return () => cancelAnimationFrame(frame);
  }, [visible]);
  useEffect(() => { if (liveVoiceEnabled) stopLocalVoice.current(); else stopLiveVoice.current(); }, [liveVoiceEnabled]);

  function voiceMessageResults(message: Message) {
    if (message.role !== "assistant") return null;
    const metadata = message.metadata;
    const jobIds = messageJobIds(metadata);
    return <>
      <ChatRecovery message={message} busy={busy || controlling} onRetry={(message) => void retrySavedRequest(message)} />
      {jobIds.map((id) => <div id={`voice-job-${id}`} key={id}><ConversationRender projectId={projectId} jobId={id} embedded busy={busy || Boolean(resultDraft)} onFollowup={stageResult} /></div>)}
      <ConversationImages ids={metadata.viewed_asset_ids} />
    </>;
  }
  function stageResult(asset: Asset, action: ResultAction) {
    if (asset.project_id !== projectId || busy || resultDraft) return;
    setResultDraft({ id: Date.now(), asset, action });
    followLatest.current = true;
    requestAnimationFrame(scrollToLatest);
  }
  const lastIntent = [...messages].reverse().find(message => message.role === "assistant" && message.metadata.superseded !== true && message.metadata.resolved_intent)?.metadata.resolved_intent;
  const resultFollowup = resultDraft && resultDraft.asset.project_id === projectId ? <ResultFollowup key={resultDraft.id} draft={resultDraft} busy={busy} onClose={() => setResultDraft(null)} onSend={(text, asset) => send(text, [asset], false, undefined, undefined, true)} /> : null;
  const voiceControls = <div className="voice-controls">
        {compact ? <button className="mobile-conversation-menu icon-button" aria-label="Open conversation menu" aria-expanded={mobileThreadsOpen} onClick={() => setMobileThreadsOpen((open) => !open)} type="button"><MessagesSquare size={22} /></button> : null}
        <button className="secondary-button" disabled={!projectId || loading || loadError} type="button" onClick={() => { voice.stop(); setFullscreenChat(true); setFullscreenVoice(true); }}><Maximize2 size={16} />Fullscreen chat</button>
        <button className="secondary-button voice-fullscreen-launch" disabled={!projectId || loading || loadError} type="button" onClick={() => { setFullscreenChat(false); setFullscreenVoice(true); if (!busy && voice.phase === "off" && !voice.connecting) voice.start(); }}><Maximize2 size={16} />Fullscreen voice</button>
        {!liveVoiceEnabled && localVoice.transcribing ? <span role="status">Transcribing your message…</span> : null}
        <button className={voice.phase === "off" ? "secondary-button" : "primary-button"} disabled={voice.connecting || !projectId || loading || loadError || (busy && voice.phase === "off")} aria-label={voice.phase === "off" ? "Start voice conversation" : "End voice conversation"} onClick={voice.phase === "off" ? voice.start : voice.endConversation} type="button">
          {voice.phase === "off" ? <Mic size={16} /> : <Square size={14} />}
          {voice.connecting ? "Connecting..." : voice.phase === "off" ? "Start voice" : "End voice"}
        </button>
        {voice.phase === "speaking" || (!liveVoiceEnabled && voice.phase === "thinking") ? <button className="secondary-button" disabled={!liveVoiceEnabled && localVoice.waitingForReply} onClick={voice.start} type="button">Interrupt & speak</button> : null}
        {!liveVoiceEnabled && localVoice.waitingForReply ? <span role="status">Your next message is held until the current reply finishes.</span> : null}
        {!liveVoiceEnabled && voice.phase === "speaking" ? <small>{voiceBackend === "pipecat" ? "Speak naturally to interrupt the voice. Your task continues in chat." : "Say “Darius, stop” to interrupt. The task continues in chat."}</small> : null}
        {!liveVoiceEnabled && voice.phase === "thinking" && !busy ? <button className="secondary-button" onClick={localVoice.start} type="button">Continue listening</button> : null}
        <span className="voice-phase" role="status">{voice.phase === "listening" ? liveVoiceEnabled ? "Listening · GPT-Live 1" : "Listening…" : voice.phase === "thinking" ? busy ? "Thinking…" : liveVoiceEnabled ? "GPT-Live is thinking…" : "Preparing local voice…" : voice.phase === "speaking" ? "Darius is speaking…" : voice.armed ? "Listening for Darius · local" : ""}</span>
  </div>;

  const conversationPanel = visible ? <div className={`assistant-workspace ${messages.length ? "has-conversation" : ""} ${mobileThreadsOpen ? "mobile-threads-open" : ""}`}>
      {mobileThreadsOpen ? <button className="mobile-thread-scrim" aria-label="Dismiss conversations" onClick={closeThreads} type="button" /> : null}
      <aside className="talk-thread-list" role={compact && mobileThreadsOpen ? "dialog" : undefined} aria-modal={compact && mobileThreadsOpen ? true : undefined} aria-label="Conversations">
        <header className="mobile-sheet-title"><strong>Your conversations</strong><button className="icon-button" aria-label="Close conversations" onClick={closeThreads} type="button"><X size={20} /></button></header>
        <div className="talk-thread-tools">
          <button className="primary-button" disabled={!projectId || busy} onClick={() => void newThread().catch((err: Error) => setError(err.message))} type="button"><MessageSquarePlus size={15} /> New chat</button>
          <label className="search-field"><Search size={14} /><span className="sr-only">Search conversations</span><input value={threadQuery} onChange={(event) => setThreadQuery(event.target.value)} placeholder="Search" /></label>
        </div>
        {["Today", "Earlier"].map((bucket) => {
          const start = new Date();
          start.setHours(0, 0, 0, 0);
          const group = threads.filter((thread) => {
            const today = new Date(thread.updated_at || thread.created_at).getTime() >= start.getTime();
            return (bucket === "Today" ? today : !today) && thread.title.toLowerCase().includes(threadQuery.trim().toLowerCase());
          });
          if (!group.length) return null;
          return <div key={bucket}><p className="talk-thread-group">{bucket}</p>{group.map((thread) => <ConversationRow key={thread.id} thread={thread} active={thread.id === activeThread} disabled={busy || loading} onOpen={() => void openThread(thread.id).catch((err: Error) => setError(err.message))} onRename={(title) => renameThread(thread, title)} onDelete={() => deleteThread(thread)} onError={setError} />)}</div>;
        })}
        {!threads.length ? <p className="map-search-empty">This project has no saved chats yet.</p> : null}
      </aside>
      <div className="talk-conversation-column">
      {projectId && !fullscreenVoice ? <ConversationContext key={projectId} projectId={projectId} busy={busy} lastIntent={lastIntent} /> : null}
      <div className="talk-stream" ref={scrollArea} onWheel={(event) => { if (event.deltaY < 0) followLatest.current = false; }} onTouchMove={() => { followLatest.current = false; }} onPointerDown={(event) => { if (event.target === event.currentTarget) followLatest.current = false; }} onKeyDown={(event) => { if (["ArrowUp", "PageUp", "Home"].includes(event.key)) followLatest.current = false; }} onScroll={(event) => {
      const area = event.currentTarget;
      if (area.scrollHeight - area.scrollTop - area.clientHeight < 80) followLatest.current = true;
      rememberWorkspaceValue(`chat-scroll:${projectId}:${activeThread}`, { top: area.scrollTop, follow: followLatest.current });
    }}>
      <div ref={scrollContent} className="talk-stream-content">
      <div className="assistant-voice-bar">
        {voice.error && !error ? <p className="form-error" role="alert">{voice.error}</p> : null}
      </div>
      {loading ? <p role="status">Loading your conversation…</p> : null}
      {remoteWorking && !busy ? <p className="project-sync-notice" role="status">Darius is working on this conversation on another device. Replies will appear here automatically.</p> : null}
      {messages.length || busy || (voice.phase === "listening" && voice.transcript) ? <section className="assistant-messages" aria-label="Conversation with Darius">
        {messages.filter((message) => message.metadata.superseded !== true && (message.role === "user" || message.role === "assistant")).map((message) => <article className={`assistant-message from-${message.role}${enterIds.has(message.id) ? " os-enter" : ""}`} key={message.id}>
          <span className="eyebrow">{message.role === "user" ? "You" : "Darius"}</span>
          <RenderMessageText message={message} projectId={projectId} />
          {message.role === "assistant" ? <ChatRecovery message={message} busy={busy || controlling} onRetry={(message) => void retrySavedRequest(message)} /> : null}
          {message.role === "assistant" && message.metadata.workflow_route && typeof message.metadata.workflow_route === "object" ? <small>Workflow template: {String((message.metadata.workflow_route as Record<string, unknown>).name ?? "")}</small> : null}
          {message.role === "assistant" ? messageJobIds(message.metadata).map((id) => <ConversationRender key={id} projectId={projectId} jobId={id} busy={busy || Boolean(resultDraft)} onFollowup={stageResult} />) : null}
          {message.role === "assistant" && !message.metadata.recovery && !messageJobIds(message.metadata).length && Array.isArray(message.metadata.tool_activity) && message.metadata.tool_activity.length ? (() => {
            const activity = message.metadata.tool_activity as Array<{ operation?: unknown; ok?: unknown }>;
            const failed = activity.filter((item) => item.ok === false).length;
            const jobId = typeof message.metadata.job_id === "string" ? message.metadata.job_id : null;
            return <div className={`assistant-result-status ${failed ? "has-failure" : ""}`} role="status">
              <span>{jobId ? "Render job saved" : message.metadata.generation_prompt ? "Draft ready · not rendered" : failed ? "Some steps failed" : `Processed ${activity.length} steps`}</span>
              {jobId ? <small>Job {jobId.slice(0, 8)} is saved in Background jobs.</small> : <small>{message.metadata.generation_prompt ? "Review and approve below to create the media. It will appear in Create when rendering completes." : "ComfyUI activity is saved below."}</small>}
            </div>;
          })() : null}
          {message.role === "assistant" ? <ConversationImages ids={message.metadata.viewed_asset_ids} /> : null}
          {message.role === "assistant" && typeof message.metadata.job_id === "string" ? <button className="secondary-button" type="button" onClick={() => {
            useDariusStore.getState().setSelection({ type: "job", id: message.metadata.job_id as string });
          }}>View render job</button> : null}
          {message.role === "assistant" && Array.isArray(message.metadata.tool_activity) && message.metadata.tool_activity.length ? <details className="assistant-tool-history"><summary>ComfyUI activity · {message.metadata.tool_activity.length} calls</summary><ul>{message.metadata.tool_activity.map((item, index) => <li key={index}>{String(item.operation).replaceAll("_", " ")} · {item.ok ? "completed" : "failed"}{typeof item.error === "string" ? <p>{item.error}</p> : null}</li>)}</ul></details> : null}
          {Array.isArray(message.metadata.asset_ids) && message.metadata.asset_ids.length ? <small>{message.metadata.asset_ids.length} attached asset(s)</small> : null}
        </article>)}
        {(voice.phase === "listening" || (!liveVoiceEnabled && localVoice.waitingForReply)) && voice.transcript ? <article className="assistant-message from-user voice-draft" aria-live="polite" aria-atomic="true"><span className="eyebrow">You · {!liveVoiceEnabled && localVoice.waitingForReply ? "Next message held" : !liveVoiceEnabled && localVoice.transcribing ? "Finalizing transcription…" : "Live transcript"}</span><p>{voice.transcript}</p><small>{!liveVoiceEnabled && localVoice.waitingForReply ? "Sends when the current reply finishes. End voice to discard." : "Draft · words may change before sending"}</small></article> : null}
        {streamedReply ? <article className="assistant-message from-assistant" aria-label="Darius reply in progress"><span className="eyebrow">Darius · replying</span><p>{streamedReply}</p></article> : null}
        {busy && !streamedReply ? <div className="assistant-thought os-enter"><LiquidOrb mood="thinking" size="thought" /><AssistantTaskCard history={taskHistory} elapsed={elapsed} slow={slowReply} saved={Boolean(pending)} /></div> : null}
        {pending ? <div className="task-controls"><span role="status">{taskState === "pause_requested" ? "Pausing after the current step…" : taskState === "cancelled" ? "Cancellation requested; finishing the current call." : taskState === "paused" ? "Task paused" : taskState === "interrupted" ? "Server restarted · saved task available" : ""}</span>
          {busy && !["pause_requested", "paused", "cancelled"].includes(taskState) ? <button className="secondary-button" disabled={controlling} onClick={() => void controlTask("pause")} type="button">Pause after this step</button> : null}
          {taskState !== "cancelled" ? <button className="secondary-button" disabled={controlling} onClick={() => void controlTask("cancel")} type="button">Cancel task</button> : null}
          {!busy && !error && taskState !== "cancelled" ? <button className="secondary-button" onClick={() => void submit("", [], true).catch(() => {})} type="button">{pending.metadata.task || taskState === "paused" ? "Resume saved task" : "Continue reply"}</button> : null}
        </div> : null}
      </section> : null}
      {error ? <div className="assistant-error assistant-reply-error" role="alert"><strong>{loadError ? "Conversation could not load" : "Reply interrupted"}</strong><p>{error}</p>{pending || failedInput ? <><p>Your message is saved. You can retry this reply here.</p><button className="secondary-button" disabled={busy} onClick={() => void submit("", [], true).catch(() => {})} type="button">Retry reply</button></> : <button className="secondary-button" onClick={() => { if (loadError) { setError(""); setLoading(true); setLoadError(false); setLoadAttempt(attempt => attempt + 1); } else window.location.reload(); }} type="button">Reload conversation</button>}</div> : null}
      {!fullscreenVoice && !messages.length && !workspaceHost ? <CreativeChatWelcome mood={mood} /> : null}
      {!fullscreenVoice ? resultFollowup : null}
      <div ref={bottom} style={{ height: 1 }} />
      {showLatest && messages.length > 0 ? <div className="talk-latest-anchor"><button className="talk-latest-button" type="button" aria-label="Scroll to latest message" onClick={() => {
        followLatest.current = true;
        scrollToLatest();
      }}><ArrowDown size={16} /><span>Latest message</span></button></div> : null}
      </div>
      </div>
      </div>
    </div> : null;
  const viewer = presentation.gallery ? presentation.gallery.mode === "gallery" ? <VoiceGallery assets={presentation.gallery.assets} onSelect={presentation.select} onClose={presentation.close} /> : <AssetViewer asset={presentation.gallery.assets[presentation.gallery.index]} navigationAssets={presentation.gallery.assets} playback={presentation.playback} onGallery={presentation.browse} onSelect={presentation.select} onClose={presentation.close} /> : null;
  return <>
    {visible && !fullscreenVoice ? viewer : null}
    {visible && !fullscreenVoice && presentation.error ? <p role="alert" className="form-error">{presentation.error}</p> : null}
    {visible && fullscreenVoice ? createPortal(<FullscreenVoice initialChat={fullscreenChat} draftKey={`${projectId}:${activeThread ?? "new"}`} phase={voice.phase} connecting={voice.connecting} busy={busy} transcript={voice.transcript} reply="" messages={messages} streamedReply={streamedReply}
      sessionName={threads.find((thread) => thread.id === activeThread)?.title ?? "New conversation"} projectName={voiceProjectName} loading={loading}
      contextPanel={projectId ? <ConversationContext key={projectId} projectId={projectId} busy={busy} lastIntent={lastIntent} /> : null}
      transcribing={!liveVoiceEnabled && localVoice.transcribing} waitingForReply={!liveVoiceEnabled && localVoice.waitingForReply}
      voiceBackend={voiceBackend} onBackendChange={setVoiceBackend}
      overlay={<>{viewer}{presentation.error ? <p role="alert" className="form-error">{presentation.error}</p> : null}</>}
      renderMessage={voiceMessageResults} renderText={(message) => <RenderMessageText message={message} projectId={projectId} />} onSend={async (text) => { voice.stop(); return submit(text); }}
      error={error || voice.error} cloud={liveVoiceEnabled} disabled={!projectId || loading || loadError} onStart={voice.start} onStop={voice.stop} onClose={() => setFullscreenVoice(false)} onEnd={() => { voice.endConversation(); setFullscreenVoice(false); }} onEngineChange={(cloud) => { voice.stop(); setLiveVoiceEnabled(cloud); }} canInterrupt={!liveVoiceEnabled && (voice.phase === "speaking" || voice.phase === "thinking") && !localVoice.waitingForReply} actions={<>
      {resultFollowup}
      {busy ? <AssistantTaskCard history={taskHistory} elapsed={elapsed} slow={slowReply} saved={Boolean(pending)} /> : null}

      {pending ? <div className="task-controls"><span role="status">{taskState.replaceAll("_", " ")}</span>{busy && !["pause_requested", "paused", "cancelled"].includes(taskState) ? <button type="button" className="secondary-button" disabled={controlling} onClick={() => void controlTask("pause")}>Pause task</button> : null}{taskState !== "cancelled" ? <button type="button" className="secondary-button" disabled={controlling} onClick={() => void controlTask("cancel")}>Cancel task</button> : null}{!busy && taskState !== "cancelled" ? <button type="button" className="secondary-button" onClick={() => void submit("", [], true).catch(() => {})}>Resume saved task</button> : null}</div> : null}
    </>} />, document.body) : null}
    {visible && voiceHost ? createPortal(voiceControls, voiceHost) : null}
    {workspaceHost ? createPortal(conversationPanel, workspaceHost) : conversationPanel}
    <MovableSurface target={composerHost}>
    <Composer key={`${projectId}:${activeThread ?? "new"}`} draftKey={`${projectId}:${activeThread ?? "new"}`} targetLabel={threads.find(thread => thread.id === activeThread)?.title ?? "New conversation"} compact={compact || !visible || Boolean(workspaceHost)} onBeginTyping={() => voice.stop()} toolbarActions={visible ? <><span className="project-images-host" ref={setImageTriggerHost} /><details className="conversation-settings"><summary aria-label="Conversation settings" title="Conversation settings"><Settings2 size={18} /></summary><div className="conversation-settings-panel"><label className="wake-word-setting"><input type="checkbox" checked={liveVoiceEnabled} disabled={!projectId || loading || busy || liveVoice.connecting} onChange={(event) => setLiveVoiceEnabled(event.target.checked)} />Use GPT-Live 1 cloud voice</label><small>Uses OpenAI GPT-Live 1 for full-duplex voice. Audio is billed by session duration; your API key stays on the server.</small><label className="wake-word-setting"><input type="checkbox" checked={!liveVoiceEnabled && voice.armed} disabled={liveVoiceEnabled || voiceBackend === "pipecat" || (!voice.armed && (!projectId || loading || busy || voice.connecting))} onChange={(event) => event.target.checked ? localVoice.arm() : localVoice.stop()} />Listen for &quot;Darius&quot; locally</label><small>Wake-word activation uses Classic voice. Pipecat sessions start with the microphone button.</small><small>After activation, your commands and project context go to your configured AI.</small></div></details></> : null} beforeComposer={<>{canvasBoard ? <small className="moss-composer-target">Context: {canvasBoard.name} · Read-only. Use in board applies a prompt; Generate stays on the board.</small> : null}{visible ? <><div className="composer-voice-controls">{voiceControls}</div>{projectId ? <AssistantReferences key={`references-${projectId}`} projectId={projectId} busy={busy} triggerHost={imageTriggerHost} /> : null}</> : null}</>} disabled={!projectId || loading || busy || voice.phase !== "off" || voice.connecting || loadError} onSubmit={(text, assets) => void submit(text, assets).catch(() => {})} projectId={projectId} />
    </MovableSurface>
  </>;
}
