import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { Message } from "@/lib/types";
import { FullscreenVoice } from "./fullscreen-voice";
import { rememberWorkspaceValue, readWorkspaceValue } from "@/lib/workspace-session";

vi.mock("./liquid-orb", () => ({ LiquidOrb: ({ mood }: { mood: string }) => <span data-testid="orb" data-mood={mood} /> }));
afterEach(() => vi.restoreAllMocks());
const history: Message[] = [
  { id: "u1", conversation_id: "c", role: "user", content: "Let’s imagine a moonlit harbour.", metadata: {}, created_at: "" },
  { id: "a1", conversation_id: "c", role: "assistant", content: "A quiet harbour, blue light on the water.", metadata: {}, created_at: "" },
];
it("opens chat with a visible composer and no microphone activation", () => {
  const base=props();render(<FullscreenVoice {...base} phase="off" initialChat onSend={vi.fn()} />);
  expect(screen.getByRole("textbox",{name:"Message Darius in fullscreen"})).toBeVisible();
  expect(screen.getByRole("button",{name:"Chat"})).toHaveAttribute("aria-pressed","true");
  expect(base.onStart).not.toHaveBeenCalled();
});
it("keeps the next typed thought while a chat reply is pending", async () => {
  let finish!:()=>void;const onSend=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
  render(<FullscreenVoice {...props()} phase="off" initialChat draftKey="next-chat-thought" onSend={onSend}/>);
  const input=screen.getByRole("textbox",{name:"Message Darius in fullscreen"});
  fireEvent.change(input,{target:{value:"First concept"}});fireEvent.click(screen.getByRole("button",{name:"Send fullscreen message"}));
  expect(input).toHaveValue("");fireEvent.change(input,{target:{value:"Keep the uniform orange"}});
  await act(async()=>finish());expect(input).toHaveValue("Keep the uniform orange");expect(onSend).toHaveBeenCalledOnce();
});
it("distinguishes returning to chat, pausing voice and ending the session", async () => {
  const base = props(), onEnd = vi.fn(), user = userEvent.setup();
  render(<FullscreenVoice {...base} onEnd={onEnd} />);
  await user.click(screen.getByRole("button", { name: "Close fullscreen voice" }));
  expect(base.onClose).toHaveBeenCalledOnce(); expect(base.onStop).not.toHaveBeenCalled(); expect(onEnd).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Pause voice" }));
  expect(base.onStop).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "End voice session" }));
  expect(onEnd).toHaveBeenCalledOnce(); expect(base.onClose).toHaveBeenCalledOnce();
});
function props() {
  return { phase: "listening" as const, connecting: false, busy: false, transcript: "", reply: "", error: "", cloud: false, disabled: false,
    canInterrupt: false, onStart: vi.fn(), onStop: vi.fn(), onClose: vi.fn(), onEngineChange: vi.fn(), messages: history };
}
it("reuses the site's decorative background without adding an interactive layer", () => {
  render(<FullscreenVoice {...props()} />);
  const background = screen.getByRole("dialog").querySelector(":scope > .ambient-scene");
  expect(background).toHaveAttribute("aria-hidden", "true");
  expect(background?.querySelectorAll(".ambient-orbit")).toHaveLength(3);
});
it("shares the conversation draft and requires attachment review instead of sending text alone", async () => {
  const user = userEvent.setup(), onSend = vi.fn();
  rememberWorkspaceValue("composer:p:chat:text", "My shared draft");
  rememberWorkspaceValue("composer:p:chat:attachments", [{ status: "ready" }]);
  render(<FullscreenVoice {...props()} draftKey="p:chat" onSend={onSend} />);
  await user.click(screen.getByRole("button", { name: "Type a message" }));
  const input = screen.getByRole("textbox", { name: "Message Darius in fullscreen" });
  expect(input).toHaveValue("My shared draft");
  await user.type(input, " updated");
  expect(readWorkspaceValue("composer:p:chat:text")).toBe("My shared draft updated");
  expect(screen.getByRole("button", { name: "Send fullscreen message" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return to chat to review and send" })).toBeVisible();
  expect(onSend).not.toHaveBeenCalled();
});
it("keeps the conversation and visual results as captions stream", async () => {
  const base = props();
  const { rerender } = render(<FullscreenVoice {...base} transcript="Add a little mist" renderMessage={(message) => message.role === "assistant" ? <button>Inspect harbour render</button> : null} />);
  expect(screen.getByText(history[0].content)).toBeVisible();
  expect(screen.getByLabelText("Your live transcript")).toHaveTextContent("Add a little mist");
  rerender(<FullscreenVoice {...base} phase="speaking" busy streamedReply="The mist drifts" renderMessage={(message) => message.role === "assistant" ? <button>Inspect harbour render</button> : null} />);
  expect(screen.getByTestId("orb")).toHaveAttribute("data-mood", "speaking");
  expect(screen.getByRole("status")).toHaveTextContent("Darius is speaking");
  expect(screen.getByLabelText("Darius reply in progress")).toHaveTextContent("The mist drifts");
  await userEvent.click(screen.getByRole("button", { name: "Toggle captions" }));
  expect(screen.queryByText(history[0].content)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Inspect harbour render" })).toBeVisible();
});
it("replaces streamed text with one saved answer", () => {
  const base = props();
  const { rerender } = render(<FullscreenVoice {...base} busy streamedReply="A new answer" />);
  rerender(<FullscreenVoice {...base} messages={[...history, { ...history[1], id: "a2", content: "A new answer" }]} />);
  expect(screen.getAllByText("A new answer")).toHaveLength(1);
  expect(screen.queryByLabelText("Darius reply in progress")).not.toBeInTheDocument();
});
it("does not duplicate a submitted transcript and labels held input", () => {
  const base = props();
  const { rerender } = render(<FullscreenVoice {...base} phase="thinking" busy messages={[history[0]]} transcript={history[0].content} />);
  expect(screen.getAllByText(history[0].content)).toHaveLength(1);
  rerender(<FullscreenVoice {...base} phase="thinking" busy waitingForReply transcript="And add a boat" />);
  expect(screen.getByLabelText("Your live transcript")).toHaveTextContent("next message held");
});
it("lets the user browse history without being pulled down by streaming", async () => {
  const base = props();
  const { rerender } = render(<FullscreenVoice {...base} />);
  const area = screen.getByRole("region", { name: "Fullscreen conversation" });
  Object.defineProperties(area, { scrollHeight: { configurable: true, value: 1600 }, clientHeight: { configurable: true, value: 400 } });
  await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
  area.scrollTop = 150;
  fireEvent.wheel(area, { deltaY: -200 });
  fireEvent.scroll(area);
  rerender(<FullscreenVoice {...base} streamedReply="Another sentence" />);
  await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
  expect(area.scrollTop).toBe(150);
  await userEvent.click(screen.getByRole("button", { name: "Back to live" }));
  expect(area.scrollTop).toBe(1600);
});
it("sends typed fallback without leaving fullscreen and retains failed drafts", async () => {
  const onSend = vi.fn().mockRejectedValueOnce(new Error("Connection interrupted")).mockResolvedValueOnce(undefined);
  render(<FullscreenVoice {...props()} onSend={onSend} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Type a message" }));
  const input = screen.getByRole("textbox", { name: "Message Darius in fullscreen" });
  await user.type(input, "Add a red boat");
  await user.click(screen.getByRole("button", { name: "Send fullscreen message" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection interrupted");
  expect(input).toHaveValue("Add a red boat");
  await user.click(screen.getByRole("button", { name: "Send fullscreen message" }));
  await waitFor(() => expect(input).toHaveValue(""));
  expect(onSend).toHaveBeenLastCalledWith("Add a red boat");
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("traps focus across the composer and restores the previous focus on exit", async () => {
  const user = userEvent.setup();
  const trigger = document.createElement("button"); trigger.textContent = "Launch voice"; document.body.append(trigger); trigger.focus();
  const base = props();
  const { unmount } = render(<FullscreenVoice {...base} onSend={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Type a message" }));
  expect(screen.getByRole("textbox", { name: "Message Darius in fullscreen" })).toHaveFocus();
  const end = screen.getByRole("button", { name: "End voice session" }); end.focus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Close fullscreen voice" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" }); expect(base.onClose).toHaveBeenCalledOnce();
  unmount(); expect(trigger).toHaveFocus(); expect(trigger.inert).toBeFalsy(); trigger.remove();
});
it("keeps task approval controls available within the session", () => {
  render(<FullscreenVoice {...props()} actions={<button>Approve & queue</button>} />);
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve & queue" })).toBeEnabled();
});

it("lets an expanded native media preview handle Escape without ending the session", () => {
  const base = props();
  render(<FullscreenVoice {...base} actions={<dialog open aria-label="Media preview"><button>Close preview</button></dialog>} />);
  fireEvent.keyDown(screen.getByRole("button", { name: "Close preview" }), { key: "Escape" });
  expect(base.onClose).not.toHaveBeenCalled();
});
