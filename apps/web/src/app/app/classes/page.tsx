import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MyClasses } from "@/features/batches/components/MyClasses";

export const metadata: Metadata = { title: "My classes" };

/** STU-040 My classes: live classes of the learner's batches (join link, recordings, attendance). */
export default function Page() {
  return (
    <div>
      <PageHeader eyebrow="Live classes" title="My classes" description="Your next classes with the join link, recordings of past classes and your attendance." />
      <MyClasses />
    </div>
  );
}
