import { PageHeader } from "@/components/ui";

/**
 * Honest placeholder for screens that portal agents have not built yet. Shows no data
 * (no fake numbers) and names the PRD screen it stands for.
 */
export function NotImplemented({ title, screen, description }: { title: string; screen: string; description?: string }) {
  return (
    <div>
      <PageHeader title={title} eyebrow={screen} description={description} />
      <div role="status" className="rounded-xl border border-dashed border-line-strong bg-surface p-8 text-center">
        <p className="font-display text-lg font-semibold text-fg">Not yet implemented</p>
        <p className="mx-auto mt-1 max-w-prose text-sm text-fg-muted">
          This screen is part of the plan but has not been built yet. No data is shown here.
        </p>
      </div>
    </div>
  );
}
