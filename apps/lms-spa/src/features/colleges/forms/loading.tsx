/** Loading / error modal shown while a dialog fetches what it needs (shared by the forms in this folder). */
import type { ReactNode } from "react";
import { ErrorCard, Skeleton } from "../ui/Feedback";
import { Modal } from "../ui/Overlay";

export function LoadingModal({ open = true, title, error, loading, retry, onClose, what = "the college" }: { open?: boolean; title: ReactNode; error: unknown; loading: boolean; retry: () => void; onClose: () => void; what?: string }) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      {loading || !error ? <Skeleton lines={4} card={false} /> : <ErrorCard title={`Could not load ${what}`} error={error} retry={retry} />}
    </Modal>
  );
}

/** Courses / settings for dialogs (cached 5 min; the shell already loaded it). */
export const META_TTL = 300_000;
