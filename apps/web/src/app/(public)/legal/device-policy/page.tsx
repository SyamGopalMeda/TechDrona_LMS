import type { Metadata } from "next";
import { hasSessionCookie } from "@/lib/api/server";
import { ContentDocView } from "@/features/public/components/ContentDoc";
import { MyDeviceLimits } from "@/features/public/components/MyDeviceLimits";
import { DEVICE_POLICY } from "@/features/public/content/legal";
import { serverLoad } from "@/features/catalog/lib/server";
import type { DevicePolicyDto } from "@/features/public/lib/types";

export const metadata: Metadata = { title: DEVICE_POLICY.title, description: DEVICE_POLICY.summary };

/** PUB-018 device policy: published defaults, plus the signed-in learner's own limits (ME device-policy). */
export default async function Page() {
  const mine = (await hasSessionCookie()) ? await serverLoad<DevicePolicyDto>("me/device-policy") : null;
  return (
    <ContentDocView doc={DEVICE_POLICY} kind="policy">
      {mine?.ok ? <MyDeviceLimits policy={mine.data} /> : null}
    </ContentDocView>
  );
}
