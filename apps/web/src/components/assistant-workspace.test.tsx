import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { Asset, Message, Workflow } from "@/lib/types";
import { AssistantWorkspace } from "./assistant-workspace";
import { publishProjectRefresh } from "@/lib/project-sync";
import { useDariusStore } from "@/lib/store";
import { rememberWorkspaceValue } from "@/lib/workspace-session";

const voice = vi.hoisted(() => ({ phase: "off", start: vi.fn(), stop: vi.fn(), clearError: vi.fn() }));
const outgoing = vi.hoisted(() => ({ text: "Hello DeepSeek" }));
vi.mock("@/lib/use-local-voice-conversation", () => ({ useLocalVoiceConversation: () => voice }));
vi.mock("@/lib/use-live-voice-conversation", () => ({ useLiveVoiceConversation: () => voice }));
vi.mock("./liquid-orb", () => ({ LiquidOrb: () => null }));
vi.mock("./conversation-context", () => ({ ConversationContext: () => null }));
vi.mock("./conversation-render", () => ({ ConversationRender: ({ jobId, projectId, onFollowup }: { jobId: string; projectId: string; onFollowup?: (asset: Asset, action: "animate") => void }) => <div data-testid="render-output">Output {jobId}{onFollowup ? <button onClick={() => onFollowup({ id: "original-result", project_id: projectId, kind: "image", metadata: { display_name: "Forest" } } as unknown as Asset, "animate")}>Animate test result</button> : null}</div> }));
vi.mock("./assistant-references", () => ({ AssistantReferences: () => null, ConversationImages: () => null }));
vi.mock("./talk-view", () => ({ TalkView: ({ setSelectedWorkflowId }: { setSelectedWorkflowId: (id: string) => void }) => <button onClick={() => setSelectedWorkflowId("chosen-qwen")}>Choose test workflow</button> }));
vi.mock("./local-render-setting", () => ({ LocalRenderSetting: () => null }));
vi.mock("./composer", () => ({ Composer: ({ onSubmit, disabled, beforeComposer }: { onSubmit: (text: string, assets: []) => void; disabled: boolean; beforeComposer?: React.ReactNode }) => <>{beforeComposer}<button disabled={disabled} onClick={() => onSubmit(outgoing.text, [])}>Send test message</button></> }));
const originalModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
afterEach(() => {
  outgoing.text = "Hello DeepSeek";
  vi.restoreAllMocks();
  for (const [name, descriptor] of [["showModal", originalModal], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});

it("captures board A as read-only context without saving it, even if selection changes to B", async () => {
  outgoing.text = "Generate composition";
  const a = { boardId: "a", documentId: "doc-a", documentRevision: 1, boardRevision: 1, name: "A", prepare: vi.fn() };
  const b = { boardId: "b", documentId: "doc-b", documentRevision: 1, boardRevision: 1, name: "B", prepare: vi.fn() };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "chat", project_id: "p", title: "Shared chat", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([]);
  const user = { id: "source", conversation_id: "chat", role: "user", content: "Generate composition", metadata: {}, created_at: "" } as Message;
  const create = vi.spyOn(api, "createMessage").mockResolvedValue(user);
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...user, id: "reply", role: "assistant", content: "Board A queued" });
  const props = { projectId: "p", visible: true, workflows: [], workflowsLoading: false, workflowsError: null, onRetry: vi.fn() };
  const view = render(<AssistantWorkspace {...props} canvasBoard={a} />);
  await userEvent.click(await screen.findByText("Send test message"));
  expect(a.prepare).not.toHaveBeenCalled();
  view.rerender(<AssistantWorkspace {...props} canvasBoard={b} />);

  await waitFor(() => expect(create).toHaveBeenCalledWith("chat", expect.objectContaining({ metadata: expect.objectContaining({ canvas_board: expect.objectContaining({ boardId: "a", documentId: "doc-a", documentRevision: 1 }) }) })));
  expect(b.prepare).not.toHaveBeenCalled();
});

