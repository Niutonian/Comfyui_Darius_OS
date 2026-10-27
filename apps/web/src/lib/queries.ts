"use client";

import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api-client";
import type { Asset, Job } from "./types";
import { useEffect, useState } from "react";
import { connectProjectSync, type SyncStatus } from "./project-sync";
import { useDariusStore } from "./store";

export const queryKeys = {
  health: ["health"] as const,
  llmSettings: ["llm-settings"] as const,
  projects: ["projects"] as const,
  workflows: ["workflows"] as const,
  projectWorkflows: (projectId: string) => ["project-workflows", { projectId }] as const,
  projectAssets: (projectId: string) => ["assets", { projectId }] as const,
  characters: (projectId: string) => ["characters", { projectId }] as const,
  scenes: (projectId: string) => ["scenes", { projectId }] as const,
  shots: (sceneId: string) => ["shots", { sceneId }] as const,
  timelines: (projectId: string) => ["timelines", { projectId }] as const,
  timelineVersions: (timelineId: string) => ["timeline-versions", timelineId] as const,
  projectJobs: (projectId: string) => ["jobs", { projectId }] as const,
  job: (id: string) => ["job", id] as const,
  jobRun: (id: string) => ["job-run", id] as const,
  asset: (id: string) => ["asset", id] as const,
  provenance: (id: string) => ["provenance", id] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.health,
    refetchInterval: 15_000,
    retry: 1,
  });
}

export function useLlmSettings() {
  return useQuery({ queryKey: queryKeys.llmSettings, queryFn: api.llmSettings, retry: 1 });
}

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: api.projects, retry: 1 });
}

export function useWorkflows() {
  const projectId = useDariusStore((state) => state.activeProjectId);
  return useQuery({ queryKey: [...queryKeys.workflows, projectId], queryFn: () => api.workflows(projectId), retry: 1 });
}

export function useProjectWorkflows(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.projectWorkflows(projectId ?? "none"),
    queryFn: () => api.projectWorkflows(projectId!),
    enabled: Boolean(projectId),
    retry: 1,
  });
}

export function useProjectJobs(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.projectJobs(projectId ?? "none"),
    queryFn: () => api.jobs({ project_id: projectId! }),
    enabled: Boolean(projectId),
    refetchInterval: 2_500,
    retry: 1,
  });
}

/** Keep project views responsive to durable job and assistant activity events. */
export function useProjectEventStream(projectId: string | null) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SyncStatus>("connecting");
  useEffect(() => {
    if (!projectId) return;
    return connectProjectSync(projectId, `${api.eventsStreamUrl(projectId)}&live=true`, ({ full, types }) => {
      const changed = (...prefixes: string[]) => full || types.some((type) => prefixes.some((prefix) => type.startsWith(prefix)));
      const invalidate = (queryKey: readonly unknown[]) => { void queryClient.invalidateQueries({ queryKey }); };
      if (changed("project.")) invalidate(queryKeys.projects);
      if (changed("job.", "generation.", "timeline.render", "action_plan.", "assistant.")) {
        invalidate(queryKeys.projectJobs(projectId)); invalidate(["job"]); invalidate(["job-run"]);
      }
      if (changed("asset.", "generation.completed", "timeline.render_completed")) {
        invalidate(queryKeys.projectAssets(projectId)); invalidate(["asset"]); invalidate(["provenance"]);
      }
      if (changed("workflows.")) { invalidate(queryKeys.projectWorkflows(projectId)); invalidate(queryKeys.workflows); }
      if (changed("character.")) invalidate(queryKeys.characters(projectId));
      if (changed("scene.")) invalidate(queryKeys.scenes(projectId));
      if (changed("shot.", "scene.", "asset.", "job.", "generation.")) invalidate(["shot-board", projectId]);
      if (changed("shot.")) invalidate(["shots"]);
      if (changed("timeline.")) { invalidate(queryKeys.timelines(projectId)); invalidate(["timeline-versions"]); }
      if (changed("local_rendering.")) invalidate(["local-rendering", projectId]);
      if (changed("canvas.")) { invalidate(["canvases", projectId]); invalidate(["canvas", projectId]); }
    }, setStatus);
  }, [projectId, queryClient]);
  return status;
}


export function useKnownJobs(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.job(id),
      queryFn: () => api.job(id),
      refetchInterval: (query: { state: { data?: Job } }) =>
        ["queued", "running"].includes(query.state.data?.status ?? "") ? 2_500 : false,
      retry: 1,
    })),
    combine: (results) => ({
      jobs: results.flatMap((result) => (result.data ? [result.data] : [])),
      isLoading: results.some((result) => result.isLoading),
      hasError: results.some((result) => result.isError),
    }),
  });
}

export function useKnownAssets(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.asset(id),
      queryFn: () => api.asset(id),
      retry: 1,
    })),
    combine: (results) => ({
      assets: results.flatMap((result) => (result.data ? [result.data as Asset] : [])),
      isLoading: results.some((result) => result.isLoading),
      hasError: results.some((result) => result.isError),
    }),
  });
}

export function useProjectAssets(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.projectAssets(projectId ?? "none"),
    queryFn: () => api.assets({ project_id: projectId!, limit: 500 }),
    enabled: Boolean(projectId),
    refetchInterval: 2_500,
    retry: 1,
  });
}

export function useCharacters(projectId: string | null) {
  return useQuery({ queryKey: queryKeys.characters(projectId ?? "none"), queryFn: () => api.characters(projectId!), enabled: Boolean(projectId), retry: 1 });
}

export function useScenes(projectId: string | null) {
  return useQuery({ queryKey: queryKeys.scenes(projectId ?? "none"), queryFn: () => api.scenes(projectId!), enabled: Boolean(projectId), retry: 1 });
}

export function useShots(sceneId: string | null) {
  return useQuery({ queryKey: queryKeys.shots(sceneId ?? "none"), queryFn: () => api.shots(sceneId!), enabled: Boolean(sceneId), retry: 1 });
}

export function useTimelines(projectId: string | null) {
  return useQuery({ queryKey: queryKeys.timelines(projectId ?? "none"), queryFn: () => api.timelines(projectId!), enabled: Boolean(projectId), retry: 1 });
}

export function useTimelineVersions(timelineId: string | null) {
  return useQuery({ queryKey: queryKeys.timelineVersions(timelineId ?? "none"), queryFn: () => api.timelineVersions(timelineId!), enabled: Boolean(timelineId), retry: 1 });
}
