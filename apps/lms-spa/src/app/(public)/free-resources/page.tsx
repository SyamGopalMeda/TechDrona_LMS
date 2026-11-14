import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { hasSessionCookie } from "@/lib/api/server";
import { CourseGrid, ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { serverLoad } from "@/features/catalog/lib/server";
import type { CourseCardDto } from "@/features/catalog/lib/types";
import { FreeResourceList } from "@/features/public/components/FreeResources";
import type { FreeResourceDto } from "@/features/public/lib/types";

export const metadata: Metadata = { title: "Free resources", description: "Free PDFs, cheat sheets and free courses for placement preparation." };

interface FreeResourcesResponse {
  data: { resources: FreeResourceDto[]; free_courses: CourseCardDto[] };
}

/** PUB-009 free resources (CAT-06). */
async function Page__server() {
  const [result, signedIn] = await Promise.all([serverLoad<FreeResourcesResponse>("catalog/free-resources?limit=50"), hasSessionCookie()]);
  return (
    <div className="space-y-8">
      <PageHeader title="Free resources" description="Free PDFs, cheat sheets and free courses." />
      {!result.ok ? (
        <ServerErrorState result={result} retryHref="/free-resources" />
      ) : (
        <>
          <section aria-labelledby="res-h" className="space-y-3">
            <h2 id="res-h" className="font-display text-xl font-semibold text-fg">
              Downloads
            </h2>
            <FreeResourceList resources={result.data.data.resources} signedIn={signedIn} />
          </section>
          {result.data.data.free_courses.length ? (
            <section aria-labelledby="fc-h" className="space-y-3">
              <h2 id="fc-h" className="font-display text-xl font-semibold text-fg">
                Free courses
              </h2>
              <CourseGrid courses={result.data.data.free_courses} headingLevel={3} />
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/(public)/free-resources/page.tsx#Page");
