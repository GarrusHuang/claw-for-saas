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
} from './types/pipeline.ts';

// ── Stores ──
export { usePipelineStore } from './stores/pipeline.ts';
export { useAIChatStore } from './stores/ai-chat.ts';
export type { ChatDialogState, ContentView, SessionAction, AIChatState } from './stores/ai-chat.ts';
export { useAuthStore } from './stores/auth.ts';
export type { AuthState } from './stores/auth.ts';

// ── Services ──
export { AgentSSEClient } from './services/sse.ts';
export type { SSEEventType, SSEEvent, SSEClientOptions } from './services/sse.ts';
export * as aiApi from './services/ai-api.ts';
export type {
  SessionInfo, SessionDetail,
  SkillMetadata, SkillDetail, SkillCreatePayload,
  MemoryStats,
  FileInfo, ToolInfo,
  CorrectionPayload, CorrectionResult,
  ScheduledTask, ScheduleCreatePayload, ScheduleUpdatePayload,
} from './services/ai-api.ts';

// ── Hooks ──
export { usePipeline } from './hooks/usePipeline.ts';
export type { InvokeParams } from './hooks/usePipeline.ts';
export { useAIChat } from './hooks/useAIChat.ts';
export type { ChatMessage } from './hooks/useAIChat.ts';
