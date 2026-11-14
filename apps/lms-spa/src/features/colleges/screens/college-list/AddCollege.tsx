/**
 * "Add college" (old dashboard.js openCollegeForm(ctx, null, defaults)): opens the shared college create dialog and
 * opens the new college's page once it is saved (old createCollege navigated there).
 */
import { useCallback, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { portalPath } from "../../lib/routes";
import { CollegeFormDialog } from "../college/CollegeForm";

export interface AddCollegeDefaults {
  district_id?: string;
  city_id?: string;
}

export function useAddCollege(): [open: (defaults?: AddCollegeDefaults) => void, dialog: ReactNode] {
  const navigate = useNavigate();
  const [state, setState] = useState<{ open: boolean; defaults?: AddCollegeDefaults }>({ open: false });
  const open = useCallback((defaults?: AddCollegeDefaults) => setState({ open: true, defaults }), []);
  const dialog = state.open ? (
    <CollegeFormDialog
      open
      collegeId={null}
      defaults={state.defaults}
      onDone={(saved) => {
        setState({ open: false });
        if (saved?.id) void navigate(portalPath.college(saved.id));
      }}
    />
  ) : null;
  return [open, dialog];
}
