/** FE-33: streaming fallback for public pages that wait on the api (catalog, placement, status). */
export default function Loading() {
  return (
    <div role="status" aria-live="polite" className="space-y-4">
      <span className="sr-only">Loading</span>
      <div className="h-8 w-1/3 animate-pulse rounded-md bg-surface-subtle" />
      <div className="h-4 w-2/3 animate-pulse rounded-md bg-surface-subtle" />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="h-32 animate-pulse rounded-xl bg-surface-subtle" />
        <div className="h-32 animate-pulse rounded-xl bg-surface-subtle" />
      </div>
    </div>
  );
}
