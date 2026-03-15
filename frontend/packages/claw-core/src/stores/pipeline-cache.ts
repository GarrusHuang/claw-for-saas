/**
 * Pipeline Session Cache — 切换会话/F5 刷新时保存/恢复 Pipeline Store 快照 + 消息。
 *
 * 使用 sessionStorage（浏览器存储，同标签页内 F5 不丢失）替代内存 Map。
 * 切走时 saveSession，F5 前 beforeunload 自动保存，回来时 restoreSession 恢复。
 */

import { usePipelineStore } from './pipeline.ts';

/**
 * Pipeline 状态快照 — 保存的字段子集。
 */
export interface PipelineStateSnapshot {
  sessionId: string | null;
  status: string;
  scenario: string;
  conversationHistory: unknown[];
  streamingText: string;
  isStreaming: boolean;
  thinkingText: string;
  timelineEntries: unknown[];
  inferredType: unknown;
  fieldValues: unknown[];
  auditSummary: unknown;
  document: unknown;
  documents: unknown[];
  toolExecutions: unknown[];
  agentIteration: unknown;
  plan: unknown;
  agentPlanProposed: boolean;
  agentMessage: string | null;
  planSteps: unknown[];
  fileArtifacts: unknown[];
  loadedSkills: string[];
  errorDetail: unknown;
  error: string | null;
  startedAt: number | null;
  completedAt: number | null;
  durationMs: number;
  eventLog: unknown[];
  pendingInteraction: unknown;
  workflowPhase: string;
  workflowProgress: number;
  parallelReview: unknown;
  adoptedDocument: unknown;
}

// ── sessionStorage helpers ──

const CACHE_PREFIX = 'claw-pipe-';
const MSG_PREFIX = 'claw-msg-';

function storageGet<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : null;
  } catch {
    return null;
  }
}

function storageSet(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // sessionStorage full — silently ignore
  }
}

function storageRemove(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // ignore
  }
}

/** Save current pipeline store state to cache. */
export function saveSession(sessionId: string): void {
  const state = usePipelineStore.getState();
  const snapshot: PipelineStateSnapshot = {
    sessionId: state.sessionId,
    status: state.status,
    scenario: state.scenario,
    conversationHistory: state.conversationHistory,
    streamingText: state.streamingText,
    isStreaming: state.isStreaming,
    thinkingText: state.thinkingText,
    timelineEntries: state.timelineEntries,
    inferredType: state.inferredType,
    fieldValues: state.fieldValues,
    auditSummary: state.auditSummary,
    document: state.document,
    documents: state.documents,
    toolExecutions: state.toolExecutions,
    agentIteration: state.agentIteration,
    plan: state.plan,
    agentPlanProposed: state.agentPlanProposed,
    agentMessage: state.agentMessage,
    planSteps: state.planSteps,
    fileArtifacts: state.fileArtifacts,
    loadedSkills: state.loadedSkills,
    errorDetail: state.errorDetail,
    error: state.error,
    startedAt: state.startedAt,
    completedAt: state.completedAt,
    durationMs: state.durationMs,
    eventLog: state.eventLog,
    pendingInteraction: state.pendingInteraction,
    workflowPhase: state.workflowPhase,
    workflowProgress: state.workflowProgress,
    parallelReview: state.parallelReview,
    adoptedDocument: state.adoptedDocument,
  };
  storageSet(CACHE_PREFIX + sessionId, snapshot);
}

/** Restore pipeline state from cache. Returns true if cache hit. */
export function restoreSession(sessionId: string): boolean {
  const snapshot = storageGet<PipelineStateSnapshot>(CACHE_PREFIX + sessionId);
  if (!snapshot) return false;
  usePipelineStore.setState(snapshot as Partial<ReturnType<typeof usePipelineStore.getState>>);
  return true;
}

/** Clear cached state for a session. */
export function clearSession(sessionId: string): void {
  storageRemove(CACHE_PREFIX + sessionId);
  storageRemove(MSG_PREFIX + sessionId);
}

/** Check if a session has cached state. */
export function hasSession(sessionId: string): boolean {
  return sessionStorage.getItem(CACHE_PREFIX + sessionId) !== null;
}

/** Get cached pipeline status for a session (used to detect F5 during running). */
export function getCachedStatus(sessionId: string): string | null {
  const snapshot = storageGet<PipelineStateSnapshot>(CACHE_PREFIX + sessionId);
  return snapshot?.status ?? null;
}

/** Save messages for a session. */
export function saveMessages(sessionId: string, messages: unknown[]): void {
  storageSet(MSG_PREFIX + sessionId, messages);
}

/** Restore messages for a session. Returns null if no cache. */
export function restoreMessages(sessionId: string): unknown[] | null {
  return storageGet<unknown[]>(MSG_PREFIX + sessionId);
}

/**
 * 获取当前活跃 session ID（用于 beforeunload 自动保存）。
 */
export function getCurrentSessionId(): string | null {
  return usePipelineStore.getState().sessionId;
}
