import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef } from "react";
import { expect, it } from "vitest";
import { readWorkspaceValue, useWorkspaceScroll, useWorkspaceState } from "./workspace-session";
import { useDariusStore } from "./store";

function Draft({ scope }: { scope: string }) {
  const [text, setText] = useWorkspaceState(scope, "");
  return <input aria-label="Draft" value={text} onChange={event => setText(event.target.value)} />;
}
it("restores an app's transient state across unmounts without browser storage", async () => {
  const user = userEvent.setup();
  const first = render(<Draft scope="p:conversation-one" />);
  await user.type(screen.getByLabelText("Draft"), "Keep this thought"); first.unmount();
  const other = render(<Draft scope="p:conversation-two" />);
  expect(screen.getByLabelText("Draft")).toHaveValue(""); other.unmount();
  render(<Draft scope="p:conversation-one" />);
  expect(screen.getByLabelText("Draft")).toHaveValue("Keep this thought");
  expect(localStorage.getItem("p:conversation-one")).toBeNull();
});
it("keeps asynchronous draft updates with their original owner after unmount", () => {
  let update!: (next: string) => void;
  function Owner() { const [text, setText] = useWorkspaceState("upload-owner", "uploading"); useEffect(() => { update = setText; }, [setText]); return <span>{text}</span>; }
  const first = render(<Owner />); first.unmount();
  act(() => update("ready")); render(<Owner />);
  expect(screen.getByText("ready")).toBeVisible();
});
it("restores scroll offsets from the actual scroll region", () => {
  function Scroll() { const ref = useRef<HTMLDivElement>(null); useWorkspaceScroll("library-scroll", ref); return <div data-testid="scroll" ref={ref} />; }
  const first = render(<Scroll />), region = screen.getByTestId("scroll");
  region.scrollTop = 350; region.dispatchEvent(new Event("scroll")); first.unmount();
  render(<Scroll />); expect(screen.getByTestId("scroll").scrollTop).toBe(350);
});
it("restores each project's references and selection without mixing ownership", () => {
  useDariusStore.setState({ activeProjectId: "owner-a", referenceAssetIds: ["image-a"], selection: { type: "asset", id: "image-a" } });
  const store = useDariusStore.getState(); store.setActiveProject("owner-b");
  expect(useDariusStore.getState().referenceAssetIds).toEqual([]);
  useDariusStore.getState().addReferenceAsset("image-b");
  store.setActiveProject("owner-a");
  expect(useDariusStore.getState()).toMatchObject({ referenceAssetIds: ["image-a"], selection: { type: "asset", id: "image-a" } });
  store.setActiveProject("owner-b"); expect(useDariusStore.getState().referenceAssetIds).toEqual(["image-b"]);
  expect(readWorkspaceValue("project-context:owner-a")).toMatchObject({ referenceAssetIds: ["image-a"] });
});
