import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ShotGenerationDrafts } from "./shot-generation-drafts";

it("reviews the selected shot with its own prompt and references, and links an existing job", () => {
  const review = vi.fn();
  const job = vi.fn();
  render(<ShotGenerationDrafts availableIds={["draft-two"]} onReview={review} onJob={job} value={[
    { brief_id: "shot-1", prompt: "Ellie enters", workflow_id: "draft-one", job_id: "job-one", reference_asset_ids: ["ellie"] },
    { brief_id: "shot-2", prompt: "Giorgio at the counter", workflow_id: "draft-two", reference_asset_ids: ["giorgio"] },
    { brief_id: "shot-3", prompt: "Ellie and Giorgio leave", reference_asset_ids: [] },
  ]} />);
  fireEvent.click(screen.getByText("Shot 2 · Ready for review"));
  fireEvent.click(screen.getByRole("button", { name: "Review shot 2" }));
  expect(review).toHaveBeenCalledWith({ briefId: "shot-2", prompt: "Giorgio at the counter", workflowId: "draft-two", referenceIds: ["giorgio"], jobId: null });
  fireEvent.click(screen.getByText("Shot 1 · Render job saved"));
  fireEvent.click(screen.getByRole("button", { name: "View shot 1 job" }));
  expect(job).toHaveBeenCalledWith("job-one");
  fireEvent.click(screen.getByText("Shot 3 · Needs a workflow"));
  expect(screen.getByRole("button", { name: "Review shot 3" })).toBeDisabled();
});
