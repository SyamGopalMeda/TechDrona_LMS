/** Team tab: college lead → ambassador leads → ambassadors, vacant slots, unassigned people, inactive history. */
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { isPortalApiError, portalApi } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { ContactActions, EmptyState, Icon, Menu, ProgressBar, Provenance, Section, StatusChip, WriteOnly, cx as cls, toast, type MenuItem } from "../../ui";
import { ROLE_LABEL } from "../../forms/labels";
import { assignToLead, deactivatePerson, editPerson, movePerson, reactivatePerson, replaceLead, validLeads } from "../../forms/People";
import { targetDialog } from "../targets/TargetDialog";
import { PerfChip } from "../shared/dashboard";
import { addPerson, type CollegeCtx } from "./ctx";
import { isActive, perfRows, personPerf, type PerfRes, type PerfRow, type PersonX } from "./model";
import { Btn, branchLabel } from "./parts";

/** Per-person own / team numbers (v4 /performance); the tree renders without them. */
function usePersonPerf(collegeId: string, period = "programme"): Map<number, PerfRow> | null {
  const q = usePortalQuery<PerfRes>("performance", { query: { level: "person", college_id: collegeId, period, include_inactive: 1 } });
  return useMemo(() => (q.data ? new Map(perfRows(q.data).map((x) => [Number(x.id), x])) : null), [q.data]);
}

