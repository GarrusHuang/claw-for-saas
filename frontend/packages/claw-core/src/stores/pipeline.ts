/**
 * Pipeline 数据状态 Store — 增强版。
 *
 * Phase 8: ErrorDetail (category/suggestedAction)
 * Phase 9: workflowPhase + workflowProgress
 * Phase 13: ParallelReviewState
 */

import { create } from 'zustand';
import type {
  PipelineStatus, StepProgress, InferredType, FieldValue,
  AuditSummary, GeneratedDocument, PlanStep, PlanProposal, PipelineEvent,
  ConversationTurn, ToolExecution, AgentIterationInfo,
  ErrorDetail, ParallelReviewState, PlanStepTracking,
  PendingInteraction,
} from '../types/pipeline.ts';

// Re-export types for convenience
export type {
  PipelineStatus, StepProgress, InferredType, FieldValue,
  AuditSummary, GeneratedDocument, PlanStep, PlanProposal, PipelineEvent,
  ConversationTurn, ToolExecution, AgentIterationInfo,
  ErrorDetail, ParallelReviewState, AuditItem, AgentReviewResult,
  PlanStepStatus, PlanStepTracking,
  PendingInteraction, InteractionOption,
} from '../types/pipeline.ts';


interface PipelineState {
  // Status
  status: PipelineStatus;
  scenario: string;
  traceId: string;

  // Session (multi-turn)
  sessionId: string | null;
  conversationHistory: ConversationTurn[];

  // Steps
  steps: StepProgress[];
  currentStep: string;

  // Plan mode
  plan: PlanProposal | null;
  planMode: boolean;
  agentPlanProposed: boolean;
  agentMessage: string | null;

  // Streaming text
  streamingText: string;
  isStreaming: boolean;
  thinkingText: string;

  // Results
  inferredType: InferredType | null;
  fieldValues: FieldValue[];
  auditSummary: AuditSummary | null;
  document: GeneratedDocument | null;
  // Phase 23: 多文档支持
  documents: GeneratedDocument[];

  // Real-time tool tracking
  toolExecutions: ToolExecution[];
  agentIteration: AgentIterationInfo;

  // Phase 8: 增强错误详情
  errorDetail: ErrorDetail | null;

  // Phase 9: 工作流阶段
  workflowPhase: string;
  workflowProgress: number;

  // Phase 13: 并行审查
  parallelReview: ParallelReviewState | null;

  // Phase 21: Plan step tracking
  planSteps: PlanStepTracking[];

  // Phase 24: Agent 交互请求
  pendingInteraction: PendingInteraction | null;

  // 文档采纳 — 宿主表单采纳 AI 生成的文档
  adoptedDocument: GeneratedDocument | null;

  // Metadata
  startedAt: number | null;
  completedAt: number | null;
  durationMs: number;
  eventLog: PipelineEvent[];
  error: string | null;

  // Actions
  reset: () => void;
  softReset: () => void;
  startPipeline: (scenario: string, steps: string[]) => void;
  updateStepProgress: (data: Record<string, unknown>) => void;
  setInferredType: (data: InferredType) => void;
  addFieldValue: (data: FieldValue) => void;
  setAuditSummary: (data: AuditSummary) => void;
  setDocument: (data: GeneratedDocument) => void;
  addDocument: (data: GeneratedDocument) => void;
  setPlan: (data: PlanProposal) => void;
  setPlanMode: (mode: boolean) => void;
  clearPlan: () => void;
  setAgentPlanProposed: (v: boolean) => void;
  setAgentMessage: (msg: string) => void;
  appendStreamingText: (text: string) => void;
  setIsStreaming: (v: boolean) => void;
  clearStreamingText: () => void;
  appendThinkingText: (text: string) => void;
  addToolExecution: (data: ToolExecution) => void;
  setCallingTools: (tools: string[]) => void;
  setAgentIterationInfo: (current: number, max: number) => void;
  completePipeline: (status: string, durationMs: number) => void;
  setError: (error: string) => void;
  addEvent: (event: PipelineEvent) => void;
  setSessionId: (id: string) => void;
  addConversationTurn: (role: 'user' | 'assistant', content: string) => void;
  // Phase 8
  setErrorDetail: (detail: ErrorDetail | null) => void;
  // Phase 9
  setWorkflowPhase: (phase: string, progress: number) => void;
  // Phase 13
  setParallelReview: (review: ParallelReviewState | null) => void;
  // Phase 21: Plan step tracking (后端驱动)
  initPlanSteps: (steps: PlanStep[]) => void;
  startPlanStep: (index: number) => void;
  completePlanStep: (index: number, durationMs?: number) => void;
  failPlanStep: (index: number) => void;
  completePlanSteps: () => void;
  // Phase 24: Agent 交互请求
  setPendingInteraction: (interaction: PendingInteraction | null) => void;
  resolveInteraction: () => void;
  // 文档采纳
  adoptDocument: (doc: GeneratedDocument) => void;
}

