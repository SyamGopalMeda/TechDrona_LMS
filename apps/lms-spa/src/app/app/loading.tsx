import { Skeleton } from "@/components/ui";

/** Learner portal segment loading state (FE-33): shown inside the portal shell while a page streams. */
export default function Loading() {
  return (
    <div aria-busy="true" className="space-y-4">
      <span className="sr-only">Loading…</span>
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}