export function TeamTab({ c: cx }: { c: CollegeCtx }) {
  const { d, s, research } = cx;
  const c = d.college;
  const perfById = usePersonPerf(c.id);
  const active = s.people.filter(isActive);
  const lead = s.lead;
  const AL = active.filter((p) => p.role === "ambassador_lead" && !s.unassigned.has(Number(p.id)));
  const AM = active.filter((p) => p.role === "ambassador" && !s.unassigned.has(Number(p.id)));
  const UN = active.filter((p) => s.unassigned.has(Number(p.id)));
  const inactive = s.people.filter((p) => !isActive(p));
  const bmap = new Map(s.branches.map((b) => [Number(b.id), b]));
  const suggested = research?.ambassadors_research ?? null;

  const card = (p: PersonX, compact = false) => <PersonCard key={p.id} p={p} compact={compact} cx={cx} perfById={perfById} bmap={bmap} />;
  const under = (pid: number) => AM.filter((a) => Number(a.reports_to) === Number(pid));
  const node = (p: PersonX, kids?: ReactNode[]) => (
    <li className="vc-node" key={p.id}>
      {card(p)}
      {kids && kids.length ? <ul className="vc-tree-kids">{kids}</ul> : null}
    </li>
  );
  const slots = s.branches
    .filter((b) => b._gap)
    .map((b) => (
      <li className="vc-node" key={`gap-${b.id}`}>
        <Vacant
          title={`${branchLabel(b)} — no ambassador`}
          text={`${b.name || "This branch"} counts toward the target`}
          action={
            <Btn small onClick={() => addPerson(cx, "ambassador", { branch_ids: [b.id] })}>
              Recruit
            </Btn>
          }
        />
      </li>
    ));
  const alNodes = (list: PersonX[]) => list.map((a) => node(a, under(a.id).map((x) => node(x))));

  const n = (k: number, w: string) => (
    <span key={w}>
      <strong>{fmt.num(k)}</strong>
      {` ${fmt.word(k, w)}`}
    </span>
  );

  return (
    <div className="vc-tab vc-team">
      <div className="vc-teambody">
        <div className="vc-team-bar">
          <div className="vc-team-sum">
            {n(lead ? 1 : 0, "college lead")}
            {n(active.filter((p) => p.role === "ambassador_lead").length, "ambassador lead")}
            {n(active.filter((p) => p.role === "ambassador").length, "ambassador")}
            {UN.length ? (
              <span className="is-warn">
                <strong>{fmt.num(UN.length)}</strong> unassigned
              </span>
            ) : null}
            {suggested != null ? (
              <span className="vx-muted">
                {`research suggests ${fmt.num(suggested)} ambassadors `}
                <Provenance basis="estimated" />
              </span>
            ) : null}
          </div>
          <WriteOnly>
            <div className="vx-actions">
              <Btn small icon="ambassador" tone={lead ? "primary" : "secondary"} onClick={() => addPerson(cx, "ambassador")}>
                Add ambassador
              </Btn>
              <Btn small icon="lead" onClick={() => addPerson(cx, "ambassador_lead")}>
                Add ambassador lead
              </Btn>
              {lead ? (
                <Btn small onClick={() => void replaceLead(lead.id)}>
                  Replace lead
                </Btn>
              ) : (
                <Btn small tone="primary" icon="lead" onClick={() => addPerson(cx, "college_lead")}>
                  Appoint college lead
                </Btn>
              )}
            </div>
          </WriteOnly>
        </div>

        {!active.length && !inactive.length ? (
          <EmptyState
            title="No team yet"
            icon="people"
            text="Start with one college lead who is accountable for the whole college. Then add one student ambassador for each target branch (computer science, CS-related or electronics); they report to the lead."
            actions={[
              <WriteOnly key="a">
                <Btn tone="primary" icon="lead" onClick={() => addPerson(cx, "college_lead")}>
                  Appoint college lead
                </Btn>
              </WriteOnly>,
            ]}
          />
        ) : (
          <>
            <ul className="vc-tree" aria-label="Team structure">
              {lead ? (
                node(lead, [...alNodes(AL.filter((a) => Number(a.reports_to) === Number(lead.id))), ...under(lead.id).map((x) => node(x)), ...slots])
              ) : (
                <li className="vc-node">
                  <Vacant
                    title="College lead — vacant"
                    text="Appoint one student accountable for this college"
                    action={
                      <Btn small tone="primary" onClick={() => addPerson(cx, "college_lead")}>
                        Appoint
                      </Btn>
                    }
                  />
                  <ul className="vc-tree-kids">{[...alNodes(AL), ...slots]}</ul>
                </li>
              )}
            </ul>
            {UN.length ? <Unassigned cx={cx} un={UN} card={(p) => card(p, true)} /> : null}
            {inactive.length ? (
              <details className="vc-inactive">
                <summary>{`Inactive (${fmt.num(inactive.length)}) — history kept`}</summary>
                <div className="vc-inactive-list">{inactive.map((p) => card(p, true))}</div>
              </details>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function Vacant({ title, text, action }: { title: string; text: string; action?: ReactNode }) {
  return (
    <div className="vc-pcard is-vacant">
      <div className="vc-pcard-top">
        <span className="vc-pcard-ic">
          <Icon name="plus" size={16} />
        </span>
        <div className="vc-pcard-id">
          <strong>{title}</strong>
          <span className="vx-small vx-muted">{text}</span>
        </div>
        {action ? <WriteOnly>{action}</WriteOnly> : null}
      </div>
    </div>
  );
}

function PersonCard({ p, compact, cx, perfById, bmap }: { p: PersonX; compact: boolean; cx: CollegeCtx; perfById: Map<number, PerfRow> | null; bmap: Map<number, { code?: string | null; name?: string | null; id: number }> }) {
  const pf = personPerf(p, perfById);
  const bs = p._branches.map((i) => bmap.get(i)).filter((b): b is NonNullable<typeof b> => !!b);
  const acts: MenuItem[] = [
    { label: "Edit details", icon: "edit", writeOnly: true, onClick: () => void editPerson(p.id) },
    { label: "Set target", icon: "target", writeOnly: true, onClick: () => void targetDialog({ scope_type: "person", scope_id: String(p.id), label: p.full_name }) },
    { label: "Replace as college lead", icon: "lead", writeOnly: true, hidden: p.role !== "college_lead", onClick: () => void replaceLead(p.id) },
    { label: "Move to another college", icon: "college", writeOnly: true, onClick: () => void movePerson(p.id) },
    isActive(p)
      ? { label: "Deactivate…", icon: "close", tone: "danger", writeOnly: true, onClick: () => void deactivatePerson(p.id) }
      : { label: "Reactivate", icon: "refresh", writeOnly: true, onClick: () => void reactivatePerson(p) },
  ];
  const lname = p.reports_to_name || p.lead?.name || `#${p.reports_to}`;
  const ISSUE: Record<string, string> = {
    no_lead: "No lead assigned",
    lead_missing: "Their lead no longer exists",
    lead_inactive: `Reports to ${lname}, who is inactive`,
    lead_other_college: `Reports to ${lname}, who is at another college`,
    lead_wrong_role: `Reports to ${lname}, who is not a lead`,
  };
  const issue = cx.s.unassigned.has(Number(p.id))
    ? ((p.assignment_issue && ISSUE[p.assignment_issue]) ??
      (p.reports_to ? `Reports to ${p.reports_to_name || `#${p.reports_to}`}, who is not an active lead of this college` : "No lead assigned"))
    : null;
  return (
    <div className={cls("vc-pcard", `is-${p.role}`, !isActive(p) && "is-inactive", issue && "is-unassigned", compact && "is-compact")}>
      <div className="vc-pcard-top">
        <span className="vc-pcard-ic">
          <Icon name={p.role === "ambassador" ? "ambassador" : "lead"} size={16} />
        </span>
        <div className="vc-pcard-id">
          <Link to={portalPath.person(p.id)} className="vc-pcard-name">
            {p.full_name || `Person #${p.id}`}
          </Link>
          <span className="vx-small vx-muted">
            {ROLE_LABEL[p.role] || p.role}
            {p.designation ? ` · ${p.designation}` : ""}
            {bs.length ? ` · ${bs.map(branchLabel).join(", ")}` : ""}
          </span>
        </div>
        {p.status !== "active" ? <StatusChip status={p.status} /> : null}
        <Menu ariaLabel={`Actions for ${p.full_name}`} items={acts} />
      </div>
      {issue ? (
        <div className="vc-pcard-issue vx-small">
          <Icon name="warn" size={14} />
          {issue}
        </div>
      ) : null}
      <div className="vc-pcard-bottom">
        <ContactActions phone={p.phone} email={p.email} compact name={p.full_name} />
        <div className="vc-pcard-perf">
          {pf.target != null && pf.target > 0 ? (
            <ProgressBar actual={pf.actual ?? 0} target={pf.target} min={pf.min} max={pf.max} size="sm" status={pf.status} pct={pf.pct} />
          ) : (
            <span className="vx-small vx-muted">{pf.target === 0 ? `Target 0 · ${fmt.num(pf.actual ?? 0)} confirmed` : `${fmt.num(pf.actual ?? 0)} confirmed · no target`}</span>
          )}
          {pf.status ? <PerfChip status={pf.status} /> : null}
          {pf.team && pf.team.size ? (
            <span className="vx-small vx-muted">{`Team (${fmt.num(pf.team.size)}): ${fmt.num(pf.team.actual ?? 0)}${pf.team.target ? ` / ${fmt.num(pf.team.target)}` : ""} confirmed`}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Unassigned({ cx, un, card }: { cx: CollegeCtx; un: PersonX[]; card: (p: PersonX) => ReactNode }) {
  const { s } = cx;
  const leads = validLeads(s.people, "ambassador").filter((p) => !s.unassigned.has(Number(p.id)));
  const [leadId, setLeadId] = useState<string>(s.lead ? String(s.lead.id) : "");
  const [picks, setPicks] = useState<Set<number>>(() => new Set(un.map((p) => Number(p.id))));
  const [busy, setBusy] = useState(false);

  const assign = async () => {
    if (!leadId) return toast("Choose the lead first", "warn");
    const ids = [...picks];
    if (!ids.length) return toast("Tick at least one person", "warn");
    // ambassador leads can only report to the college lead
    const leadP = s.byId.get(Number(leadId));
    if (ids.some((i) => s.byId.get(i)?.role === "ambassador_lead") && leadP?.role !== "college_lead") return toast("Ambassador leads can only report to the college lead", "bad");
    setBusy(true);
    try {
      let okN = 0;
      let fail: { id: number | string; message: string }[] = [];
      try {
        const r = await portalApi.post<{ updated?: unknown[]; unchanged?: unknown[] }>("people/bulk-assign", { person_ids: ids, reports_to: Number(leadId) });
        okN = (r?.updated ?? []).length + (r?.unchanged ?? []).length || ids.length;
      } catch (e) {
        if (!(isPortalApiError(e) && (e.status === 404 || e.status === 405))) throw e;
        const r = await assignToLead(ids, Number(leadId));
        okN = r.ok.length;
        fail = r.failed;
      }
      toast(
        fail.length ? `${okN} assigned, ${fail.length} failed: ${fail[0]!.message}` : `${fmt.plural(okN, "person", "people")} assigned to ${leadP?.full_name || "the lead"}`,
        fail.length ? "warn" : "good",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not assign", "bad");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title={`Unassigned (${fmt.num(un.length)})`}
      sub="Active people without a valid lead in this college (no lead, an inactive lead, or a lead elsewhere)."
      actions={
        <WriteOnly>
          <div className="vx-actions">
            <select className="td-input td-select td-input--sm" aria-label="Lead to assign to" value={leadId} onChange={(e) => setLeadId(e.target.value)}>
              <option value="">{leads.length ? "Choose a lead…" : "No active lead in this college"}</option>
              {leads.map((l) => (
                <option key={l.id} value={String(l.id)}>{`${l.full_name} (${ROLE_LABEL[l.role] ?? l.role})`}</option>
              ))}
            </select>
            <Btn small tone="primary" onClick={() => void (busy ? undefined : assign())}>
              Assign ticked
            </Btn>
          </div>
        </WriteOnly>
      }
    >
      <ul className="vc-unlist">
        {un.map((p) => (
          <li key={p.id}>
            <WriteOnly>
              <label className="td-checkhit vc-unpick">
                <input
                  type="checkbox"
                  className="td-check"
                  checked={picks.has(Number(p.id))}
                  aria-label={`Assign ${p.full_name}`}
                  onChange={(e) =>
                    setPicks((old) => {
                      const next = new Set(old);
                      if (e.target.checked) next.add(Number(p.id));
                      else next.delete(Number(p.id));
                      return next;
                    })
                  }
                />
              </label>
            </WriteOnly>
            {card(p)}
          </li>
        ))}
      </ul>
    </Section>
  );
}

