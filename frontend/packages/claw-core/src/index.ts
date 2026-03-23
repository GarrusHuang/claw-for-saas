/**
 * @claw/core — AI 核心包公共导出。
 *
 * 提供 AI 状态管理、服务、Hook 和类型定义。
 * 宿主应用通过 configureAI() 注入场景配置后即可使用。
 */

// ── Config ──
export { configureAI, getAIConfig, getAllScenarios, setNavigate } from './config.ts';
export type { AIConfig } from './config.ts';

// ── Types ──
export type {
  ScenarioConfig,
  FormSection,
  CandidateType,
  FormFieldDef,
  FieldType,
  AuditRuleDef,
  KnownValue,
} from './types/scenario.ts';

export type {
  PipelineStatus,
  StepProgress,
  InferredType,
  FieldValue,
  AuditItem,
  AuditSummary,
  GeneratedDocument,
  PlanStep,
  PlanStepStatus,
  PlanStepTracking,
  PlanProposal,
  PipelineEvent,
  ConversationTurn,
  ToolExecution,
  AgentIterationInfo,
  ErrorDetail,
  AgentReviewResult,
  ParallelReviewState,
  PendingInteraction,
  InteractionOption,
  FileChange,
} from './types/pipeline.ts';

// ── Stores ──
export { usePipelineStore } from './stores/pipeline.ts';
export type { TimelineEntry, FileArtifact } from './stores/pipeline.ts';
export { useAIChatStore } from './stores/ai-chat.ts';
export type { ChatDialogState, ContentView, SessionAction, AIChatState } from './stores/ai-chat.ts';
export { useAuthStore } from './stores/auth.ts';
export type { AuthState } from './stores/auth.ts';
export { useSessionStatusStore } from './stores/session-status.ts';
export { saveSession, restoreSession, clearSession, hasSession, saveMessages, restoreMessages, getCachedStatus } from './stores/pipeline-cache.ts';
export type { PipelineStateSnapshot } from './stores/pipeline-cache.ts';

// ── Services ──
export { dispatchPipelineEvent, applyPipelineSnapshot, setReplayPending } from './services/pipeline-dispatcher.ts';
export * as aiApi from './services/ai-api.ts';
export type {
  SessionInfo, SessionDetail, SearchResult,
  SkillMetadata, SkillDetail, SkillCreatePayload,
  MemoryStats,
  FileInfo, ToolInfo,
  CorrectionPayload, CorrectionResult,
  RunRecord, ScheduledTask, ScheduleCreatePayload, ScheduleUpdatePayload,
  KBFileInfo,
  PipelineSnapshot,
} from './services/ai-api.ts';
export { apiFetch, fetchPipelineSnapshot, fetchRunningSessions } from './services/ai-api.ts';

// ── Hooks ──
export { usePipeline } from './hooks/usePipeline.ts';
export type { InvokeParams } from './hooks/usePipeline.ts';
export { useAIChat } from './hooks/useAIChat.ts';
export type { ChatMessage, ChatMessageFile, ChatTimelineEntry } from './hooks/useAIChat.ts';
export { useChatMessages } from './hooks/useChatMessages.ts';
export type { UseChatMessagesReturn } from './hooks/useChatMessages.ts';
export { useSessionManager } from './hooks/useSessionManager.ts';
export type { UseSessionManagerParams, UseSessionManagerReturn } from './hooks/useSessionManager.ts';
export { useNotifications } from './hooks/useNotifications.ts';
export type { NotificationHandler } from './hooks/useNotifications.ts';
