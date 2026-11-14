/** Branches tab (old college.js branchesTab / branchCard / branchTable): target branches first, with provenance. */
import { useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { Badge, DataTable, EmptyState, Segmented, StatusBadge, WriteOnly } from "../../ui";
import { addBranch, editBranch } from "../../forms/Branch";
import { Progress } from "../shared/dashboard";
import { addPerson, type CollegeCtx } from "./ctx";
import type { BranchX, CollegeUiPrefs } from "./model";
import { BRANCH_FIG, BranchFigures, Btn, CATEGORY_LABEL, Callout, ISSUE_LABEL, ProgressCell, TARGET_BRANCH_HELP, Vb, branchLabel } from "./parts";

export const BRANCH_SORTS: [string, string][] = [
  ["relevance", "Target branches first"],
  ["gap", "Needs ambassador first"],
  ["progress", "Lowest progress first"],
  ["remaining", "Most remaining"],
  ["eligible", "Most likely prospects"],
  ["strength", "Most seats"],
  ["name", "Branch code A–Z"],
];

export function sortBranchesBy(rows: BranchX[], sort: string): BranchX[] {
  const keys: Record<string, (b: BranchX) => number | string> = {
    name: (b) => String(b.code || b.name),
    strength: (b) => -(b.intake_per_year ?? -1),
    eligible: (b) => -(b.eligible_estimate ?? -1),
    remaining: (b) => -(b.rollup.remaining ?? -1),
    progress: (b) => (b.rollup.target ? (b.rollup.pct ?? 0) : 2),
    gap: (b) => (b._gap ? 0 : 1),
    relevance: (b) => (b.is_relevant ? 0 : 1) * 1e6 - (b.eligible_estimate ?? 0),
  };
  const key = keys[sort] ?? (() => 0);
  return rows.slice().sort((a, b) => {
    const x = key(a);
    const y = key(b);
    return typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number);
  });
}

function OutreachStatus({ b }: { b: BranchX }) {
  const r = b.rollup;
  if (b._gap) return <Badge tone="bad">No ambassador</Badge>;
  if (!b.is_relevant && !b._activeAmbs.length) return <Badge tone="neutral">Not a target branch</Badge>;
  if (r.target && r.on_track === false) return <StatusBadge kind="diagnosis" value={r.diagnosis || "behind_pace"} />;
  if (r.target && r.on_track) return <StatusBadge kind="on_track" value />;
  if (r.reached) return <Badge tone="info">{`${fmt.num(r.reached)} reached`}</Badge>;
  return <Badge tone="warn">Not started</Badge>;
}

function AmbNames({ b }: { b: BranchX }) {
  if (!b._ambs.length) return <span className="vx-muted">None</span>;
  return (
    <span>
      {b._ambs.map((p, i) => (
        <span key={p.id}>
          {i ? ", " : ""}
          <Link to={portalPath.person(p.id)} onClick={(e) => e.stopPropagation()} className={p.status === "inactive" ? "is-inactive" : undefined}>
            {p.full_name}
          </Link>
        </span>
      ))}
    </span>
  );
}

