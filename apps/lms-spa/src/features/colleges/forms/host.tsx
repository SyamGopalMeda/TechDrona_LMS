/**
 * Imperative dialogs, like the old forms.js (`await forms.logCall({ college_id })`), on top of React components.
 *
 *   const saved = await openDialog<Call>((done) => <LogCallDialog collegeId="c9" onDone={done} />);
 *
 * The dialogs render in <FormsHost/>. Mount it once inside the portal (any screen that opens a dialog can render
 * one: several hosts are fine, only the first mounted one draws, the next takes over when it unmounts).
 * Each dialog component is also usable declaratively (`<LogCallDialog open … onDone />`).
 */
import { Fragment, useEffect, useId, useSyncExternalStore, type ReactNode } from "react";

interface Entry {
  id: number;
  render: (done: (r: unknown) => void) => ReactNode;
  resolve: (r: unknown) => void;
}

let seq = 0;
let entries: Entry[] = [];
let hosts: string[] = [];
let version = 0;
const listeners = new Set<() => void>();
const notify = () => {
  version += 1;
  listeners.forEach((l) => l());
};
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** Open a dialog; resolves with what the dialog passes to `done` (null = cancelled). */
export function openDialog<R>(render: (done: (result: R | null) => void) => ReactNode): Promise<R | null> {
  return new Promise<R | null>((resolve) => {
    const id = ++seq;
    const entry: Entry = {
      id,
      render: render as Entry["render"],
      resolve: (r) => {
        if (!entries.some((e) => e.id === id)) return;
        entries = entries.filter((e) => e.id !== id);
        notify();
        resolve((r ?? null) as R | null);
      },
    };
    entries = [...entries, entry];
    notify();
    if (!hosts.length && typeof console !== "undefined") console.warn("openDialog: no <FormsHost/> is mounted; the dialog shows once one mounts.");
  });
}

/** Close every open dialog (as cancelled). */
export function closeAllDialogs(): void {
  for (const e of [...entries]) e.resolve(null);
}

/** Renders the dialogs opened with openDialog(). Safe to mount more than once. */
export function FormsHost() {
  const me = useId();
  useSyncExternalStore(subscribe, () => version, () => 0);
  useEffect(() => {
    hosts = [...hosts, me];
    notify();
    return () => {
      hosts = hosts.filter((h) => h !== me);
      notify();
    };
  }, [me]);
  if (hosts[0] !== me) return null;
  return (
    <>
      {entries.map((e) => (
        <Fragment key={e.id}>{e.render(e.resolve)}</Fragment>
      ))}
    </>
  );
}

/** Tests only. */
export function resetDialogsForTests(): void {
  entries = [];
  notify();
}
