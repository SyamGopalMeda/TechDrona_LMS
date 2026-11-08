"use client";

import { Button, Select, type SelectProps } from "@/components/ui";
import { useApi } from "@/features/trainer/shared/use-api";

/** PLC-01 `GET placement/subjects` node (active taxonomy, nested). */
export interface TopicNode {
  id: string;
  parent_id: string | null;
  kind: string;
  slug: string;
  name: string;
  path: string;
  depth: number;
  position: number;
  is_active: boolean;
  question_count: number;
  children: TopicNode[];
}

export interface TopicOption {
  id: string;
  name: string;
  /** Indented label ("Aptitude › Percentages"). */
  label: string;
  level: number;
  node: TopicNode;
}

/** Depth-first flattening of the subject tree in display order. */
export function flattenTopics(items: TopicNode[] | undefined, level = 0, trail: string[] = []): TopicOption[] {
  const out: TopicOption[] = [];
  for (const n of items ?? []) {
    const names = [...trail, n.name];
    out.push({ id: n.id, name: n.name, label: names.join(" › "), level, node: n });
    out.push(...flattenTopics(n.children, level + 1, names));
  }
  return out;
}

/**
 * Topic tree. `"active"` (default) = PLC-01 `placement/subjects` for pickers; `"studio"` =
 * PLC-02b `studio/topics` (taxonomy managers, includes deactivated nodes so they can be reactivated).
 */
export function useTopics(source: "active" | "studio" = "active") {
  const state = useApi<{ items: TopicNode[] }>(source === "studio" ? "studio/topics" : "placement/subjects");
  return { ...state, options: flattenTopics(state.data?.items) };
}

/**
 * Topic picker (audit ADM-51: no raw UUIDs). Lists the active taxonomy from PLC-01; while it
 * loads the select is disabled, and a load failure shows a retry instead of an empty list.
 */
export function TopicSelect({
  topics,
  placeholder = "Choose a topic",
  ...props
}: Omit<SelectProps, "options"> & { topics: ReturnType<typeof useTopics> }) {
  if (topics.error)
    return (
      <div className="flex items-center gap-2 text-sm text-danger-fg" role="alert">
        Couldn&apos;t load topics.
        <Button size="sm" variant="secondary" onClick={() => void topics.reload()}>
          Retry
        </Button>
      </div>
    );
  return (
    <Select
      {...props}
      disabled={props.disabled || topics.loading}
      placeholder={topics.loading ? "Loading topics…" : topics.options.length ? placeholder : "No topics yet — add them under Taxonomy"}
      options={topics.options.map((t) => ({ value: t.id, label: t.label }))}
    />
  );
}

/** Generic "pick one of a list" select for lesson references (tests, coding problems, assignments). */
export function RefSelect({
  state,
  noun,
  ...props
}: Omit<SelectProps, "options"> & {
  state: { data?: { id: string; label: string }[]; loading: boolean; error: unknown; reload: () => Promise<void> };
  noun: string;
}) {
  if (state.error)
    return (
      <div className="flex items-center gap-2 text-sm text-danger-fg" role="alert">
        Couldn&apos;t load {noun}s.
        <Button size="sm" variant="secondary" onClick={() => void state.reload()}>
          Retry
        </Button>
      </div>
    );
  const opts = state.data ?? [];
  return (
    <Select
      {...props}
      disabled={props.disabled || state.loading}
      placeholder={state.loading ? `Loading ${noun}s…` : opts.length ? `Choose a ${noun}` : `No ${noun}s available`}
      options={opts.map((o) => ({ value: o.id, label: o.label }))}
    />
  );
}
