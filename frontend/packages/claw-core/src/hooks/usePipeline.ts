/**
 * Pipeline 执行 Hook — REST POST 触发 + WebSocket 事件接收。
 *
 * invoke() 发送 POST /api/chat (application/json)，拿到 { session_id, trace_id }。
 * Pipeline 事件通过 WebSocket (useNotifications) 接收并分发到 store。
 * cancel() 发送 POST /api/chat/{session_id}/cancel。
 */

import { useCallback, useRef } from 'react';
import { getAIConfig } from '../config.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import { useSessionStatusStore } from '../stores/session-status.ts';
import type { CandidateType, FormFieldDef, AuditRuleDef, KnownValue } from '../types/scenario.ts';

// ── 调用参数类型 ──

export interface InvokeParams {
  action: string;
  businessType: string;
  userId?: string;
  sessionId?: string;
  userMessage?: string;
  materials?: Array<{
    material_id: string;
    material_type: string;
    content: string;
    filename: string;
  }>;
  formFields?: FormFieldDef[];
  auditRules?: AuditRuleDef[];
  candidateTypes?: CandidateType[];
  knownValues?: KnownValue[];
}

export function usePipeline() {
  // ── 细粒度 selectors ──
  const status = usePipelineStore((s) => s.status);
  const scenario = usePipelineStore((s) => s.scenario);
  const traceId = usePipelineStore((s) => s.traceId);
  const sessionId = usePipelineStore((s) => s.sessionId);
  const conversationHistory = usePipelineStore((s) => s.conversationHistory);
  const plan = usePipelineStore((s) => s.plan);
  const steps = usePipelineStore((s) => s.steps);
  const currentStep = usePipelineStore((s) => s.currentStep);
  const inferredType = usePipelineStore((s) => s.inferredType);
  const fieldValues = usePipelineStore((s) => s.fieldValues);
  const auditSummary = usePipelineStore((s) => s.auditSummary);
  const document = usePipelineStore((s) => s.document);
  const startedAt = usePipelineStore((s) => s.startedAt);
  const completedAt = usePipelineStore((s) => s.completedAt);
  const durationMs = usePipelineStore((s) => s.durationMs);
  const eventLog = usePipelineStore((s) => s.eventLog);
  const error = usePipelineStore((s) => s.error);
  const errorDetail = usePipelineStore((s) => s.errorDetail);
  const workflowPhase = usePipelineStore((s) => s.workflowPhase);
  const workflowProgress = usePipelineStore((s) => s.workflowProgress);
  const parallelReview = usePipelineStore((s) => s.parallelReview);

  const isInvokingRef = useRef(false);

  const invoke = useCallback(
    async (params: InvokeParams) => {
      // 防止并发 invoke
      if (isInvokingRef.current) {
        console.warn('[usePipeline] invoke already in progress, skipping duplicate');
        return;
      }
      isInvokingRef.current = true;

      try {
        // 多轮对话：使用 softReset 保留 session 信息；首次调用用 reset
        const isFollowUp = !!params.sessionId && params.sessionId === usePipelineStore.getState().sessionId;
        if (isFollowUp) {
          usePipelineStore.getState().softReset();
        } else {
          usePipelineStore.getState().reset();
        }

        // 记录用户消息到对话历史
        if (params.userMessage) {
          usePipelineStore.getState().addConversationTurn('user', params.userMessage);
        }

        // 只设 status=running，不调 startPipeline (它会重置 toolExecutions 等)
        // startPipeline 由 WS pipeline_started 事件触发 (与旧 SSE 行为一致)
        usePipelineStore.setState({ status: 'running' as const, startedAt: Date.now() });

        const requestBody = {
          user_id: params.userId || getAIConfig().defaultUserId,
          session_id: params.sessionId || usePipelineStore.getState().sessionId || undefined,
          message: params.userMessage || `请帮我处理${params.action}`,
          business_type: params.action,
          materials: params.materials || [],
        };

        // Build auth headers
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        const config = getAIConfig();
        if (config.getAuthToken) {
          const token = await config.getAuthToken();
          if (token) headers['Authorization'] = `Bearer ${token}`;
        } else if (config.authToken) {
          headers['Authorization'] = `Bearer ${config.authToken}`;
        }

        const response = await fetch(`${config.aiBaseUrl}/api/chat`, {
          method: 'POST',
          headers,
          body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
          const errorText = await response.text().catch(() => '');
          throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
        }

        const result = await response.json() as { session_id: string | null; trace_id: string };

        // Update session ID and trace_id from response
        if (result.session_id) {
          usePipelineStore.getState().setSessionId(result.session_id);
          useSessionStatusStore.getState().addRunning(result.session_id);
        }
        if (result.trace_id) {
          usePipelineStore.setState({ traceId: result.trace_id });
        }

        // Events will arrive via WebSocket (pipeline_event) → useNotifications → dispatchPipelineEvent → store update
        // No SSE connection needed here.

      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        usePipelineStore.getState().setError(message);
        usePipelineStore.getState().setErrorDetail({
          message,
          category: 'network',
          affectedStep: '',
          suggestedAction: '请检查网络连接后重试',
          traceId: '',
        });
      } finally {
        isInvokingRef.current = false;
      }
    },
    [],
  );

  const cancel = useCallback(async () => {
    const currentSessionId = usePipelineStore.getState().sessionId;
    if (!currentSessionId) return;

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const config = getAIConfig();
      if (config.getAuthToken) {
        const token = await config.getAuthToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
      } else if (config.authToken) {
        headers['Authorization'] = `Bearer ${config.authToken}`;
      }

      await fetch(`${config.aiBaseUrl}/api/chat/${encodeURIComponent(currentSessionId)}/cancel`, {
        method: 'POST',
        headers,
      });
    } catch (err) {
      console.warn('[usePipeline] Cancel request failed:', err);
    }

    // Mark as cancelled locally
    const state = usePipelineStore.getState();
    if (state.status === 'running') {
      usePipelineStore.getState().completePipeline('cancelled', Date.now() - (state.startedAt || Date.now()));
    }
    useSessionStatusStore.getState().removeRunning(currentSessionId);
  }, []);

  return {
    invoke,
    cancel,
    status,
    scenario,
    traceId,
    sessionId,
    conversationHistory,
    plan,
    steps,
    currentStep,
    inferredType,
    fieldValues,
    auditSummary,
    document,
    startedAt,
    completedAt,
    durationMs,
    eventLog,
    error,
    errorDetail,
    workflowPhase,
    workflowProgress,
    parallelReview,
  };
}
