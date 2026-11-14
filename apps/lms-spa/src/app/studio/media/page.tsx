import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MediaLibrary } from "@/features/studio/components/Media";

export const metadata: Metadata = { title: "Media" };

/** CMS-012: lesson media per course (MED-01..03). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Media" description="Open a course to upload lesson videos, attach PDFs or captions, and follow processing until they are ready." />
      <MediaLibrary />
    </div>
  );
}
