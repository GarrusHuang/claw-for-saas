/**
 * Pipeline 执行 Hook — 封装 SSE 连接 + Store 更新。
 *
 * 增强版 — 新增:
 * - Phase 8: error 事件增强 (ErrorDetail with category/suggestedAction)
 * - Phase 9: 工作流阶段 (workflowPhase/workflowProgress) + agent_partial_result
 * - Phase 13: 并行审查 (parallel_review_started / parallel_review_result)
 *
 * 支持多轮对话：
 * - 首次调用不传 sessionId，后端自动分配并通过 pipeline_started 返回
 * - 后续调用传入相同 sessionId，自动加载对话历史
 */

import { useCallback, useRef, useState } from 'react';
import { AgentSSEClient } from '../services/sse.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import type { CandidateType, FormFieldDef, AuditRuleDef, KnownValue } from '../types/scenario.ts';

// ── 调用参数类型 ──

export interface InvokeParams {
  action: string;
  businessType: string;
  userId?: string;
  sessionId?: string;
  userMessage?: string;
  planMode?: boolean;
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

/**
 * How long to wait (ms) after the stream opens without receiving *any*
 * SSE event before treating the connection as stale and timing out.
 */
const IDLE_TIMEOUT_MS = 60_000;

export function usePipeline() {
  const store = usePipelineStore();
  const clientRef = useRef<AgentSSEClient | null>(null);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isInvokingRef = useRef(false);

  // ── Retry / connection state exposed to UI ──
  const [retryCount, setRetryCount] = useState(0);

  /** Clear the idle-event timeout (if running). */
  const clearIdleTimer = useCallback(() => {
    if (idleTimerRef.current !== null) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  }, []);

  /** (Re-)start the idle-event timeout. Called every time we receive an SSE event. */
  const resetIdleTimer = useCallback(() => {
    clearIdleTimer();
    idleTimerRef.current = setTimeout(() => {
      // No event received within the window — treat as timeout.
      console.warn('[usePipeline] Idle timeout fired after', IDLE_TIMEOUT_MS, 'ms — no SSE events received');
      const state = usePipelineStore.getState();
      const hasResults =
        state.inferredType ||
        state.fieldValues.length > 0 ||
        state.auditSummary ||
        state.document;
      // Plan Mode: 有 plan 且 requiresApproval → 视为 plan_awaiting
      if (state.plan?.requiresApproval) {
        console.warn('[usePipeline] Idle timeout with requires_approval plan — treating as plan_awaiting');
        store.completePipeline('plan_awaiting_approval', Date.now() - (state.startedAt || Date.now()));
      } else if (hasResults) {
        console.warn('[usePipeline] Idle timeout but has results — treating as completed');
        store.completePipeline('success', Date.now() - (state.startedAt || Date.now()));
      } else {
        store.setError('连接超时：服务器在 60 秒内未返回任何事件');
      }
      clientRef.current?.close();
    }, IDLE_TIMEOUT_MS);
  }, [clearIdleTimer, store]);

  const invoke = useCallback(
    async (params: InvokeParams) => {
      // 防止并发 invoke (React Strict Mode 或重复触发)
      if (isInvokingRef.current) {
        console.warn('[usePipeline] invoke already in progress, skipping duplicate');
        return;
      }
      isInvokingRef.current = true;

      // 关闭之前的 SSE 连接 (如果有)
      if (clientRef.current) {
        clientRef.current.close();
        clientRef.current = null;
      }

      // 多轮对话：使用 softReset 保留 session 信息；首次调用用 reset
      const isFollowUp = !!params.sessionId && params.sessionId === store.sessionId;
      if (isFollowUp) {
        store.softReset();
      } else {
        store.reset();
      }
      setRetryCount(0);

      // 记录用户消息到对话历史
      if (params.userMessage) {
        store.addConversationTurn('user', params.userMessage);
      }

      // 设置 plan mode 状态
      const planMode = params.planMode ?? true;
      store.setPlanMode(planMode);

      const requestBody = {
        user_id: params.userId || 'U001',
        session_id: params.sessionId || store.sessionId || undefined,
        message: params.userMessage || `请帮我处理${params.action}`,
        business_type: params.action,
        plan_mode: planMode,
        context: {
          form_fields: params.formFields || [],
          audit_rules: params.auditRules || [],
          candidate_types: params.candidateTypes || [],
          known_values: params.knownValues || [],
          materials: params.materials || [],
        },
      };

      const client = new AgentSSEClient('/api/chat', requestBody, {
        maxRetries: 3,
        retryDelayMs: 1000,
        connectionTimeoutMs: 30_000,
        onRetry: (attempt, maxRetries, error) => {
          setRetryCount(attempt);
          store.addEvent({
            type: 'retry',
            data: {
              attempt,
              maxRetries,
              message: error.message,
            },
            timestamp: Date.now(),
          });
        },
      });
      clientRef.current = client;

      // ── Helper: reset idle timer on every dispatched event ──
      const touchIdleTimer = () => {
        resetIdleTimer();
      };

      // ── 注册 SSE 事件处理 ──

      client
        .on('pipeline_started', (data) => {
          touchIdleTimer();
          if (data.session_id) {
            store.setSessionId(data.session_id as string);
          }
          const businessType = (data.business_type as string) || (data.scenario as string) || '';
          store.startPipeline(businessType, []);
        })
        .on('agent_progress', (data) => {
          touchIdleTimer();
          const status = data.status as string;
          if (status === 'started') {
            store.setAgentIterationInfo(0, (data.max_iterations as number) || 15);
          } else if (status === 'calling_tools') {
            store.setAgentIterationInfo(
              (data.iteration as number) || 0,
              store.agentIteration?.max || 15,
            );
            const tools = data.tools as string[] | undefined;
            if (tools && tools.length > 0) {
              store.setCallingTools(tools);
            }
          } else if (status === 'completed' || status === 'max_iterations_reached') {
            store.setAgentIterationInfo(
              (data.iterations as number) || 0,
              store.agentIteration?.max || 15,
            );
            store.setCallingTools([]);
          }

          // Phase 9: 工作流阶段跟踪
          if (data.phase) {
            store.setWorkflowPhase(
              data.phase as string,
              (data.progress as number) || 0,
            );
          }

          store.updateStepProgress(data);
          store.addEvent({
            type: 'agent_progress',
            data,
            timestamp: Date.now(),
          });
        })
        .on('type_inferred', (data) => {
          touchIdleTimer();
          store.setInferredType({
            docType: data.doc_type as string,
            confidence: data.confidence as number,
            reasoning: data.reasoning as string,
          });
          store.addEvent({
            type: 'type_inferred',
            data,
            timestamp: Date.now(),
          });
        })
        .on('field_update', (data) => {
          touchIdleTimer();
          store.addFieldValue({
            fieldId: data.field_id as string,
            value: data.value,
            source: data.source as string,
            confidence: data.confidence as number,
          });
          store.addEvent({
            type: 'field_update',
            data,
            timestamp: Date.now(),
          });
        })
        .on('audit_result', (data) => {
          touchIdleTimer();
          const rawResults =
            (data.results as Array<Record<string, unknown>>) || [];
          store.setAuditSummary({
            results: rawResults.map((r) => ({
              ruleId: (r.ruleId as string) || (r.rule_id as string) || '',
              status: ((r.status as string) || 'pass') as
                | 'pass'
                | 'fail'
                | 'warning',
              message: (r.message as string) || '',
            })),
            passCount: (data.pass_count as number) || 0,
            failCount: (data.fail_count as number) || 0,
            warningCount: (data.warning_count as number) || 0,
            conclusion: (data.conclusion as string) || '',
          });
          store.addEvent({
            type: 'audit_result',
            data,
            timestamp: Date.now(),
          });
        })
        .on('document_ready', (data) => {
          touchIdleTimer();
          const docMeta: Record<string, unknown> = (data.metadata as Record<string, unknown>) || {};
          // 将 docx 下载信息合并到 metadata
          if (data.docx_download_url) docMeta.docx_download_url = data.docx_download_url;
          if (data.docx_filename) docMeta.docx_filename = data.docx_filename;
          if (data.docx_file_id) docMeta.docx_file_id = data.docx_file_id;
          store.setDocument({
            documentType: data.document_type as string,
            title: data.title as string,
            content: data.content as string,
            metadata: docMeta,
          });
          store.addEvent({
            type: 'document_ready',
            data,
            timestamp: Date.now(),
          });
        })
        .on('agent_message', (data) => {
          touchIdleTimer();
          store.setAgentMessage(data.content as string);
          store.setIsStreaming(false);
          store.addEvent({
            type: 'agent_message',
            data,
            timestamp: Date.now(),
          });
        })
        .on('text_delta', (data) => {
          touchIdleTimer();
          const text = data.content as string;
          if (text) {
            store.appendStreamingText(text);
          }
        })
        .on('thinking', (data) => {
          touchIdleTimer();
          const text = data.content as string;
          if (text) {
            store.appendThinkingText(text);
          }
        })
        .on('thinking_complete', () => {
          touchIdleTimer();
        })
        .on('plan_proposed', (data) => {
          touchIdleTimer();
          store.setAgentPlanProposed(true);
          let rawSteps = data.steps;
          // LLM 可能把 steps 序列化成 JSON 字符串而非数组
          if (typeof rawSteps === 'string') {
            try { rawSteps = JSON.parse(rawSteps); } catch { rawSteps = []; }
          }
          const safeSteps = Array.isArray(rawSteps)
            ? rawSteps.map((s: unknown, i: number) => {
                if (typeof s === 'string') return { step: i + 1, description: s };
                if (s && typeof s === 'object') {
                  const obj = s as Record<string, unknown>;
                  return {
                    step: (obj.step as number) || i + 1,
                    description: (obj.description as string) || (obj.action as string) || JSON.stringify(s),
                    tools: obj.tools as string[] | undefined,
                  };
                }
                return { step: i + 1, description: String(s) };
              })
            : [];
          store.setPlan({
            summary: (data.summary as string) || '',
            detail: (data.detail as string) || '',
            steps: safeSteps,
            estimatedActions: (data.estimated_actions as number) || 0,
            requiresApproval: !!(data.requires_approval),
          });
          // plan step tracking: 仅 cowork 模式 (不需要确认) 立即初始化 todo list
          // requires_approval=true 时等 EXECUTE 模式再初始化
          if (!data.requires_approval) {
            store.initPlanSteps(safeSteps);
          }
          store.addEvent({
            type: 'plan_proposed',
            data,
            timestamp: Date.now(),
          });
        })
        .on('skill_created', (data) => {
          touchIdleTimer();
          store.addEvent({
            type: 'skill_created',
            data,
            timestamp: Date.now(),
          });
        })
        .on('skill_updated', (data) => {
          touchIdleTimer();
          store.addEvent({
            type: 'skill_updated',
            data,
            timestamp: Date.now(),
          });
        })
        .on('pipeline_complete', (data) => {
          touchIdleTimer();
          // Phase 21: 仅执行完成时标记所有步骤完成 (plan_awaiting 时不标记)
          const pipelineStatus = data.status as string;
          if (pipelineStatus !== 'plan_awaiting_approval') {
            store.completePlanSteps();
          }
          store.completePipeline(
            data.status as string,
            (data.duration_ms as number) || 0,
          );
          store.addConversationTurn('assistant', '处理完成');
          store.addEvent({
            type: 'pipeline_complete',
            data,
            timestamp: Date.now(),
          });
        })
        .on('heartbeat', () => {
          touchIdleTimer();
        })
        .on('keepalive', () => {
          touchIdleTimer();
        })
        .on('tool_executed', (data) => {
          touchIdleTimer();
          const toolName = (data.tool as string) || 'unknown';
          store.addToolExecution({
            id: `tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            toolName,
            success: (data.success as boolean) ?? true,
            latencyMs: (data.latency_ms as number) || 0,
            timestamp: Date.now(),
            argsSummary: data.args_summary as Record<string, string> | undefined,
            resultSummary: data.result_summary as string | undefined,
            blocked: data.blocked as boolean | undefined,
          });
          store.addEvent({
            type: 'tool_executed',
            data,
            timestamp: Date.now(),
          });
        })
        // ── EXECUTE 模式: 后端推送 plan steps 初始化 todo list ──
        .on('plan_steps_init', (data) => {
          touchIdleTimer();
          let rawSteps = data.steps;
          if (typeof rawSteps === 'string') {
            try { rawSteps = JSON.parse(rawSteps); } catch { rawSteps = []; }
          }
          const safeSteps = Array.isArray(rawSteps)
            ? rawSteps.map((s: unknown, i: number) => {
                if (typeof s === 'string') return { step: i + 1, description: s };
                if (s && typeof s === 'object') {
                  const obj = s as Record<string, unknown>;
                  return {
                    step: (obj.step as number) || i + 1,
                    description: (obj.description as string) || (obj.action as string) || JSON.stringify(s),
                  };
                }
                return { step: i + 1, description: String(s) };
              })
            : [];
          store.initPlanSteps(safeSteps);
        })
        // ── 后端驱动 plan step 推进 ──
        .on('step_started', (data) => {
          touchIdleTimer();
          store.startPlanStep(data.step_index as number);
        })
        .on('step_completed', (data) => {
          touchIdleTimer();
          store.completePlanStep(data.step_index as number, data.duration_ms as number | undefined);
        })
        .on('step_failed', (data) => {
          touchIdleTimer();
          store.failPlanStep(data.step_index as number);
        })
        .on('browser_action', (data) => {
          touchIdleTimer();
          store.addEvent({ type: 'browser_action', data, timestamp: Date.now() });
        })
        .on('browser_screenshot', (data) => {
          touchIdleTimer();
          store.addEvent({ type: 'browser_screenshot', data, timestamp: Date.now() });
        })

        // ── Phase 8: 增强错误处理 ──
        .on('error', (data) => {
          touchIdleTimer();
          store.setError((data.message as string) || 'Unknown error');
          // Phase 8: 设置结构化错误详情
          store.setErrorDetail({
            message: (data.message as string) || '',
            category: (data.category as string) || 'internal',
            affectedStep: (data.affected_step as string) || '',
            suggestedAction: (data.suggested_action as string) || '',
            traceId: (data.trace_id as string) || '',
          });
          store.addEvent({ type: 'error', data, timestamp: Date.now() });
        })

        // ── Phase 9: 部分结果 (工作流中途失败) ──
        .on('agent_partial_result', (data) => {
          touchIdleTimer();
          store.setError(`部分完成: ${(data.error as string) || '工作流中途异常'}`);
          store.setErrorDetail({
            message: (data.error as string) || '工作流中途异常',
            category: 'partial_failure',
            affectedStep: (data.failed_step as string) || '',
            suggestedAction: (data.suggested_action as string) || '可保留已完成步骤的结果，手动处理未完成部分',
            traceId: (data.trace_id as string) || '',
          });
          store.addEvent({
            type: 'agent_partial_result',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 13: 并行审查开始 ──
        .on('parallel_review_started', (data) => {
          touchIdleTimer();
          store.setParallelReview({
            roles: (data.roles as string[]) || [],
            status: 'running',
            overallStatus: '',
            overallConfidence: 0,
            results: [],
            durationMs: 0,
          });
          store.addEvent({
            type: 'parallel_review_started',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 13: 并行审查结果 ──
        .on('parallel_review_result', (data) => {
          touchIdleTimer();
          store.setParallelReview({
            roles: (data.roles as string[]) || [],
            status: 'completed',
            overallStatus: (data.overall_status as string) || '',
            overallConfidence: (data.overall_confidence as number) || 0,
            results: ((data.individual_results as Array<Record<string, unknown>>) || []).map((r) => ({
              agentRole: (r.agent_role as string) || (r.agentRole as string) || '',
              conclusion: (r.conclusion as string) || '',
              confidence: (r.confidence as number) || 0,
              details: (r.details as string) || '',
              durationMs: (r.duration_ms as number) || (r.durationMs as number) || 0,
            })),
            durationMs: (data.duration_ms as number) || 0,
          });
          store.addEvent({
            type: 'parallel_review_result',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 24: Agent 交互请求 ──
        .on('request_upload', (data) => {
          touchIdleTimer();
          store.setPendingInteraction({
            type: 'upload',
            prompt: (data.prompt as string) || '请上传文件',
            accept: (data.accept as string) || '*',
          });
          store.addEvent({ type: 'request_upload', data, timestamp: Date.now() });
        })
        .on('request_confirmation', (data) => {
          touchIdleTimer();
          const rawOptions = (data.options as Array<Record<string, string>>) || [];
          store.setPendingInteraction({
            type: 'confirmation',
            message: (data.message as string) || '请确认',
            options: rawOptions.map((o) => ({
              label: o.label || o.value || '',
              value: o.value || o.label || '',
            })),
          });
          store.addEvent({ type: 'request_confirmation', data, timestamp: Date.now() });
        })
        .on('request_input', (data) => {
          touchIdleTimer();
          store.setPendingInteraction({
            type: 'input',
            prompt: (data.prompt as string) || '请输入',
            fieldType: (data.field_type as string) || 'text',
          });
          store.addEvent({ type: 'request_input', data, timestamp: Date.now() });
        });

      // Start the idle timer before connecting.
      resetIdleTimer();

      try {
        await client.connect();
      } finally {
        clearIdleTimer();
        setRetryCount(0);

        // ── 兜底: SSE 流结束但 store 仍在 running 状态 ──
        const currentStatus = usePipelineStore.getState().status;
        if (currentStatus === 'running') {
          const state = usePipelineStore.getState();
          const hasResults =
            state.inferredType ||
            state.fieldValues.length > 0 ||
            state.auditSummary ||
            state.document;

          if (state.plan?.requiresApproval) {
            console.warn('[usePipeline] Stream ended with requires_approval plan — marking as plan_awaiting');
            store.completePipeline('plan_awaiting_approval', Date.now() - (state.startedAt || Date.now()));
          } else if (hasResults) {
            console.warn('[usePipeline] Stream ended without pipeline_complete, but has results — marking as completed');
            store.completePipeline('success', Date.now() - (state.startedAt || Date.now()));
          } else {
            console.warn('[usePipeline] Stream ended without pipeline_complete and no results — marking as failed');
            store.setError('连接已断开，未收到完整结果');
          }
        }

        isInvokingRef.current = false;
      }
    },
    [store, resetIdleTimer, clearIdleTimer],
  );

  const cancel = useCallback(() => {
    clearIdleTimer();
    clientRef.current?.close();
    setRetryCount(0);
  }, [clearIdleTimer]);

  return {
    invoke,
    cancel,
    // Expose all store state for component consumption
    status: store.status,
    scenario: store.scenario,
    traceId: store.traceId,
    sessionId: store.sessionId,
    conversationHistory: store.conversationHistory,
    plan: store.plan,
    planMode: store.planMode,
    steps: store.steps,
    currentStep: store.currentStep,
    inferredType: store.inferredType,
    fieldValues: store.fieldValues,
    auditSummary: store.auditSummary,
    document: store.document,
    startedAt: store.startedAt,
    completedAt: store.completedAt,
    durationMs: store.durationMs,
    eventLog: store.eventLog,
    error: store.error,
    // Phase 8
    errorDetail: store.errorDetail,
    // Phase 9
    workflowPhase: store.workflowPhase,
    workflowProgress: store.workflowProgress,
    // Phase 13
    parallelReview: store.parallelReview,
  };
}
