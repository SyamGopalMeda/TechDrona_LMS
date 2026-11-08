import { redirect } from "next/navigation";

/** /app/courses has no screen of its own: My courses is STU-004 at /app/learning. */
export default function Page() {
  redirect("/app/learning");
}
