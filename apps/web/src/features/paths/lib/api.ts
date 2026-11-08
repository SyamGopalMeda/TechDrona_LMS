import { api, type ApiResult } from "@/lib/api/client";
import type {
  AllocIn,
  Allocation,
  AllocationPreview,
  ArticleDetail,
  Audience,
  CompleteResult,
  Level,
  PathDetail,
  PlayerStep,
  StepIn,
} from "./types";

/** Thin wrappers over the BFF api client for the paths module endpoints. */

export const seg = (v: string) => encodeURIComponent(v);

function data<T>(r: ApiResult<T>): T {
  if (r.kind !== "ok") throw new Error("This action needs an approval first.");
  return r.data;
}

export const pathsApi = {
  createPath: async (body: { title: string; description_md?: string; level?: Level }) =>
    data(await api.post<PathDetail>("paths", body, { idempotencyKey: true })),
  updatePath: async (id: string, body: { title?: string; description_md?: string | null; level?: Level | null }) =>
    data(await api.patch<PathDetail>(`paths/${seg(id)}`, body)),
  archivePath: async (id: string) => {
    await api.delete<void>(`paths/${seg(id)}`);
  },
  saveSteps: async (id: string, steps: StepIn[]) => data(await api.put<PathDetail>(`paths/${seg(id)}/steps`, { steps })),
  publish: async (id: string) => data(await api.post<PathDetail>(`paths/${seg(id)}/publish`, {})),
  aiGenerate: async (body: {
    topic: string;
    style: "mixed" | "textbook";
    level: Level;
    target_hours: number;
    approx_steps: number;
    guidelines?: string;
  }) => data(await api.post<PathDetail>("paths/ai-generate", body, { idempotencyKey: true })),
  preview: async (id: string, body: AllocIn, signal?: AbortSignal) =>
    data(await api.post<AllocationPreview>(`paths/${seg(id)}/allocation-preview`, body, { signal })),
  allocate: async (id: string, body: AllocIn) =>
    data(await api.post<Allocation>(`paths/${seg(id)}/allocations`, body, { idempotencyKey: true })),
  revokeAllocation: async (id: string) => {
    await api.delete<void>(`path-allocations/${seg(id)}`);
  },
  createArticle: async (body: { title: string; subtitle?: string; level?: Level; est_minutes?: number; body_md: string }) =>
    data(await api.post<ArticleDetail>("path-articles", body, { idempotencyKey: true })),
  updateArticle: async (
    id: string,
    body: { title?: string; subtitle?: string | null; level?: Level | null; est_minutes?: number | null; body_md?: string },
  ) => data(await api.patch<ArticleDetail>(`path-articles/${seg(id)}`, body)),
  deleteArticle: async (id: string) => {
    await api.delete<void>(`path-articles/${seg(id)}`);
  },
  publishArticle: async (id: string, body: { audience: Audience; batch_ids?: string[]; user_ids?: string[] }) =>
    data(await api.post<ArticleDetail>(`path-articles/${seg(id)}/publish`, body)),
  unpublishArticle: async (id: string) => data(await api.post<ArticleDetail>(`path-articles/${seg(id)}/unpublish`, {})),
  openStep: async (allocationId: string, stepKey: string) =>
    data(await api.post<PlayerStep>(`me/paths/${seg(allocationId)}/steps/${seg(stepKey)}/open`, {})),
  completeStep: async (allocationId: string, stepKey: string) =>
    data(await api.post<CompleteResult>(`me/paths/${seg(allocationId)}/steps/${seg(stepKey)}/complete`, {})),
};
