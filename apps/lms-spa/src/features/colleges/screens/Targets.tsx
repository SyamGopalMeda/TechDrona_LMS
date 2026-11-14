/**
 * Targets & performance (/colleges/targets) — port of js/views/targets.js `render`. Two sub-sections, chosen by
 * `?tab=places` (or a `?scope=type:id` deep link into the place tree): Performance and Targets by place. The
 * section tabs (Performance | Targets by place | Planner) are drawn by the shell.
 */
import "@/features/colleges/styles/views/targets.css";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { usePortalPage } from "../shell/page-context";
import { Button, PageHeader } from "../ui";
import { Performance } from "./targets/Performance";
import { Places, scrollToWizard } from "./targets/Places";

export function Targets() {
  const [q] = useQueryState();
  const tab = q.tab === "places" || (q.scope && q.tab !== "perf") ? "places" : "perf";
  usePortalPage({ title: "Targets & performance", crumbs: [{ label: "Targets & performance", to: portalPath.targets }] });
  return (
    <div className="v-tgp">
      <PageHeader
        title="Targets & performance"
        sub={
          tab === "perf"
            ? "Who is ahead and who is behind: targets against paid enrollments, by person, college or district."
            : "Set targets for places, split one number across its parts, and keep every level adding up."
        }
        actions={
          tab === "places" ? (
            <Button icon="target" tone="primary" onClick={scrollToWizard}>
              Split a target
            </Button>
          ) : null
        }
      />
      {tab === "places" ? (
        <div className="tgp-body v-tgpl">
          <Places scope={q.scope} />
        </div>
      ) : (
        <div className="tgp-body">
          <Performance />
        </div>
      )}
    </div>
  );
}
