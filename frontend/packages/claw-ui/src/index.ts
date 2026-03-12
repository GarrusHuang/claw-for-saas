/**
 * @claw/ui — AI UI 组件包公共导出。
 */

// ── Main Components ──
export { default as AIChatDialog } from './AIChatDialog.tsx';
export type { DialogMode } from './AIChatDialog.tsx';
export { default as ClawFloatingButton } from './ClawFloatingButton.tsx';

// ── Chat 子组件 ──
export { default as ChatMessageList } from './chat/ChatMessageList.tsx';
export { default as ChatInput } from './chat/ChatInput.tsx';
export { default as CoworkSidebar } from './chat/CoworkSidebar.tsx';
export { default as CollapsibleBlock } from './chat/CollapsibleBlock.tsx';
export {
  MiniTypeInference,
  MiniFieldUpdates,
  MiniAuditSummary,
  MiniDocumentPreview,
  MiniErrorCard,
  MiniParallelReviewCard,
  MiniPlanCard,
} from './chat/ChatResultCards.tsx';
export { default as ProgressPanel } from './chat/ProgressPanel.tsx';
export { default as InlineUploader } from './chat/InlineUploader.tsx';
export { default as InteractiveMessage } from './chat/InteractiveMessage.tsx';
export { default as SearchModal } from './chat/SearchModal.tsx';

// ── Results 组件 ──
export { default as TypeInferenceCard } from './results/TypeInferenceCard.tsx';
export { default as AuditResultCard } from './results/AuditResultCard.tsx';
export { default as DocumentCard } from './results/DocumentCard.tsx';
export { default as DocumentPresenter } from './results/DocumentPresenter.tsx';
export { default as DocumentPreviewModal } from './results/DocumentPreviewModal.tsx';
export { default as ContractDiffEditor } from './results/ContractDiffEditor.tsx';
export { default as DiffBlock } from './results/DiffBlock.tsx';
export type { DiffSection, DiffDecision, DiffType } from './results/DiffBlock.tsx';
export type { ContractAnnotation } from './results/ContractDiffEditor.tsx';

// ── Schedule 组件 ──
export { default as ScheduleView } from './schedule/ScheduleView.tsx';

// ── Skills 组件 ──
export { default as SkillsView } from './skills/SkillsView.tsx';
export { default as SkillEditorModal } from './skills/SkillEditorModal.tsx';
export { default as ImportModal } from './skills/ImportModal.tsx';
