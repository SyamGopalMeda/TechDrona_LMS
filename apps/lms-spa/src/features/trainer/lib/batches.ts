"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api/client";
import type { Batch, BatchMember } from "@/features/batches/lib/types";
import { hasPlatformGrant, trainerBatchIds, useMyGrants } from "../shared/grants";
import { seg } from "../shared/use-api";

/**
 * Batches the signed-in staff member works in. Batch staff get their RBAC-06 grants
 * (`trainer` / `evaluator` @ batch) → ORG-22 for each. Platform-scope staff get every
 * non-archived batch from `GET batches` in the Evaluator portal; in the Teacher portal
 * (`/trainer`) an Admin gets only the batches they are the teacher of (`GET batches?mine=true`):
 * the Admin portal is where every batch is managed.
 */
export function useTrainerBatches() {
  const grants = useMyGrants();
  const teacherPortal = isTeacherPortal(usePathname());
  const [batches, setBatches] = useState<Batch[] | undefined>();
  const [error, setError] = useState<unknown>(null);
  const ids = trainerBatchIds(grants.data?.data).join(",");
  const platform = hasPlatformGrant(grants.data?.data);

  useEffect(() => {
    if (!grants.data) return;
    let live = true;
    const list = ids ? ids.split(",") : [];
    const load = platform
      ? (teacherPortal
          ? api.get<{ data: Batch[] }>("batches", { query: { mine: true } })
          : api.get<{ data: Batch[] }>("batches")
        ).then((r) => (r.data ?? []).filter((b) => b.status !== "archived"))
      : Promise.all(list.map((id) => api.get<Batch>(`batches/${seg(id)}`)));
    load.then((b) => live && setBatches(b)).catch((e: unknown) => live && setError(e));
    return () => {
      live = false;
    };
  }, [grants.data, ids, platform, teacherPortal]);

  return {
    batches,
    error: grants.error ?? error,
    loading:
      grants.loading ||
      (grants.data !== undefined && batches === undefined && !error),
    reload: grants.reload,
  };
}

/** True inside the Teacher (trainer) portal, where lists are limited to the batches the user teaches. */
export function isTeacherPortal(pathname: string | null | undefined): boolean {
  return pathname === "/trainer" || !!pathname?.startsWith("/trainer/");
}

/**
 * Query flag for staff assignment lists (`GET assignments?scope=mine`): in the Teacher portal,
 * `teaching=true` makes the api ignore platform grants, so an Admin who teaches a batch sees that
 * batch's work there rather than every assignment. Elsewhere (Evaluator portal) it adds nothing.
 */
export function useTeachingQuery(): { teaching?: true } {
  return isTeacherPortal(usePathname()) ? { teaching: true } : {};
}

/**
 * user_id → full name for the members of the given batches (ORG-25). Test attempt and
 * submission rows from the api carry only `user_id`, so names come from batch rosters.
 */
export function useMemberNames(batchIds: (string | null | undefined)[]) {
  const key = [...new Set(batchIds.filter((x): x is string => !!x))]
    .sort()
    .join(",");
  const [names, setNames] = useState<Record<string, string | null>>({});

  useEffect(() => {
    let live = true;
    const list = key ? key.split(",") : [];
    Promise.all(
      list.map((id) =>
        api
          .get<{ data: BatchMember[] }>(`batches/${seg(id)}/members`)
          .catch(() => ({ data: [] as BatchMember[] })),
      ),
    )
      .then((res) => {
        if (!live) return;
        const out: Record<string, string | null> = {};
        for (const r of res)
          for (const m of r.data) out[m.user_id] = m.full_name;
        setNames(out);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [key]);

  return (userId: string) => names[userId] ?? "Student";
}