export function BranchesTab({ c: cx, prefs, setPrefs }: { c: CollegeCtx; prefs: CollegeUiPrefs; setPrefs: (p: Partial<CollegeUiPrefs>) => void }) {
  const { d, s } = cx;
  const c = d.college;
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const gapB = s.branches.filter((b) => b._gap);
  const total = s.branches.length;
  let rows = s.branches;
  if (prefs.relevantOnly) rows = rows.filter((b) => b.is_relevant);
  if (q) rows = rows.filter((b) => `${b.code || ""} ${b.name || ""}`.toLowerCase().includes(q));
  rows = sortBranchesBy(rows, prefs.sort);

  let list: ReactNode;
  if (!total)
    list = (
      <EmptyState
        title="No branches recorded yet"
        icon="branch"
        text="Branch-wise intake has not been researched for this college. Add each branch you know (for example CSE, ECE) with its yearly intake and source."
        actions={[
          <WriteOnly key="add">
            <Btn tone="primary" icon="plus" onClick={() => void addBranch({ college_id: c.id })}>
              Add first branch
            </Btn>
          </WriteOnly>,
        ]}
      />
    );
  else if (!rows.length)
    list = (
      <EmptyState
        title={q ? `No branch matches “${query.trim()}”` : "No target branches here"}
        icon="search"
        text={q ? "Try the branch code (e.g. CSE) or part of its name." : "This college has branches, but none count toward the target."}
        actions={[
          {
            label: "Show all branches",
            icon: null,
            onClick: () => {
              setQuery("");
              setPrefs({ relevantOnly: false });
            },
          },
        ]}
      />
    );
  else if (prefs.branchView === "table") list = <BranchTable rows={rows} onOpen={cx.showBranch} />;
  else
    list = (
      <div className="vc-bcards">
        {rows.map((b) => (
          <BranchCard key={b.id} b={b} onOpen={cx.showBranch} />
        ))}
      </div>
    );

  return (
    <div className="vc-tab vc-branches">
      {gapB.length ? (
        <Callout tone="bad" title={`${fmt.plural(gapB.length, "target branch has", "target branches have")} no ambassador`}>
          <div>
            Outreach in these branches has no owner. Tap one to recruit a student ambassador for it.
            <WriteOnly>
              <div className="vc-chips vc-gapchips">
                {gapB.map((b) => (
                  <button key={b.id} type="button" className="vc-chip is-gap" title={`Recruit an ambassador for ${b.name || b.code}`} onClick={() => addPerson(cx, "ambassador", { branch_ids: [b.id] })}>
                    {"+ "}
                    {branchLabel(b)}
                  </button>
                ))}
              </div>
            </WriteOnly>
          </div>
        </Callout>
      ) : null}
      {total ? (
        <div className="vc-btools">
          <input
            type="search"
            className="td-input td-input--sm"
            placeholder="Find a branch (code or name)"
            aria-label="Find a branch"
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select className="td-input td-select td-input--sm" aria-label="Sort branches" value={prefs.sort} onChange={(e) => setPrefs({ sort: e.target.value })}>
            {BRANCH_SORTS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <label className="vx-check" htmlFor="vc-rel-only" title={TARGET_BRANCH_HELP}>
            <input type="checkbox" id="vc-rel-only" className="td-check" checked={prefs.relevantOnly} onChange={(e) => setPrefs({ relevantOnly: e.target.checked })} />
            Target branches only
          </label>
          <Segmented
            options={[
              { value: "cards", label: "Cards" },
              { value: "table", label: "Table" },
            ]}
            value={prefs.branchView}
            ariaLabel="Show branches as"
            onChange={(v) => setPrefs({ branchView: v as CollegeUiPrefs["branchView"] })}
          />
          <span className="vx-muted vx-small vc-count" aria-live="polite">
            {rows.length === total ? fmt.plural(total, "branch", "branches") : `Showing ${fmt.num(rows.length)} of ${fmt.num(total)}`}
          </span>
          <span className="vx-grow" />
          <WriteOnly>
            <Btn small icon="plus" onClick={() => void addBranch({ college_id: c.id })}>
              Add branch
            </Btn>
          </WriteOnly>
        </div>
      ) : null}
      <div className="vc-branch-list">{list}</div>
    </div>
  );
}

function BranchCard({ b, onOpen }: { b: BranchX; onOpen: (id: number) => void }) {
  const r = b.rollup;
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(b.id);
    }
  };
  return (
    <article
      className={["vc-bcard", b._gap && "is-gap", !b.is_relevant && "is-irrelevant"].filter(Boolean).join(" ")}
      tabIndex={0}
      role="button"
      aria-label={`Open branch ${b.name || b.code}`}
      onClick={() => onOpen(b.id)}
      onKeyDown={onKey}
    >
      <header className="vc-bcard-head">
        <div>
          <div className="vc-bcard-title">
            {b.code ? <span className="vx-code">{b.code}</span> : null} {b.name || ""}
          </div>
          <div className="vx-row">
            <Badge tone={b.is_relevant ? "brand" : "neutral"}>{CATEGORY_LABEL[b.category] || "Other"}</Badge>
            <OutreachStatus b={b} />
          </div>
        </div>
        <WriteOnly>
          <Btn small icon="edit" aria={`Edit ${b.code || "branch"}`} title="Edit branch" className="vx-iconbtn" onClick={() => void editBranch(b)} />
        </WriteOnly>
      </header>
      <BranchFigures b={b} />
      <dl className="vc-bcard-dl">
        <dt>{`Ambassadors (${b._activeAmbs.length})`}</dt>
        <dd>
          <AmbNames b={b} />
        </dd>
        <dt>Next follow-up</dt>
        <dd>{b._nextFu ? `${fmt.date(b._nextFu.due_date)} — ${b._nextFu.title || (b._nextFu.issue ? ISSUE_LABEL[b._nextFu.issue] : "") || ""}` : "—"}</dd>
      </dl>
      {r.target ? (
        <div className="vc-bcard-target">
          <Progress target={r.target} done={r.enrolled || 0} size="sm" />
        </div>
      ) : (
        <div className="vx-small vx-muted">{`${fmt.num(r.enrolled || 0)} confirmed · no branch target`}</div>
      )}
    </article>
  );
}

function BranchTable({ rows, onOpen }: { rows: BranchX[]; onOpen: (id: number) => void }) {
  return (
    <DataTable<BranchX>
      rows={rows}
      rowKey={(b) => b.id}
      caption="Branches of this college"
      onRowClick={(b) => onOpen(b.id)}
      columns={[
        {
          key: "code",
          label: "Branch",
          primary: true,
          sortValue: (b) => b.code || b.name,
          render: (b) => (
            <span>
              <strong>{b.code || ""}</strong> <span className="vx-small">{b.name || ""}</span>{" "}
              {b.is_relevant ? (
                <span title={TARGET_BRANCH_HELP}>
                  <Badge tone="brand">Target</Badge>
                </span>
              ) : null}
            </span>
          ),
        },
        { key: "intake_per_year", label: BRANCH_FIG.intake, align: "right", sortValue: (b) => b.intake_per_year ?? -1, render: (b) => <Vb value={b.intake_per_year} basis={b.intake_basis} /> },
        { key: "eligible_estimate", label: BRANCH_FIG.eligible, align: "right", sortValue: (b) => b.eligible_estimate ?? -1, render: (b) => <Vb value={b.eligible_estimate} basis={b.eligible_basis} /> },
        {
          key: "n_ambs",
          label: "Ambassadors",
          sortable: false,
          render: (b) => (
            <span>
              <strong>{fmt.num(b._activeAmbs.length)}</strong> <AmbNames b={b} />
            </span>
          ),
        },
        { key: "r_pct", label: "Progress", sortable: false, render: (b) => <ProgressCell target={b.rollup.target} done={b.rollup.enrolled} /> },
        { key: "status", label: "Outreach", sortable: false, render: (b) => <OutreachStatus b={b} /> },
      ]}
    />
  );
}