it("opens an embedded chat at the latest message instead of restoring Talk's older reading position", async () => {
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(1000);
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "embedded-scroll", project_id: "p", title: "Canvas chat", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([{ id: "latest", conversation_id: "embedded-scroll", role: "assistant", content: "Newest embedded reply", metadata: {}, created_at: "" }]);
  rememberWorkspaceValue("chat-scroll:p:embedded-scroll", { top: 120, follow: false });
  const host = document.createElement("div"); document.body.appendChild(host);
  const props = { projectId: "p", workflows: [], workflowsLoading: false, workflowsError: null, onRetry: vi.fn(), stayInView: true, workspaceHost: host };
  const view = render(<AssistantWorkspace {...props} visible={false} />);
  try {
    await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
    view.rerender(<AssistantWorkspace {...props} visible />);
    await screen.findByText("Newest embedded reply");
    await waitFor(() => expect(host.querySelector(".talk-stream")?.scrollTop).toBe(1000));
  } finally { view.unmount(); host.remove(); }
});
it("snapshots outgoing references before conversation creation and rejects stale replies after a project switch", async () => {
  const user = userEvent.setup();
  vi.spyOn(api, "conversations").mockResolvedValue([]);
  let finishCreation!: (value: Awaited<ReturnType<typeof api.createConversation>>) => void;
  vi.spyOn(api, "createConversation").mockImplementation(() => new Promise(resolve => { finishCreation = resolve; }));
  const message = { id: "old-user", conversation_id: "old-chat", role: "user", content: "Hello DeepSeek", metadata: {}, created_at: "" } as Message;
  const create = vi.spyOn(api, "createMessage").mockResolvedValue(message);
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...message, id: "old-answer", role: "assistant", content: "Old project reply" });
  useDariusStore.setState({ activeProjectId: "project-a", referenceAssetIds: ["reference-a"] });
  const props = { visible: true, workflows: [], workflowsLoading: false, workflowsError: null, onRetry: vi.fn() };
  const { rerender } = render(<AssistantWorkspace key="project-a" projectId="project-a" {...props} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Send test message" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Send test message" }));
  act(() => { useDariusStore.getState().setActiveProject("project-b"); useDariusStore.getState().addReferenceAsset("reference-b"); });
  rerender(<AssistantWorkspace key="project-b" projectId="project-b" {...props} />);
  await act(async () => { finishCreation({ id: "old-chat", project_id: "project-a", title: "Old chat", created_at: "", updated_at: "" }); });
  await waitFor(() => expect(create).toHaveBeenCalledWith("old-chat", expect.objectContaining({ metadata: expect.objectContaining({ asset_ids: ["reference-a"] }) })));
  expect(screen.queryByText("Old project reply")).not.toBeInTheDocument();
  expect(useDariusStore.getState().referenceAssetIds).toEqual(["reference-b"]);
});

