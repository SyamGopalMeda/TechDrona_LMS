/**
 * Pick a college first (forms opened outside a college page): type-to-filter list, arrow keys + Enter, or click.
 *
 *   const id = await pickCollege("Record an enrollment");    // null when cancelled
 */
import "../styles/views/ops.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePortalQuery } from "../lib/cache";
import type { CollegeRow, PortalMeta } from "../lib/types";
import { Button } from "../ui/Button";
import { cx } from "../ui/context";
import { ErrorCard, Skeleton } from "../ui/Feedback";
import { Modal } from "../ui/Overlay";
import { openDialog } from "./host";
import { rowsOf } from "./util";

interface Item {
  id: string;
  label: string;
  sub: string;
  hay: string;
  targeted: number;
}

export function PickCollegeDialog({ open = true, title, onDone }: { open?: boolean; title: string; onDone: (id: string | null) => void }) {
  const cols = usePortalQuery<unknown>("colleges", { ttl: 60_000 });
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  const all = useMemo<Item[]>(() => {
    const dn = new Map((meta.data?.districts ?? []).map((d) => [d.id, d.name]));
    return rowsOf<CollegeRow>(cols.data)
      .map((c) => ({
        id: c.id,
        label: c.short_name || c.name,
        sub: [c.short_name && c.short_name !== c.name ? c.name : null, dn.get(c.district_id) || c.district_id].filter(Boolean).join(" · "),
        hay: `${c.name} ${c.short_name || ""} ${dn.get(c.district_id) || ""}`.toLowerCase(),
        targeted: c.targeted ? 1 : 0,
      }))
      .sort((a, b) => b.targeted - a.targeted || a.label.localeCompare(b.label));
  }, [cols.data, meta.data]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter((c) => !t || t.split(/\s+/).every((w) => c.hay.includes(w))).slice(0, 60);
  }, [all, q]);
  const active = Math.min(idx, Math.max(shown.length - 1, 0));

  useEffect(() => {
    box.current?.querySelector(".is-active")?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const note = shown.length ? (all.length > shown.length ? `Showing ${shown.length} of ${all.length}. Keep typing to narrow down.` : "") : "No college matches. Check the spelling or try the district name.";

  return (
    <Modal
      open={open}
      title={title}
      onClose={() => onDone(null)}
      footer={
        <Button tone="ghost" onClick={() => onDone(null)}>
          Cancel
        </Button>
      }
    >
      {cols.loading && !cols.data ? (
        <Skeleton lines={4} card={false} />
      ) : cols.error && !cols.data ? (
        <ErrorCard title="Could not load colleges" error={cols.error} retry={() => void cols.reload()} />
      ) : (
        <div className="vf-form">
          <p className="vf-intro">Choose the college first. Type to search, use the arrow keys and Enter, or click.</p>
          <input
            type="search"
            className="td-input"
            placeholder="Type a college or district name…"
            aria-label="Search colleges"
            autoFocus
            autoComplete="off"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                setIdx(Math.max(0, Math.min(shown.length - 1, active + (e.key === "ArrowDown" ? 1 : -1))));
              }
              if (e.key === "Enter") {
                e.preventDefault();
                if (shown[active]) onDone(shown[active].id);
              }
            }}
          />
          <p className="vf-pick-note" aria-live="polite">
            {note}
          </p>
          <div className="vf-pick" role="listbox" aria-label="Colleges" ref={box}>
            {shown.map((c, i) => (
              <button key={c.id} type="button" role="option" aria-selected={i === active} className={cx("vf-pick-opt", i === active && "is-active")} onClick={() => onDone(c.id)}>
                <span className="vf-pick-name">
                  {c.label}
                  {c.targeted ? <span className="vf-pick-tag">Targeted</span> : null}
                </span>
                <span className="vf-pick-sub">{c.sub}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Old forms.js pickCollege(ctx, title): resolves the college id, or null when cancelled. */
export function pickCollege(title: string): Promise<string | null> {
  return openDialog<string>((done) => <PickCollegeDialog title={title} onDone={done} />);
}
