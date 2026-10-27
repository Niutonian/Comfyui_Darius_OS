import React, { type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api-client";
import { useProjectAssets } from "./queries";

afterEach(() => vi.restoreAllMocks());

describe("project asset queries", () => {
  it("polls so completed generation assets appear without a manual refresh", async () => {
    vi.spyOn(api, "assets").mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useProjectAssets("project-1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.assets).toHaveBeenCalledWith({ project_id: "project-1", limit: 500 });
    await waitFor(() => expect(api.assets).toHaveBeenCalledTimes(2), { timeout: 3_000 });
  });
});