it.each(["local", "direct"])("shows shared %s render outputs only in Darius's bubble, preserving user attachments", async (source) => {
  const request: Message = { id: "render-user", conversation_id: "render-chat", role: "user", content: "Generate two images", metadata: {
    asset_ids: ["reference"],
    ...(source === "local" ? { local_render_job_id: "render-one", local_render_job_ids: ["render-one", "render-two"] } : { job_id: "render-one", job_ids: ["render-one", "render-two"] }),
    task: { state: "completed", job_id: "render-one", output_asset_ids: ["output-one", "output-two"] },
  }, created_at: "" };
  const reply: Message = { ...request, id: "render-reply", role: "assistant", content: "Your images are ready", metadata: { reply_to: request.id, job_id: "render-one", job_ids: ["render-one", "render-two"] } };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "render-chat", project_id: "render-project", title: "Render chat", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([request, reply]);
  render(<AssistantWorkspace projectId="render-project" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  const userBubble = (await screen.findByText(request.content)).closest("article")!;
  const assistantBubble = screen.getByText(reply.content).closest("article")!;
  expect(within(userBubble).queryAllByTestId("render-output")).toHaveLength(0);
  expect(within(userBubble).getByText("1 attached asset(s)")).toBeVisible();
  expect(within(assistantBubble).getAllByTestId("render-output")).toHaveLength(2);
  expect(screen.getAllByTestId("render-output")).toHaveLength(2);
  expect(request.metadata.task).toEqual({ state: "completed", job_id: "render-one", output_asset_ids: ["output-one", "output-two"] });
});

it("recovers a blocked request using its saved message instead of creating a duplicate", async () => {
  const user = userEvent.setup();
  const request: Message = { id: "saved-user", conversation_id: "recovery-chat", role: "user", content: "Generate a forest image", metadata: { asset_ids: ["reference"] }, created_at: "" };
  const blocked: Message = { ...request, id: "blocked", role: "assistant", content: "Workflow service unavailable", metadata: { reply_to: request.id, recovery: { action: "retry", can_retry: true } } };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "recovery-chat", project_id: "p", title: "Recovery chat", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([request, blocked]);
  const create = vi.spyOn(api, "createMessage");
  const recover = vi.spyOn(api, "retryPreparation").mockResolvedValue(request);
  const reply = vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...blocked, id: "recovered", content: "Your request is ready for review", metadata: { reply_to: request.id } });
  render(<AssistantWorkspace projectId="p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "Retry saved request" }));
  expect(await screen.findByText("Your request is ready for review")).toBeVisible();
  expect(recover).toHaveBeenCalledWith("recovery-chat", "saved-user");
  expect(reply).toHaveBeenCalledWith("recovery-chat", "saved-user", expect.any(Function));
  expect(create).not.toHaveBeenCalled();
  expect(screen.getAllByText(request.content)).toHaveLength(1);
  expect(screen.queryByText(blocked.content)).not.toBeInTheDocument();
});

it("sends a result follow-up with exactly its chosen asset, keeping other selected references unchanged", async () => {
  const user = userEvent.setup();
  const reply: Message = { id: "result", conversation_id: "result-chat", role: "assistant", content: "Forest result", metadata: { job_id: "render" }, created_at: "" };
  useDariusStore.setState({ activeProjectId: "p", referenceAssetIds: ["unrelated-selected"] });
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "result-chat", project_id: "p", title: "Results", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([reply]);
  const create = vi.spyOn(api, "createMessage").mockResolvedValue({ ...reply, id: "followup", role: "user", metadata: {} });
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...reply, id: "answer", content: "Ready for review", metadata: {} });
  render(<AssistantWorkspace projectId="p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "Animate test result" }));
  expect(create).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Send follow-up" }));
  await waitFor(() => expect(create).toHaveBeenCalledWith("result-chat", expect.objectContaining({ metadata: expect.objectContaining({ asset_ids: ["original-result"] }) })));
  expect(useDariusStore.getState().referenceAssetIds).toEqual(["unrelated-selected"]);
});

it("opens a new presentation reply using original media but never replays saved history", async () => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  const user = userEvent.setup();
  const receipt = { action: "open", asset_ids: ["original"], project_id: "p" };
  const saved = { id: "old", conversation_id: "chat", role: "assistant", content: "An old preview", metadata: { presentation_actions: [receipt] }, created_at: "" } as Message;
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "chat", project_id: "p", title: "Darius assistant", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([saved]);
  const get = vi.spyOn(api, "asset").mockResolvedValue({ id: "original", project_id: "p", kind: "image", metadata: { display_name: "Original image" } } as unknown as Asset);
  vi.spyOn(api, "createMessage").mockResolvedValue({ ...saved, id: "user", role: "user", metadata: {} });
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...saved, id: "new", content: "Opening full size.", metadata: { presentation_actions: [receipt], reply_to: "user" } });
  render(<AssistantWorkspace projectId="p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await screen.findByText("An old preview");
  expect(get).not.toHaveBeenCalled();
  await user.click(await screen.findByText("Send test message"));
  const viewer = await screen.findByRole("dialog", { name: "Full-size preview: Original image" });
  expect(within(viewer).getByRole("img")).toHaveAttribute("src", expect.stringContaining("/assets/original/content"));
  await user.click(within(viewer).getByRole("button", { name: "Close asset preview" }));
  expect(screen.queryByRole("dialog", { name: "Full-size preview: Original image" })).not.toBeInTheDocument();
});

