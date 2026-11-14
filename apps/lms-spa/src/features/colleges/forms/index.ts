/**
 * Shared portal dialogs and vocabulary (React port of js/views/forms.js + the follow-up form of followups.js).
 *
 * Same names as forms.js. Two ways to use a dialog:
 *  - imperative, like before: `await logCall({ college_id, college_label, onSaved })` → result | null (cancelled).
 *    `PortalLayout` mounts the one `<FormsHost />` (tests mount their own; extra hosts are harmless).
 *  - declarative: `<LogCallDialog collegeId=… onDone={(r) => …} />` (mount it while open).
 * The old `ctx` first argument is gone (no ctx in React); everything else keeps its shape. Saving refreshes every
 * mounted query (portalApi writes clear the cache), so `onSaved` is optional.
 */
export { FormsHost, openDialog, closeAllDialogs } from "./host";
export { DialogForm, KEEP_OPEN, TextField, TextAreaField, SelectField, CheckField, MultiField, QuickDates, DangerZone, type Opt, type DialogFormProps } from "./kit";
export {
  CONTACT_ROLE_LABEL,
  CONTACT_STATUS,
  OUTCOMES,
  CALL_STATUS,
  STAGE_OPTS,
  STAGE_LABEL,
  STAGE_TONE,
  ROLE_OPTS,
  ROLE_LABEL,
  PERSON_STATUS_OPTS,
  BASIS_OPTS,
  CATEGORY,
  CATEGORY_LABEL,
  CATEGORY_OPTS,
  ACT_OPTS,
  OP_OPTS,
  ISSUES,
  ISSUE_HELP,
  FOLLOWUP_SCOPE_LABEL,
  isCallBack,
  reasonOf,
  formatPhone,
  PERSON_PHONE_RULE,
  normAnyPhone,
  normPhone,
  normEmail,
  StageBadge,
  ContactStatusBadge,
  CallStatusBadge,
  OutcomeBadge,
  ReasonBadge,
  contactLabel,
  TelLink,
  telLink,
  type OutcomeMeta,
} from "./labels";
export { addDays, num, str, arr, wholeOrNull, EMAIL_RE, validationError, rowsOf, listAll, safeUrl, errMsg, branchOpts, sortBranches, today } from "./util";
export { LogCallDialog, logCall, type LogCallOptions, type LogCallResult } from "./LogCall";
export { ContactDialog, addContact, editContact, checkContact, type ContactOptions } from "./Contact";
export {
  FollowupDialog,
  MarkDoneDialog,
  RescheduleDialog,
  openFollowupForm,
  addFollowup,
  markFollowupDone,
  rescheduleFollowup,
  rescheduleFollowups,
  reopenFollowup,
  patchFollowups,
  type FollowupRow,
  type FollowupPreset,
  type FollowupFormOptions,
  type FollowupScope,
  type BulkResult,
} from "./Followup";
export { PickCollegeDialog, pickCollege } from "./PickCollege";
export {
  PersonDialog,
  personDialog,
  addPerson,
  editPerson,
  movePerson,
  deactivatePerson,
  reactivatePerson,
  replaceLead,
  replaceLeadRequest,
  assignToLead,
  deletePerson,
  askOldLeadFate,
  findDuplicatePeople,
  validLeads,
  peopleRows,
  serverIsV4,
  sideEffectText,
  type PersonDialogOptions,
} from "./People";
export { RecordEnrollmentDialog, EditEnrollmentDialog, recordEnrollment, editEnrollment, type RecordEnrollmentOptions } from "./Enrollment";
export { ActivityDialog, logActivity, type LogActivityOptions } from "./Activity";
export { EditCollegeDialog, editCollege } from "./CollegeEdit";
export { BranchDialog, addBranch, editBranch, branchVals, branchBody, checkBranch, type BranchVals } from "./Branch";
export { mondayOf, periodKey, parsePeriod, periodLabel, saveTargetRow, type TargetRowInput, type PeriodKind } from "./targets";
export { personBranchIds, personOptLabel, confirmInactiveCredit, type TeamPerson } from "./team";
