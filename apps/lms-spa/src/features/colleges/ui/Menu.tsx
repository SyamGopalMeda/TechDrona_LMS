/**
 * Overflow / action menu (components.js `menu`): a button that opens a popover list (role=menu), keyboard
 * navigable, closed by Esc, outside click, scroll or resize. `writeOnly` items are hidden for viewers.
 *
 *   <Menu ariaLabel="Row actions" items={[{ label: "Edit", icon: "edit", onClick: edit, writeOnly: true }, …]} />
 *   <Menu label="Modules" icon={null} tone="secondary" items={…} />
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button, type ButtonTone } from "./Button";
import { cx, useOverlayRoot, usePortalUi } from "./context";
import { Icon, type IconName } from "./Icon";

export interface MenuItem {
  label: ReactNode;
  icon?: IconName | null;
  tone?: "danger";
  onClick?: () => void;
  /** a link instead of an action (full page load when `reload`) */
  href?: string;
  reload?: boolean;
  hidden?: boolean;
  writeOnly?: boolean;
  /** marks the current item (aria-current) */
  current?: boolean;
}

export function Menu({
  label,
  icon = "more",
  items,
  ariaLabel = "More actions",
  tone = "ghost",
  size = "sm",
  className,
  onNavigate,
}: {
  label?: ReactNode;
  icon?: IconName | null;
  items: (MenuItem | null | false | undefined)[];
  ariaLabel?: string;
  tone?: ButtonTone;
  size?: "sm" | "md";
  className?: string;
  /** called for `href` items without `reload` (client navigation); default: location.assign */
  onNavigate?: (href: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const root = useOverlayRoot();
  const { canWrite } = usePortalUi();
  const vis = items.filter((it): it is MenuItem => !!it && !it.hidden && !(it.writeOnly && !canWrite));

  useLayoutEffect(() => {
    if (!open || !btn.current || !pop.current) return;
    const r = btn.current.getBoundingClientRect();
    const pw = pop.current.offsetWidth;
    const ph = pop.current.offsetHeight;
    const left = Math.max(8, Math.min(r.right - pw, window.innerWidth - pw - 8));
    let top = r.bottom + 4;
    if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 4);
    setPos({ left, top });
    pop.current.querySelector<HTMLElement>(".td-menu__item")?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      const entries = [...(pop.current?.querySelectorAll<HTMLElement>(".td-menu__item") ?? [])];
      const i = entries.indexOf(document.activeElement as HTMLElement);
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close();
        btn.current?.focus();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        entries[(i + 1) % entries.length]?.focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        entries[(i - 1 + entries.length) % entries.length]?.focus();
      } else if (e.key === "Tab") close();
    };
    const onOut = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!pop.current?.contains(t) && !btn.current?.contains(t)) close();
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onOut, true);
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onOut, true);
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [open]);

  const choose = (it: MenuItem) => {
    setOpen(false);
    btn.current?.focus();
    if (it.href) {
      if (!it.reload && onNavigate) onNavigate(it.href);
      else window.location.assign(it.href);
    }
    it.onClick?.();
  };

  return (
    <>
      <Button
        ref={btn}
        tone={tone}
        size={size}
        icon={icon ?? undefined}
        ariaLabel={ariaLabel}
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
          setPos(null);
        }}
      >
        {label}
      </Button>
      {open && root
        ? createPortal(
            <div ref={pop} className="td-menu" role="menu" style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden", left: 0, top: 0 }}>
              {vis.length ? (
                vis.map((it, i) => (
                  <button
                    key={i}
                    type="button"
                    role="menuitem"
                    tabIndex={-1}
                    aria-current={it.current ? "true" : undefined}
                    className={cx("td-menu__item", it.tone === "danger" && "is-danger")}
                    onClick={(e) => {
                      e.stopPropagation();
                      choose(it);
                    }}
                  >
                    {it.icon ? <Icon name={it.icon} size={16} /> : <span className="td-menu__sp" />}
                    <span>{it.label}</span>
                  </button>
                ))
              ) : (
                <div className="td-menu__none td-muted">No actions available</div>
              )}
            </div>,
            root,
          )
        : null}
    </>
  );
}
