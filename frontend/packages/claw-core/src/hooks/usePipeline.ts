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
import { getAIConfig } from '../config.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
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

/**
 * How long to wait (ms) after the stream opens without receiving *any*
 * SSE event before treating the connection as stale and timing out.
 */
const IDLE_TIMEOUT_MS = 60_000;

export function usePipeline() {
  // ── 细粒度 selectors (避免整 store 订阅导致不必要的重渲染) ──
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
      if (hasResults) {
        console.warn('[usePipeline] Idle timeout but has results — treating as completed');
        usePipelineStore.getState().completePipeline('success', Date.now() - (state.startedAt || Date.now()));
      } else {
        usePipelineStore.getState().setError('连接超时：服务器在 60 秒内未返回任何事件');
      }
      clientRef.current?.close();
    }, IDLE_TIMEOUT_MS);
  }, [clearIdleTimer]);

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
      const isFollowUp = !!params.sessionId && params.sessionId === usePipelineStore.getState().sessionId;
      if (isFollowUp) {
        usePipelineStore.getState().softReset();
      } else {
        usePipelineStore.getState().reset();
      }
      setRetryCount(0);

      // 记录用户消息到对话历史
      if (params.userMessage) {
        usePipelineStore.getState().addConversationTurn('user', params.userMessage);
      }

      const requestBody = {
        user_id: params.userId || getAIConfig().defaultUserId,
        session_id: params.sessionId || usePipelineStore.getState().sessionId || undefined,
        message: params.userMessage || `请帮我处理${params.action}`,
        business_type: params.action,
        materials: params.materials || [],
      };

      const client = new AgentSSEClient('/api/chat', requestBody, {
        maxRetries: 3,
        retryDelayMs: 1000,
        connectionTimeoutMs: 30_000,
        onRetry: (attempt, maxRetries, error) => {
          setRetryCount(attempt);
          usePipelineStore.getState().addEvent({
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
            usePipelineStore.getState().setSessionId(data.session_id as string);
          }
          const businessType = (data.business_type as string) || (data.scenario as string) || '';
          usePipelineStore.getState().startPipeline(businessType, []);
        })
        .on('agent_progress', (data) => {
          touchIdleTimer();
          const status = data.status as string;
          if (status === 'started') {
            usePipelineStore.getState().setAgentIterationInfo(0, (data.max_iterations as number) || 15);
          } else if (status === 'calling_tools') {
            usePipelineStore.getState().setAgentIterationInfo(
              (data.iteration as number) || 0,
              usePipelineStore.getState().agentIteration?.max || 15,
            );
            const tools = data.tools as string[] | undefined;
            if (tools && tools.length > 0) {
              usePipelineStore.getState().setCallingTools(tools);
            }
          } else if (status === 'completed' || status === 'max_iterations_reached') {
            usePipelineStore.getState().setAgentIterationInfo(
              (data.iterations as number) || 0,
              usePipelineStore.getState().agentIteration?.max || 15,
            );
            usePipelineStore.getState().setCallingTools([]);
          }

          // Phase 9: 工作流阶段跟踪
          if (data.phase) {
            usePipelineStore.getState().setWorkflowPhase(
              data.phase as string,
              (data.progress as number) || 0,
            );
          }

          usePipelineStore.getState().updateStepProgress(data);
          usePipelineStore.getState().addEvent({
            type: 'agent_progress',
            data,
            timestamp: Date.now(),
          });
        })
        .on('type_inferred', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setInferredType({
            docType: data.doc_type as string,
            confidence: data.confidence as number,
            reasoning: data.reasoning as string,
          });
          usePipelineStore.getState().addEvent({
            type: 'type_inferred',
            data,
            timestamp: Date.now(),
          });
        })
        .on('field_update', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().addFieldValue({
            fieldId: data.field_id as string,
            value: data.value,
            source: data.source as string,
            confidence: data.confidence as number,
          });
          usePipelineStore.getState().addEvent({
            type: 'field_update',
            data,
            timestamp: Date.now(),
          });
        })
        .on('audit_result', (data) => {
          touchIdleTimer();
          const rawResults =
            (data.results as Array<Record<string, unknown>>) || [];
          usePipelineStore.getState().setAuditSummary({
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
          usePipelineStore.getState().addEvent({
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
          usePipelineStore.getState().setDocument({
            documentType: data.document_type as string,
            title: data.title as string,
            content: data.content as string,
            metadata: docMeta,
          });
          usePipelineStore.getState().addEvent({
            type: 'document_ready',
            data,
            timestamp: Date.now(),
          });
        })
        .on('agent_message', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setAgentMessage(data.content as string);
          usePipelineStore.getState().setIsStreaming(false);
          usePipelineStore.getState().addEvent({
            type: 'agent_message',
            data,
            timestamp: Date.now(),
          });
        })
        .on('text_delta', (data) => {
          touchIdleTimer();
          const text = data.content as string;
          if (text) {
            usePipelineStore.getState().appendStreamingText(text);
          }
        })
        .on('thinking', (data) => {
          touchIdleTimer();
          const text = data.content as string;
          if (text) {
            usePipelineStore.getState().appendThinkingText(text);
          }
        })
        .on('thinking_complete', () => {
          touchIdleTimer();
        })
        .on('plan_proposed', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setAgentPlanProposed(true);
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
          usePipelineStore.getState().setPlan({
            summary: (data.summary as string) || '',
            detail: (data.detail as string) || '',
            steps: safeSteps,
            estimatedActions: (data.estimated_actions as number) || 0,
          });
          usePipelineStore.getState().initPlanSteps(safeSteps);
          usePipelineStore.getState().addEvent({
            type: 'plan_proposed',
            data,
            timestamp: Date.now(),
          });
        })
        .on('skill_created', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().addEvent({
            type: 'skill_created',
            data,
            timestamp: Date.now(),
          });
        })
        .on('skill_updated', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().addEvent({
            type: 'skill_updated',
            data,
            timestamp: Date.now(),
          });
        })
        .on('pipeline_complete', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().completePlanSteps();
          usePipelineStore.getState().completePipeline(
            data.status as string,
            (data.duration_ms as number) || 0,
          );
          usePipelineStore.getState().addConversationTurn('assistant', '处理完成');
          usePipelineStore.getState().addEvent({
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
          usePipelineStore.getState().addToolExecution({
            id: `tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            toolName,
            success: (data.success as boolean) ?? true,
            latencyMs: (data.latency_ms as number) || 0,
            timestamp: Date.now(),
            argsSummary: data.args_summary as Record<string, string> | undefined,
            resultSummary: data.result_summary as string | undefined,
            blocked: data.blocked as boolean | undefined,
          });
          usePipelineStore.getState().addEvent({
            type: 'tool_executed',
            data,
            timestamp: Date.now(),
          });
        })
        // ── 后端推送 plan steps 初始化 todo list ──
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
          usePipelineStore.getState().initPlanSteps(safeSteps);
        })
        // ── 后端驱动 plan step 推进 ──
        .on('step_started', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().startPlanStep(data.step_index as number);
        })
        .on('step_completed', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().completePlanStep(data.step_index as number, data.duration_ms as number | undefined);
        })
        .on('step_failed', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().failPlanStep(data.step_index as number);
        })
        .on('browser_action', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().addEvent({ type: 'browser_action', data, timestamp: Date.now() });
        })
        .on('browser_screenshot', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().addEvent({ type: 'browser_screenshot', data, timestamp: Date.now() });
        })

        // ── Phase 8: 增强错误处理 ──
        .on('error', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setError((data.message as string) || 'Unknown error');
          // Phase 8: 设置结构化错误详情
          usePipelineStore.getState().setErrorDetail({
            message: (data.message as string) || '',
            category: (data.category as string) || 'internal',
            affectedStep: (data.affected_step as string) || '',
            suggestedAction: (data.suggested_action as string) || '',
            traceId: (data.trace_id as string) || '',
          });
          usePipelineStore.getState().addEvent({ type: 'error', data, timestamp: Date.now() });
        })

        // ── Phase 9: 部分结果 (工作流中途失败) ──
        .on('agent_partial_result', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setError(`部分完成: ${(data.error as string) || '工作流中途异常'}`);
          usePipelineStore.getState().setErrorDetail({
            message: (data.error as string) || '工作流中途异常',
            category: 'partial_failure',
            affectedStep: (data.failed_step as string) || '',
            suggestedAction: (data.suggested_action as string) || '可保留已完成步骤的结果，手动处理未完成部分',
            traceId: (data.trace_id as string) || '',
          });
          usePipelineStore.getState().addEvent({
            type: 'agent_partial_result',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 13: 并行审查开始 ──
        .on('parallel_review_started', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setParallelReview({
            roles: (data.roles as string[]) || [],
            status: 'running',
            overallStatus: '',
            overallConfidence: 0,
            results: [],
            durationMs: 0,
          });
          usePipelineStore.getState().addEvent({
            type: 'parallel_review_started',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 13: 并行审查结果 ──
        .on('parallel_review_result', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setParallelReview({
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
          usePipelineStore.getState().addEvent({
            type: 'parallel_review_result',
            data,
            timestamp: Date.now(),
          });
        })

        // ── Phase 24: Agent 交互请求 ──
        .on('request_upload', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setPendingInteraction({
            type: 'upload',
            prompt: (data.prompt as string) || '请上传文件',
            accept: (data.accept as string) || '*',
          });
          usePipelineStore.getState().addEvent({ type: 'request_upload', data, timestamp: Date.now() });
        })
        .on('request_confirmation', (data) => {
          touchIdleTimer();
          const rawOptions = (data.options as Array<Record<string, string>>) || [];
          usePipelineStore.getState().setPendingInteraction({
            type: 'confirmation',
            message: (data.message as string) || '请确认',
            options: rawOptions.map((o) => ({
              label: o.label || o.value || '',
              value: o.value || o.label || '',
            })),
          });
          usePipelineStore.getState().addEvent({ type: 'request_confirmation', data, timestamp: Date.now() });
        })
        .on('request_input', (data) => {
          touchIdleTimer();
          usePipelineStore.getState().setPendingInteraction({
            type: 'input',
            prompt: (data.prompt as string) || '请输入',
            fieldType: (data.field_type as string) || 'text',
          });
          usePipelineStore.getState().addEvent({ type: 'request_input', data, timestamp: Date.now() });
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

          if (hasResults) {
            console.warn('[usePipeline] Stream ended without pipeline_complete, but has results — marking as completed');
            usePipelineStore.getState().completePipeline('success', Date.now() - (state.startedAt || Date.now()));
          } else {
            console.warn('[usePipeline] Stream ended without pipeline_complete and no results — marking as failed');
            usePipelineStore.getState().setError('连接已断开，未收到完整结果');
          }
        }

        isInvokingRef.current = false;
      }
    },
    [resetIdleTimer, clearIdleTimer],
  );

  const cancel = useCallback(() => {
    clearIdleTimer();
    clientRef.current?.close();
    setRetryCount(0);
  }, [clearIdleTimer]);

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
