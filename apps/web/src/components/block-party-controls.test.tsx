import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api-client";
import type { BlockPartyImportResult } from "@/lib/types";
import { BlockPartyCheck, BlockPartyImport } from "./block-party-controls";

afterEach(() => vi.restoreAllMocks());
const imported: BlockPartyImportResult = {
  workflow_id: "block-party/still-123.json", name: "Party still", already_imported: false, output_kind: "image", note: "No render.",
  registration: { workflow_id: "block-party/still-123.json", version: 1, status: "ready", source_digest: "source", graph_digest: "graph", contract_digest: "contract", scene_slots: ["1.text"], protected_slots: [], unresolved_slots: [], processing_only: false, fields: [] },
};

it("imports one ZIP and refreshes the catalog without saving defaults or rendering", async () => {
  const upload = vi.spyOn(api, "importBlockParty").mockResolvedValue(imported);
  const save = vi.spyOn(api, "saveGlobalWorkflowDefaults");
  const onImported = vi.fn().mockResolvedValue(undefined);
  render(<BlockPartyImport onImported={onImported} />);
  const file = new File(["fixture"], "party.zip", { type: "application/zip" });
  await userEvent.upload(screen.getByLabelText("Block Party job ZIP"), file);
  expect(await screen.findByRole("status")).toHaveTextContent("Party still: imported");
  expect(upload).toHaveBeenCalledWith(file);
  expect(onImported).toHaveBeenCalledOnce();
  expect(save).not.toHaveBeenCalled();
});

it("retains the current catalog on a rejected package", async () => {
  vi.spyOn(api, "importBlockParty").mockRejectedValue(new Error("Input slot does not match the workflow"));
  const onImported = vi.fn();
  render(<BlockPartyImport onImported={onImported} />);
  await userEvent.upload(screen.getByLabelText("Block Party job ZIP"), new File(["bad"], "bad.zip", { type: "application/zip" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Input slot does not match");
  expect(onImported).not.toHaveBeenCalled();
});

it("checks dependencies only on request and explains preparation blockers", async () => {
  const check = vi.spyOn(api, "blockPartyReadiness").mockResolvedValue({ ready: false,
    issues: [{ code: "missing_model", message: "Missing exact model; prepare it in Block Party" }], warnings: ["Unknown nodes still require review"],
    checked: { models: 0, node_packs: 1, node_classes: 8 }, checked_at: "now", note: "No installation or render was started." });
  render(<BlockPartyCheck workflowId={imported.workflow_id} />);
  expect(check).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Check dependencies" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Preparation needed");
  expect(screen.getByRole("status")).toHaveTextContent("Missing exact model");
  expect(check).toHaveBeenCalledWith(imported.workflow_id);
});
