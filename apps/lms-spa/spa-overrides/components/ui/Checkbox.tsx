import { useId, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";
import { choiceInputClass } from "./touch";

export interface CheckboxProps extends Omit<ComponentProps<"input">, "type"> {
  label: ReactNode;
  description?: ReactNode;
}

export function Checkbox({ label, description, className, id, ...props }: CheckboxProps) {
  const generated = useId();
  const inputId = id ?? generated;
  const descId = description ? `${inputId}-desc` : undefined;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <input
        id={inputId}
        type="checkbox"
        aria-describedby={descId}
        className={cn(
          "mt-0.5 shrink-0 cursor-pointer rounded-sm border-line-control accent-[var(--td-brand)] focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed [@media(pointer:coarse)]:mt-0",
          choiceInputClass,
        )}
        {...props}
      />
      <div className="text-sm">
        <label htmlFor={inputId} className="cursor-pointer font-medium text-fg">
          {label}
        </label>
        {description ? (
          <p id={descId} className="text-fg-muted">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}
