import { redirect } from "next/navigation";

/**
 * STU-011 skill analytics is the Progress page (mastery by topic, time spent, method disclosure);
 * this older route forwards there so both nav entries land on one screen.
 */
export default function Page() {
  redirect("/app/progress");
}
