import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { Asset } from "@/lib/types";
import { AssetThumbnailPicker } from "./asset-thumbnail-picker";

const asset = { id: "forest", project_id: "p", kind: "image", role: "generation", metadata: { display_name: "Forest opening" } } as unknown as Asset;
it("selects from named thumbnails and excludes foreign/derivative media", async () => {
  const user = userEvent.setup(), change = vi.fn();
  render(<AssetThumbnailPicker label="Add reference" assets={[asset, { ...asset, id: "foreign", project_id: "other", metadata: { display_name: "Private media" } }, { ...asset, id: "thumb", role: "derivative" }]} projectId="p" value="" onChange={change} />);
  expect(screen.getAllByRole("img")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: /Private media/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Add reference: Forest opening" }));
  expect(change).toHaveBeenCalledWith("forest");
});
