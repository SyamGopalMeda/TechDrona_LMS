/**
 * /colleges/d/:district/:city — town page (old geo.js renderCity, route #/d/:district/:city): summary of the town
 * (target, KPIs, map) + the shared colleges list fixed to the town (any operating status by default).
 */
import "@/features/colleges/styles/views/dashboard.css";
import { Link, useParams } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { portalPath } from "../lib/routes";
import type { PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Button, EmptyState, ErrorCard, PageHeader, Section, Skeleton, WriteOnly } from "../ui";
import { useAddCollege } from "./college-list/AddCollege";
import { CollegeListView, cityShort } from "./college-list/CollegeListView";
import { OutOfScopeNote, PlaceMap, SummaryKpis, TargetBlock, cityIdFrom, isNotFound, lbRows, type PlaceSummary } from "./geo/parts";

export function Town() {
  const params = useParams();
  const did = params.district ?? "";
  const cityId = cityIdFrom(did, params.city);
  const scope = `city:${cityId}`;
  const metaQ = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const sumQ = usePortalQuery<PlaceSummary>("summary", { query: { scope } });
  const collegeLbQ = usePortalQuery<unknown>("leaderboard", { query: { level: "college", scope, limit: 500 } });
  const [openAdd, addDialog] = useAddCollege();

  const meta = metaQ.data;
  const S = sumQ.data;
  const dist = (meta?.districts ?? []).find((d) => d.id === did);
  const city = (meta?.cities ?? []).find((c) => c.id === cityId);
  const cityName = S?.label || city?.name || cityShort(did, cityId);
  const distName = dist?.name || did;
  const base = portalPath.city(did, cityId);
  usePortalPage({
    title: cityName,
    crumbs: [{ label: "Colleges", to: portalPath.colleges }, { label: distName, to: portalPath.district(did) }, { label: cityName, to: base }],
  });

  if (!S) {
    if (sumQ.loading)
      return (
        <div className="v-geo">
          <Skeleton lines={5} />
        </div>
      );
    return (
      <div className="v-geo">
        <Link className="vd-link" to={portalPath.district(did)}>{`← Back to ${dist?.name || "district"}`}</Link>
        {isNotFound(sumQ.error) ? (
          <EmptyState icon="warn" title="City not found" text="This city is not in the master list. Go back to the district to pick another one." />
        ) : (
          <ErrorCard title="Could not load this city" error={sumQ.error} retry={() => void sumQ.reload()} />
        )}
      </div>
    );
  }

  return (
    <div className="v-geo">
      <PageHeader
        eyebrow={
          <span>
            {"City / town · "}
            <Link to={portalPath.district(did)}>{distName}</Link>
          </span>
        }
        title={cityName}
        sub={`${fmt.plural(S.colleges ?? 0, "college")} · ${fmt.num(S.targeted_colleges ?? 0)} targeted`}
        actions={
          <WriteOnly>
            <Button icon="plus" onClick={() => openAdd({ district_id: did, city_id: cityId })}>
              Add college
            </Button>
          </WriteOnly>
        }
      />
      <OutOfScopeNote id={did} name={distName} />
      <div className="vg-summary">
        <div className="vg-sumgrid">
          <TargetBlock S={S} what="city" rows={collegeLbQ.data ? lbRows(collegeLbQ.data) : null} />
          <SummaryKpis S={S} base={base} />
        </div>
      </div>
      <PlaceMap districtId={did} title={cityName} focus={{ kind: "city", district: did, id: cityId }} meta={meta} />
      <CollegeListView fixed={{ city: cityId }} defaultOp="all">
        {({ exportButton, list }) => (
          <Section title={`Colleges in ${cityName}`} actions={exportButton}>
            {list}
          </Section>
        )}
      </CollegeListView>
      {addDialog}
    </div>
  );
}