const initialState = {
  status: 'idle' as PipelineStatus,
  scenario: '',
  traceId: '',
  sessionId: null as string | null,
  conversationHistory: [] as ConversationTurn[],
  plan: null as PlanProposal | null,
  planMode: true,
  agentPlanProposed: false,
  agentMessage: null as string | null,
  streamingText: '',
  isStreaming: false,
  thinkingText: '',
  steps: [] as StepProgress[],
  currentStep: '',
  inferredType: null as InferredType | null,
  fieldValues: [] as FieldValue[],
  auditSummary: null as AuditSummary | null,
  document: null as GeneratedDocument | null,
  documents: [] as GeneratedDocument[],
  toolExecutions: [] as ToolExecution[],
  agentIteration: { current: 0, max: 15, callingTools: [] as string[] } as AgentIterationInfo,
  // Phase 8
  errorDetail: null as ErrorDetail | null,
  // Phase 9
  workflowPhase: '',
  workflowProgress: 0,
  // Phase 13
  parallelReview: null as ParallelReviewState | null,
  // Phase 21
  planSteps: [] as PlanStepTracking[],
  // Phase 24
  pendingInteraction: null as PendingInteraction | null,
  // 文档采纳
  adoptedDocument: null as GeneratedDocument | null,
  // Metadata
  startedAt: null as number | null,
  completedAt: null as number | null,
  durationMs: 0,
  eventLog: [] as PipelineEvent[],
  error: null as string | null,
};

