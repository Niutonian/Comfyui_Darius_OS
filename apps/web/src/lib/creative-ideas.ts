import { request } from "./api-client";
export type CreativeIdea = { id: string; projectId: string; revision: string; title: string; content: string; sourceMessageId: string; sourceText: string; conversationId: string; archived: boolean; updatedAt: string };
export type IdeaInput = Pick<CreativeIdea, "id" | "title" | "content" | "sourceMessageId" | "sourceText">;
const root = (project: string) => `/projects/${encodeURIComponent(project)}/ideas`;
export const ideasApi = {
  list: (project: string, archived = false) => request<CreativeIdea[]>(`${root(project)}?archived=${archived}`),
  save: (project: string, input: IdeaInput) => request<CreativeIdea>(root(project), {method:"POST", body:JSON.stringify(input)}),
  state: (project: string, idea: CreativeIdea, archived: boolean) => request<CreativeIdea>(`${root(project)}/${encodeURIComponent(idea.id)}/state`, {method:"POST", body:JSON.stringify({revision:idea.revision, archived})}),
};
