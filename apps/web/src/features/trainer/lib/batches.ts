"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { Batch, BatchMember } from "@/features/batches/lib/types";
import { hasPlatformGrant, trainerBatchIds, useMyGrants } from "../shared/grants";
import { seg } from "../shared/use-api";

/**
 * Batches the signed-in staff member works in. Platform-scope staff (Admin) get every
 * non-archived batch from `GET batches`; batch staff get their RBAC-06 grants
 * (`trainer` / `evaluator` @ batch) → ORG-22 for each.
 */
export function useTrainerBatches() {
  const grants = useMyGrants();
  const [batches, setBatches] = useState<Batch[] | undefined>();
  const [error, setError] = useState<unknown>(null);
  const ids = trainerBatchIds(grants.data?.data).join(",");
  const platform = hasPlatformGrant(grants.data?.data);

  useEffect(() => {
    if (!grants.data) return;
    let live = true;
    const list = ids ? ids.split(",") : [];
    const load = platform
      ? api.get<{ data: Batch[] }>("batches").then((r) => (r.data ?? []).filter((b) => b.status !== "archived"))
      : Promise.all(list.map((id) => api.get<Batch>(`batches/${seg(id)}`)));
    load.then((b) => live && setBatches(b)).catch((e: unknown) => live && setError(e));
    return () => {
      live = false;
    };
  }, [grants.data, ids, platform]);

  return {
    batches,
    error: grants.error ?? error,
    loading:
      grants.loading ||
      (grants.data !== undefined && batches === undefined && !error),
    reload: grants.reload,
  };
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
