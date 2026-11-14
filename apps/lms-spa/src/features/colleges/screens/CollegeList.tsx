/**
 * /colleges/colleges — the colleges list (old dashboard.js renderCollegeList, route #/colleges).
 * Scoped by the global district selection; filters, sort and page live in the URL.
 */
import "@/features/colleges/styles/views/dashboard.css";
import { usePortalPage } from "../shell/page-context";
import { Button, PageHeader, WriteOnly } from "../ui";
import { useAddCollege } from "./college-list/AddCollege";
import { CollegeListView } from "./college-list/CollegeListView";

export function CollegeList() {
  usePortalPage({ title: "Colleges", crumbs: [{ label: "Colleges" }] });
  const [openAdd, addDialog] = useAddCollege();
  return (
    <div className="v-colleges">
      <CollegeListView>
        {({ exportButton, list }) => (
          <>
            <PageHeader
              title="Colleges"
              scope
              actions={
                <>
                  {exportButton}
                  <WriteOnly>
                    <Button icon="plus" tone="primary" onClick={() => openAdd()}>
                      Add college
                    </Button>
                  </WriteOnly>
                </>
              }
            />
            {list}
          </>
        )}
      </CollegeListView>
      {addDialog}
    </div>
  );
}
