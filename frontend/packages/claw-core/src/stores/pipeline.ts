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

export interface FileArtifact {
  path: string;
  filename: string;
  sizeBytes: number;
  contentType: string;
  sessionId: string;
}

export interface TimelineEntry {
  id: string;
  type: 'thinking' | 'tool' | 'text';
  timestamp: number;
  // thinking / text
  iteration?: number;
  content?: string;
  // tool
  toolExecution?: ToolExecution;
}

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

  // Plan (progress display only)
  plan: PlanProposal | null;
  agentPlanProposed: boolean;
  agentMessage: string | null;

  // Streaming text
  streamingText: string;
  isStreaming: boolean;
  thinkingText: string;

  // Timeline: thinking + tool_executed 按时间顺序排列
  timelineEntries: TimelineEntry[];

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

  // Phase 6: Agent 生成的文件
  fileArtifacts: FileArtifact[];

  // Skills loaded for this pipeline
  loadedSkills: string[];

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
  clearPlan: () => void;
  setAgentPlanProposed: (v: boolean) => void;
  setAgentMessage: (msg: string) => void;
  appendStreamingText: (text: string) => void;
  setIsStreaming: (v: boolean) => void;
  clearStreamingText: () => void;
  appendThinkingText: (text: string, iteration?: number) => void;
  appendTextToTimeline: (text: string, iteration: number) => void;
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
  completePlanStep: (index: number) => void;
  failPlanStep: (index: number) => void;
  completePlanSteps: () => void;
  // Phase 24: Agent 交互请求
  setPendingInteraction: (interaction: PendingInteraction | null) => void;
  resolveInteraction: () => void;
  // Phase 6: File artifacts
  addFileArtifact: (artifact: FileArtifact) => void;
  // Skills loaded
  setLoadedSkills: (skills: string[]) => void;
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
  agentPlanProposed: false,
  agentMessage: null as string | null,
  streamingText: '',
  isStreaming: false,
  thinkingText: '',
  timelineEntries: [] as TimelineEntry[],
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
  // Phase 6: File artifacts
  fileArtifacts: [] as FileArtifact[],
  // Skills loaded
  loadedSkills: [] as string[],
  // 文档采纳
  adoptedDocument: null as GeneratedDocument | null,
  // Metadata
  startedAt: null as number | null,
  completedAt: null as number | null,
  durationMs: 0,
  eventLog: [] as PipelineEvent[],
  error: null as string | null,
};

const MAX_EVENT_LOG_SIZE = 500;

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
      // 保留历史 toolExecutions，右栏知识库/制品依赖它跨轮次显示
      toolExecutions: state.toolExecutions,
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
  clearPlan: () => set({ plan: null }),
  setAgentPlanProposed: (v) => set({ agentPlanProposed: v }),
  setAgentMessage: (msg) => set({ agentMessage: msg }),

  appendStreamingText: (text) =>
    set((state) => ({ streamingText: state.streamingText + text, isStreaming: true })),
  setIsStreaming: (v) => set({ isStreaming: v }),
  clearStreamingText: () => set({ streamingText: '', isStreaming: false }),
  appendThinkingText: (text, iteration) =>
    set((state) => {
      const entries = [...state.timelineEntries];
      // 同一迭代的 thinking 追加到同一条 entry
      const last = entries[entries.length - 1];
      if (last && last.type === 'thinking' && last.iteration === iteration) {
        entries[entries.length - 1] = { ...last, content: (last.content || '') + text };
      } else {
        entries.push({
          id: `think-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          type: 'thinking',
          timestamp: Date.now(),
          iteration: iteration || 0,
          content: text,
        });
      }
      return { thinkingText: state.thinkingText + text, timelineEntries: entries };
    }),

  appendTextToTimeline: (text: string, iteration: number) =>
    set((state) => {
      const entries = [...state.timelineEntries];
      // 同一迭代的 text 追加到同一条 entry
      const last = entries[entries.length - 1];
      if (last && last.type === 'text' && last.iteration === iteration) {
        entries[entries.length - 1] = { ...last, content: (last.content || '') + text };
      } else {
        entries.push({
          id: `text-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          type: 'text',
          timestamp: Date.now(),
          iteration: iteration || 0,
          content: text,
        });
      }
      return { timelineEntries: entries };
    }),

  addToolExecution: (data) =>
    set((state) => {
      // 查找并替换对应的 pending 条目
      const pendingIdx = state.timelineEntries.findIndex(
        (e) => e.type === 'tool' && e.toolExecution?.pending && e.toolExecution.toolName === data.toolName,
      );
      const completedEntry = {
        id: data.id,
        type: 'tool' as const,
        timestamp: data.timestamp || Date.now(),
        toolExecution: data,
      };
      const entries = [...state.timelineEntries];
      if (pendingIdx >= 0) {
        entries[pendingIdx] = completedEntry;
      } else {
        entries.push(completedEntry);
      }
      return {
        toolExecutions: [...state.toolExecutions, data],
        timelineEntries: entries,
        agentIteration: {
          ...state.agentIteration,
          callingTools: state.agentIteration.callingTools.filter((t) => t !== data.toolName),
        },
      };
    }),

  setCallingTools: (tools) =>
    set((state) => {
      // 为每个工具插入 pending 状态的 timeline 条目
      const newEntries = tools.map((toolName) => ({
        id: `pending-${toolName}-${Date.now()}`,
        type: 'tool' as const,
        timestamp: Date.now(),
        toolExecution: {
          id: `pending-${toolName}-${Date.now()}`,
          toolName,
          success: true,
          latencyMs: 0,
          timestamp: Date.now(),
          pending: true,
        },
      }));
      return {
        agentIteration: { ...state.agentIteration, callingTools: tools },
        timelineEntries: [...state.timelineEntries, ...newEntries],
      };
    }),

  setAgentIterationInfo: (current, max) =>
    set((state) => ({
      agentIteration: { ...state.agentIteration, current, max },
    })),

  completePipeline: (status, durationMs) =>
    set({
      status: status === 'success' ? 'completed' : 'failed',
      completedAt: Date.now(),
      durationMs,
    }),

  setError: (error) => set({ error, status: 'failed' }),

  addEvent: (event) =>
    set((state) => {
      const newLog = [...state.eventLog, event];
      return { eventLog: newLog.length > MAX_EVENT_LOG_SIZE ? newLog.slice(-MAX_EVENT_LOG_SIZE) : newLog };
    }),

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

  completePlanStep: (index) =>
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

  // Phase 6: File artifacts
  addFileArtifact: (artifact) =>
    set((state) => ({ fileArtifacts: [...state.fileArtifacts, artifact] })),

  // Skills loaded
  setLoadedSkills: (skills) => set({ loadedSkills: skills }),

  // 文档采纳
  adoptDocument: (doc) => set({ adoptedDocument: doc }),
}));
