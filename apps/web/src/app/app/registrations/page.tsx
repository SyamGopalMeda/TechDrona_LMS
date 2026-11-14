import type { Metadata } from "next";
import { MyRegistrations } from "@/features/registration/components/MyRegistrations";

export const metadata: Metadata = { title: "My registrations" };

/** The student's course registrations and payment verification status. */
export default function Page() {
  return <MyRegistrations />;
}
