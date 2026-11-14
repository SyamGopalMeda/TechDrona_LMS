import Link from "next/link";
import { cn } from "@/lib/ui/cn";

export const SETTINGS_TABS = [
  { href: "/app/settings/profile", label: "Profile", screen: "STU-020" },
  { href: "/app/settings/security", label: "Security", screen: "STU-021" },
  { href: "/app/settings/devices", label: "Devices & sessions", screen: "STU-022" },
  { href: "/app/settings/privacy", label: "Privacy & consent", screen: "STU-023" },
] as const;

/** Sub-navigation shared by the student settings pages (links, aria-current on the active one). */
export function SettingsNav({ current }: { current: (typeof SETTINGS_TABS)[number]["href"] }) {
  return (
    // Same look as the kit Tabs (Jakarta semibold, navy active underline). On phones the row scrolls
    // sideways; the right-edge fade shows there is more to scroll to.
    <nav
      aria-label="Settings"
      className="mb-6 overflow-x-auto border-b border-line [mask-image:linear-gradient(to_right,black_85%,transparent)] sm:[mask-image:none]"
    >
      <ul className="flex gap-1 pr-6 sm:pr-0">
        {SETTINGS_TABS.map((t) => {
          const active = t.href === current;
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex min-h-touch items-center whitespace-nowrap border-b-2 px-3 font-display text-sm font-semibold transition-colors focus-visible:shadow-focus focus-visible:outline-none",
                  active ? "border-brand text-brand" : "border-transparent text-fg-secondary hover:border-line-strong hover:text-fg",
                )}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
