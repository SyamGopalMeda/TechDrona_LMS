import type { ReactNode } from "react";

/**
 * Integration point for importing questions from a question bank into an assignment section.
 * By default the editor uses the question-bank feature's `QuestionBankPicker`; `renderPicker`
 * lets a host substitute another picker.
 */
export type PickedQuestion = {
  question_id: string;
  question_version_id?: string | null;
  question_type: string;
  stem_html: string;
  default_marks?: number;
};

export interface BankPickerProps {
  open: boolean;
  onClose(): void;
  onAdd(q: PickedQuestion[]): void;
}

export type RenderBankPicker = (props: BankPickerProps) => ReactNode;

