import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { VoiceGallery } from "./voice-gallery";
import type { Asset } from "@/lib/types";

const descriptor = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const closeDescriptor = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } });
});
afterEach(() => {
  cleanup();
  if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, "showModal", descriptor); else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  if (closeDescriptor) Object.defineProperty(HTMLDialogElement.prototype, "close", closeDescriptor); else Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
  vi.restoreAllMocks();
});
const assets = ["Forest opening", "River sunset"].map((name, index) => ({ id: String(index), project_id: "p", kind: "image", metadata: { display_name: name } } as unknown as Asset));

it("keeps voice numbers stable during search and opens exactly the chosen asset", () => {
  const select = vi.fn();
  render(<VoiceGallery assets={assets} onSelect={select} onClose={vi.fn()} />);
  fireEvent.change(screen.getByRole("textbox", { name: "Search gallery" }), { target: { value: "river" } });
  expect(screen.queryByRole("button", { name: "Open image 1: Forest opening" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open image 2: River sunset" }));
  expect(select).toHaveBeenCalledWith(assets[1]);
});

it("closes only the gallery on Escape and keeps search emptiness understandable", () => {
  const close = vi.fn();
  render(<VoiceGallery assets={assets} onSelect={vi.fn()} onClose={close} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "missing" } });
  expect(screen.getByText(/No names match/)).toBeVisible();
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true, cancelable: true }));
  expect(close).toHaveBeenCalledOnce();
});
