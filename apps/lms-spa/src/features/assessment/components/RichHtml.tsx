import { cn } from "@/lib/ui/cn";

/**
 * Renders question/explanation HTML delivered by the api (`stem_html`, `explanation_html`,
 * option `html`). Content is authored in the studio and sanitised server-side on publish
 * (api contract assumption); the page CSP (nonce + strict-dynamic, no inline handlers)
 * is the second line of defence.
 */
export function RichHtml({ html, className, as: Tag = "div" }: { html: string | null | undefined; className?: string; as?: "div" | "span" }) {
  return <Tag className={cn("td-rich-html break-words [&_img]:max-w-full [&_pre]:overflow-x-auto [&_code]:font-mono", className)} dangerouslySetInnerHTML={{ __html: html ?? "" }} />;
}
