/**
 * /colleges/d/:district — district page (old geo.js renderDistrict, route #/d/:district): a compact summary of the
 * place (target, KPIs, map, cities & towns, alerts) + the shared colleges list fixed to the district.
 */
import "@/features/colleges/styles/views/dashboard.css";
import { useParams } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { portalPath } from "../lib/routes";
import { targetGroupOf } from "../lib/scope";
import type { AttentionItem, PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Button, EmptyState, ErrorCard, LinkButton, PageHeader, Section, Skeleton, WriteOnly } from "../ui";
import { useAddCollege } from "./college-list/AddCollege";
import { CollegeListView } from "./college-list/CollegeListView";
import { CityChips, DistrictPicker, OutOfScopeNote, PlaceMap, SummaryKpis, TargetBlock, isNotFound, lbRows, type PlaceSummary } from "./geo/parts";
import { AttentionList } from "./shared/dashboard";

export function District() {
  const id = useParams().district ?? "";
  const scope = `district:${id}`;
  const metaQ = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const sumQ = usePortalQuery<PlaceSummary>("summary", { query: { scope } });
  const attnQ = usePortalQuery<AttentionItem[]>("attention", { query: { scope } });
  const cityLbQ = usePortalQuery<unknown>("leaderboard", { query: { level: "city", scope, limit: 200 } });
  const collegeLbQ = usePortalQuery<unknown>("leaderboard", { query: { level: "college", scope, limit: 500 } });
  const [openAdd, addDialog] = useAddCollege();

  const meta = metaQ.data;
  const S = sumQ.data;
  const dist = (meta?.districts ?? []).find((d) => d.id === id);
  const dName = S?.label || dist?.name || id;
  usePortalPage({ title: dName, crumbs: [{ label: "Colleges", to: portalPath.colleges }, { label: dName, to: portalPath.district(id) }] });

  if (!S) {
    if (sumQ.loading)
      return (
        <div className="v-geo">
          <Skeleton lines={5} />
        </div>
      );
    return (
      <div className="v-geo">
        <DistrictPicker districts={meta?.districts ?? []} current={id} />
        {isNotFound(sumQ.error) ? (
          <EmptyState
            icon="warn"
            title="District not found"
            text="Pick a district from the list above, or open the colleges list."
            actions={[
              <LinkButton key="all" to={portalPath.colleges} tone="primary">
                All colleges
              </LinkButton>,
            ]}
          />
        ) : (
          <ErrorCard title="Could not load this district" error={sumQ.error} retry={() => void sumQ.reload()} />
        )}
      </div>
    );
  }

  const base = portalPath.district(id);
  const group = targetGroupOf(id);
  const sub =
    [fmt.plural(S.colleges ?? 0, "college"), `${fmt.num(S.targeted_colleges ?? 0)} targeted`, fmt.plural(S.cities ?? 0, "city or town", "cities and towns")].join(" · ") +
    (dist?.old_district && dist.old_district !== dist.name ? ` · formerly part of ${dist.old_district}` : "");
  const attn = (attnQ.data ?? []).filter((r) => r.type !== "group");
  return (
    <div className="v-geo">
      <PageHeader
        eyebrow={group ? `Target district · ${group}` : "District"}
        title={dName}
        sub={sub}
        actions={
          <>
            <DistrictPicker districts={meta?.districts ?? []} current={id} />
            <WriteOnly>
              <Button icon="plus" onClick={() => openAdd({ district_id: id })}>
                Add college
              </Button>
            </WriteOnly>
          </>
        }
      />
      <OutOfScopeNote id={id} name={dName} />
      <div className="vg-summary">
        <div className="vg-sumgrid">
          <TargetBlock S={S} what="district" rows={collegeLbQ.data ? lbRows(collegeLbQ.data) : null} />
          <SummaryKpis S={S} base={base} />
        </div>
      </div>
      <PlaceMap districtId={id} title={dName} focus={{ kind: "district", id }} meta={meta} />
      <div className="vg-extras">
        <CityChips did={id} cities={meta?.cities ?? []} lb={cityLbQ.data ? lbRows(cityLbQ.data) : null} />
        {attn.length ? (
          <details className="vg-attn">
            <summary>{`Alerts in ${dName} (${fmt.num(attn.length)})`}</summary>
            <AttentionList rows={attn} limit={6} />
          </details>
        ) : null}
      </div>
      <CollegeListView fixed={{ district: id }}>
        {({ exportButton, list }) => (
          <Section title={`Colleges in ${dName}`} actions={exportButton}>
            {list}
          </Section>
        )}
      </CollegeListView>
      {addDialog}
    </div>
  );
}