export const usePipelineStore = create<PipelineState>((set) => ({
  ...initialState,

  reset: () => set({ ...initialState }),

  softReset: () =>
    set((state) => ({
      ...initialState,
      sessionId: state.sessionId,
      conversationHistory: state.conversationHistory,
      // 保留 plan 数据，执行阶段需要 TodoList 持续显示
      plan: state.plan,
      agentPlanProposed: state.agentPlanProposed,
      planSteps: state.planSteps.map((s) => ({
        ...s,
        status: 'pending' as const,
        startedAt: null,
        completedAt: null,
      })),
    })),

  startPipeline: (scenario, steps) =>
    set((state) => ({
      ...initialState,
      status: 'running',
      scenario,
      sessionId: state.sessionId,
      conversationHistory: state.conversationHistory,
      // 保留 plan 数据 (执行阶段复用 planning 阶段的 plan steps)
      plan: state.plan,
      agentPlanProposed: state.agentPlanProposed,
      planSteps: state.planSteps.map((s) => ({
        ...s,
        status: 'pending' as const,
        startedAt: null,
        completedAt: null,
      })),
      startedAt: Date.now(),
      steps: steps.map((name) => ({
        name,
        status: 'pending' as const,
        component: '',
      })),
    })),

  updateStepProgress: (data) =>
    set((state) => {
      const stepName = data.step as string;
      const status = data.status as string;

      const steps = state.steps.map((s) => {
        if (s.name !== stepName) return s;
        let newStatus: StepProgress['status'] = s.status;
        if (status === 'step_started' || status === 'started') newStatus = 'running';
        else if (status === 'step_completed' || status === 'completed') newStatus = 'completed';
        else if (status === 'failed' || status === 'error') newStatus = 'failed';
        return {
          ...s, status: newStatus,
          component: (data.component as string) || s.component,
          durationMs: (data.duration_ms as number) || s.durationMs,
          attempt: (data.attempt as number) || s.attempt,
        };
      });
      return { steps, currentStep: stepName };
    }),

  setInferredType: (data) => set({ inferredType: data }),

  addFieldValue: (data) =>
    set((state) => {
      const existing = state.fieldValues.filter((f) => f.fieldId !== data.fieldId);
      return { fieldValues: [...existing, data] };
    }),

  setAuditSummary: (data) => set({ auditSummary: data }),
  setDocument: (data) => set((state) => ({ document: data, documents: [...state.documents, data] })),
  addDocument: (data) => set((state) => ({ documents: [...state.documents, data] })),

  setPlan: (data) => set({ plan: data }),
  setPlanMode: (mode) => set({ planMode: mode }),
  clearPlan: () => set({ plan: null }),
  setAgentPlanProposed: (v) => set({ agentPlanProposed: v }),
  setAgentMessage: (msg) => set({ agentMessage: msg }),

  appendStreamingText: (text) =>
    set((state) => ({ streamingText: state.streamingText + text, isStreaming: true })),
  setIsStreaming: (v) => set({ isStreaming: v }),
  clearStreamingText: () => set({ streamingText: '', isStreaming: false }),
  appendThinkingText: (text) =>
    set((state) => ({
      thinkingText: state.thinkingText ? state.thinkingText + '\n\n' + text : text,
    })),

  addToolExecution: (data) =>
    set((state) => ({
      toolExecutions: [...state.toolExecutions, data],
      agentIteration: {
        ...state.agentIteration,
        callingTools: state.agentIteration.callingTools.filter((t) => t !== data.toolName),
      },
    })),

  setCallingTools: (tools) =>
    set((state) => ({
      agentIteration: { ...state.agentIteration, callingTools: tools },
    })),

  setAgentIterationInfo: (current, max) =>
    set((state) => ({
      agentIteration: { ...state.agentIteration, current, max },
    })),

  completePipeline: (status, durationMs) =>
    set({
      status: status === 'plan_awaiting_approval'
        ? 'plan_awaiting'
        : status === 'success' ? 'completed' : 'failed',
      completedAt: Date.now(),
      durationMs,
    }),

  setError: (error) => set({ error, status: 'failed' }),

  addEvent: (event) =>
    set((state) => ({ eventLog: [...state.eventLog, event] })),

  setSessionId: (id) => set({ sessionId: id }),

  addConversationTurn: (role, content) =>
    set((state) => ({
      conversationHistory: [
        ...state.conversationHistory,
        { role, content, timestamp: Date.now() },
      ],
    })),

  // Phase 8: 设置增强错误详情
  setErrorDetail: (detail) => set({ errorDetail: detail }),

  // Phase 9: 设置工作流阶段和进度
  setWorkflowPhase: (phase, progress) => set({ workflowPhase: phase, workflowProgress: progress }),

  // Phase 13: 设置并行审查状态
  setParallelReview: (review) => set({ parallelReview: review }),

  // Phase 21: Plan step tracking (后端驱动)
  initPlanSteps: (steps) =>
    set({
      planSteps: steps.map((s) => ({
        step: s.step,
        description: s.description,
        status: 'pending' as const,
        startedAt: null,
        completedAt: null,
      })),
    }),

  startPlanStep: (index) =>
    set((state) => ({
      planSteps: state.planSteps.map((s, i) =>
        i === index ? { ...s, status: 'running' as const, startedAt: Date.now() } : s,
      ),
    })),

  completePlanStep: (index, durationMs) =>
    set((state) => ({
      planSteps: state.planSteps.map((s, i) =>
        i === index ? { ...s, status: 'completed' as const, completedAt: Date.now() } : s,
      ),
    })),

  failPlanStep: (index) =>
    set((state) => ({
      planSteps: state.planSteps.map((s, i) =>
        i === index ? { ...s, status: 'failed' as const, completedAt: Date.now() } : s,
      ),
    })),

  completePlanSteps: () =>
    set((state) => {
      const now = Date.now();
      return {
        planSteps: state.planSteps.map((s) =>
          s.status === 'running' || s.status === 'pending'
            ? { ...s, status: 'completed' as const, completedAt: now }
            : s,
        ),
      };
    }),

  // Phase 24: Agent 交互请求
  setPendingInteraction: (interaction) => set({ pendingInteraction: interaction }),
  resolveInteraction: () => set({ pendingInteraction: null }),

  // 文档采纳
  adoptDocument: (doc) => set({ adoptedDocument: doc }),
}));