it("receives the first remotely-created conversation in an already-open empty project", async () => {
  const chats = vi.spyOn(api, "conversations").mockResolvedValue([]);
  vi.spyOn(api, "messages").mockResolvedValue([{ id: "first", conversation_id: "remote-chat", role: "assistant", content: "First conversation from desktop", metadata: {}, created_at: "" }]);
  render(<AssistantWorkspace projectId="empty-p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
  chats.mockResolvedValue([{ id: "remote-chat", project_id: "empty-p", title: "New remote chat", created_at: "", updated_at: "" }]);
  act(() => publishProjectRefresh({ projectId: "empty-p", types: ["conversation.created"], full: false }));
  expect(await screen.findByText("First conversation from desktop")).toBeVisible();
});

it("syncs remote chat history and renamed threads without speaking, presenting media, or generating another reply", async () => {
  const saved = { id: "remote", conversation_id: "chat", role: "assistant", content: "Made on my desktop", metadata: { presentation_actions: [{ action: "open", project_id: "p", asset_ids: ["original"] }] }, created_at: "" } as Message;
  const threads = vi.spyOn(api, "conversations").mockResolvedValue([{ id: "chat", project_id: "p", title: "Phone chat", created_at: "", updated_at: "" }]);
  const messages = vi.spyOn(api, "messages").mockResolvedValue([]);
  const asset = vi.spyOn(api, "asset");
  const generate = vi.spyOn(api, "assistantReplyStream");
  render(<AssistantWorkspace projectId="p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
  messages.mockResolvedValue([saved]);
  threads.mockResolvedValue([{ id: "chat", project_id: "p", title: "Renamed on laptop", created_at: "", updated_at: "" }]);
  act(() => publishProjectRefresh({ projectId: "unrelated", types: [], full: true }));
  expect(screen.queryByText(saved.content)).not.toBeInTheDocument();
  act(() => publishProjectRefresh({ projectId: "p", types: ["conversation.assistant_replied"], full: false }));
  expect(await screen.findByText(saved.content)).toBeVisible();
  expect(within(screen.getByLabelText("Conversations")).getByText("Renamed on laptop")).toBeInTheDocument();
  expect(asset).not.toHaveBeenCalled(); expect(generate).not.toHaveBeenCalled();
});

it("shows streamed text before completion and replaces it with one saved reply", async () => {
  const user = userEvent.setup();
  const message: Message = { id: "m2", conversation_id: "c2", role: "user", content: "Hello DeepSeek", metadata: {}, created_at: "" };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "c2", project_id: "p2", title: "Darius assistant", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([]);
  vi.spyOn(api, "createMessage").mockResolvedValue(message);
  let finish!: (value: Message) => void;
  let delta!: (text: string) => void;
  vi.spyOn(api, "assistantReplyStream").mockImplementation((_cid, _mid, onDelta) => {
    delta = onDelta;
    return new Promise((resolve) => { finish = resolve; });
  });
  render(<AssistantWorkspace projectId="p2" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
  await user.click(screen.getByText("Send test message"));
  act(() => delta("First sentence."));
  expect(screen.getByLabelText("Darius reply in progress")).toHaveTextContent("First sentence.");
  expect(screen.getByText("Send test message")).toBeDisabled();
  await act(async () => finish({ ...message, id: "a2", role: "assistant", content: "First sentence. Complete.", metadata: { reply_to: "m2" } }));
  expect(screen.queryByLabelText("Darius reply in progress")).not.toBeInTheDocument();
  expect(screen.getAllByText("First sentence. Complete.")).toHaveLength(1);
});

it("replaces thinking with a visible error after the saved message and retries without duplicating it", async () => {
  const user = userEvent.setup();
  const message: Message = { id: "m1", conversation_id: "c1", role: "user", content: "Hello DeepSeek", metadata: {}, created_at: "2026-09-14" };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "c1", project_id: "p1", title: "Darius assistant", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([]);
  const create = vi.spyOn(api, "createMessage").mockResolvedValue(message);
  let rejectReply!: (reason: Error) => void;
  const reply = vi.spyOn(api, "assistantReplyStream").mockImplementationOnce(() => new Promise((_, reject) => { rejectReply = reject; }))
    .mockResolvedValueOnce({ ...message, id: "a1", role: "assistant", content: "I am here", metadata: { reply_to: "m1" } });
  render(<AssistantWorkspace projectId="p1" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
  await user.click(screen.getByText("Send test message"));
  expect(await screen.findByText("Darius is thinking")).toBeVisible();
  await act(async () => rejectReply(new Error("Connection timed out")));
  const alert = screen.getByRole("alert");
  expect(alert).toBeVisible();
  expect(screen.getByText("Hello DeepSeek").compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByText("Darius is thinking")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retry reply" }));
  expect(await screen.findByText("I am here")).toBeVisible();
  expect(create).toHaveBeenCalledTimes(1);
  expect(reply).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("does not expose workflow selection or send execution preferences from chat", async () => {
  const user = userEvent.setup();
  const message: Message = { id: "choice-user", conversation_id: "choice-chat", role: "user", content: "Hello DeepSeek", metadata: {}, created_at: "" };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "choice-chat", project_id: "p", title: "Darius assistant", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([]);
  const create = vi.spyOn(api, "createMessage").mockResolvedValue(message);
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...message, role: "assistant", content: "Done" });
  render(<AssistantWorkspace projectId="p" visible workflows={[]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Send test message")).toBeEnabled());
  expect(screen.queryByText("Choose test workflow")).toBeNull();
  await user.click(screen.getByText("Send test message"));
  await waitFor(() => expect(create).toHaveBeenCalled());
  expect(create.mock.calls[0][1].metadata).not.toHaveProperty("preferred_workflow_id");
});

it("loading an old workflow proposal does not restore execution controls", async () => {
  const user = userEvent.setup();
  const message: Message = { id: "draft", conversation_id: "draft-chat", role: "assistant", content: "Review the old draft", metadata: { generation_prompt: "Garvin in a spaceship", workflow_id: "assistant-old" }, created_at: "" };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "draft-chat", project_id: "p", title: "Darius assistant", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([message]);
  const create = vi.spyOn(api, "createMessage").mockResolvedValue({ ...message, id: "new-user", role: "user", metadata: {} });
  vi.spyOn(api, "assistantReplyStream").mockResolvedValue({ ...message, content: "Done", metadata: {} });
  const old = { id: "assistant-old", required_inputs: [] } as unknown as Workflow;
  render(<AssistantWorkspace projectId="p" visible workflows={[old]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await screen.findByText(message.content);
  expect(screen.queryByRole("button", { name: "Review generation" })).toBeNull();
  await user.click(await screen.findByText("Send test message"));
  await waitFor(() => expect(create).toHaveBeenCalled());
  expect(create.mock.calls[0][1].metadata).not.toHaveProperty("preferred_workflow_id");
});

it("keeps saved history in fullscreen without reviving old generation proposals", async () => {
  const user = userEvent.setup();
  const message: Message = { id: "voice-draft", conversation_id: "voice-chat", role: "assistant", content: "An angel above a quiet harbour.", metadata: { generation_prompt: "An angel above a quiet harbour", workflow_id: "assistant-old" }, created_at: "" };
  vi.spyOn(api, "conversations").mockResolvedValue([{ id: "voice-chat", project_id: "p", title: "Harbour session", created_at: "", updated_at: "" }]);
  vi.spyOn(api, "messages").mockResolvedValue([message]);
  const old = { id: "assistant-old", required_inputs: [] } as unknown as Workflow;
  render(<AssistantWorkspace projectId="p" visible workflows={[old]} workflowsLoading={false} workflowsError={null} onRetry={vi.fn()} />);
  await screen.findByText(message.content);
  await user.click(await screen.findByRole("button", { name: "Fullscreen voice" }));
  const session = within(screen.getByRole("dialog", { name: /Darius/ }));
  expect(session.getByText(message.content)).toBeVisible();
  expect(session.queryByRole("button", { name: "Review generation here" })).toBeNull();
  expect(session.queryByText("Choose test workflow")).toBeNull();
  expect(screen.getByRole("dialog", { name: /Darius/ })).toBeVisible();
});
