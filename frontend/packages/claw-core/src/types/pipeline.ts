/**
 * Pipeline 类型定义 — 包括 Phase 8/9/13 新增类型。
 */

export type PipelineStatus = 'idle' | 'running' | 'completed' | 'failed';

export interface StepProgress {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  component: string;
  durationMs?: number;
  attempt?: number;
}

export interface InferredType {
  docType: string;
  confidence: number;
  reasoning: string;
}

export interface FieldValue {
  fieldId: string;
  value: unknown;
  source: string;
  confidence: number;
}

export interface AuditItem {
  ruleId: string;
  status: 'pass' | 'fail' | 'warning';
  message: string;
}

export interface AuditSummary {
  results: AuditItem[];
  passCount: number;
  failCount: number;
  warningCount: number;
  conclusion: string;
}

export interface GeneratedDocument {
  documentType: string;
  title: string;
  content: string;
  metadata: Record<string, unknown>;
}

export interface PlanStep {
  step: number;
  description: string;
  tools?: string[];
}

export type PlanStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface PlanStepTracking {
  step: number;
  description: string;
  status: PlanStepStatus;
  startedAt: number | null;
  completedAt: number | null;
}

export interface PlanProposal {
  summary: string;
  detail: string;
  steps: PlanStep[];
  estimatedActions: number;
}

export interface PipelineEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface ConversationTurn {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export interface ToolExecution {
  id: string;
  toolName: string;
  success: boolean;
  latencyMs: number;
  timestamp: number;
  argsSummary?: Record<string, string>;
  resultSummary?: string;
  blocked?: boolean;
  pending?: boolean;
}

export interface AgentIterationInfo {
  current: number;
  max: number;
  callingTools: string[];
}

// ────────────────────────────────────────────────────
// Phase 8: 增强错误详情
// ────────────────────────────────────────────────────

export interface ErrorDetail {
  /** 错误信息 */
  message: string;
  /** 错误分类: rate_limit | auth | tool_error | validation | internal | network */
  category: string;
  /** 受影响的步骤 */
  affectedStep: string;
  /** 建议操作 */
  suggestedAction: string;
  /** 追踪 ID */
  traceId: string;
}

// ────────────────────────────────────────────────────
// Phase 13: 并行审查
// ────────────────────────────────────────────────────

export interface AgentReviewResult {
  agentRole: string;
  conclusion: string;
  confidence: number;
  details: string;
  durationMs: number;
}

export interface ParallelReviewState {
  roles: string[];
  status: 'running' | 'completed';
  overallStatus: string;
  overallConfidence: number;
  results: AgentReviewResult[];
  durationMs: number;
}

// ────────────────────────────────────────────────────
// Phase 24: Agent 交互请求
// ────────────────────────────────────────────────────

export interface InteractionOption {
  label: string;
  value: string;
}

export type PendingInteraction =
  | { type: 'upload'; prompt: string; accept: string }
  | { type: 'confirmation'; message: string; options: InteractionOption[] }
  | { type: 'input'; prompt: string; fieldType: string };
