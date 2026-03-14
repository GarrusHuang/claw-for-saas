/**
 * Pipeline 事件分发器 — 将后端事件路由到 Pipeline Store。
 *
 * 共用于:
 * - WebSocket pipeline_event 路由 (useNotifications)
 * - 直接调用 (usePipeline fallback)
 */

import { usePipelineStore } from '../stores/pipeline.ts';
import type { PipelineSnapshot } from './ai-api.ts';

// ── 模块级开关：快照应用期间暂停实时事件分发 ──
let _replayPending = false;
export function setReplayPending(v: boolean): void { _replayPending = v; }

/**
 * 分发单个 pipeline 事件到 store。
 */
export function dispatchPipelineEvent(
  eventType: string,
  data: Record<string, unknown>,
): void {
  if (_replayPending) return;

  const store = usePipelineStore.getState();

  switch (eventType) {
    case 'pipeline_started':
      if (data.session_id) {
        store.setSessionId(data.session_id as string);
      }
      store.startPipeline(
        (data.business_type as string) || (data.scenario as string) || '',
        [],
      );
      break;

    case 'skills_loaded':
      store.setLoadedSkills((data.skills as string[]) || []);
      store.addEvent({ type: 'skills_loaded', data, timestamp: Date.now() });
      break;

    case 'agent_progress': {
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
      if (data.phase) {
        store.setWorkflowPhase(data.phase as string, (data.progress as number) || 0);
      }
      store.updateStepProgress(data);
      store.addEvent({ type: 'agent_progress', data, timestamp: Date.now() });
      break;
    }

    case 'type_inferred':
      store.setInferredType({
        docType: data.doc_type as string,
        confidence: data.confidence as number,
        reasoning: data.reasoning as string,
      });
      store.addEvent({ type: 'type_inferred', data, timestamp: Date.now() });
      break;

    case 'field_update':
      store.addFieldValue({
        fieldId: data.field_id as string,
        value: data.value,
        source: data.source as string,
        confidence: data.confidence as number,
      });
      store.addEvent({ type: 'field_update', data, timestamp: Date.now() });
      break;

    case 'audit_result': {
      const rawResults = (data.results as Array<Record<string, unknown>>) || [];
      store.setAuditSummary({
        results: rawResults.map((r) => ({
          ruleId: (r.ruleId as string) || (r.rule_id as string) || '',
          status: ((r.status as string) || 'pass') as 'pass' | 'fail' | 'warning',
          message: (r.message as string) || '',
        })),
        passCount: (data.pass_count as number) || 0,
        failCount: (data.fail_count as number) || 0,
        warningCount: (data.warning_count as number) || 0,
        conclusion: (data.conclusion as string) || '',
      });
      store.addEvent({ type: 'audit_result', data, timestamp: Date.now() });
      break;
    }

    case 'document_ready': {
      const docMeta: Record<string, unknown> = (data.metadata as Record<string, unknown>) || {};
      if (data.docx_download_url) docMeta.docx_download_url = data.docx_download_url;
      if (data.docx_filename) docMeta.docx_filename = data.docx_filename;
      if (data.docx_file_id) docMeta.docx_file_id = data.docx_file_id;
      store.setDocument({
        documentType: data.document_type as string,
        title: data.title as string,
        content: data.content as string,
        metadata: docMeta,
      });
      store.addEvent({ type: 'document_ready', data, timestamp: Date.now() });
      break;
    }

    case 'agent_message':
      store.setAgentMessage(data.content as string);
      store.setIsStreaming(false);
      store.addEvent({ type: 'agent_message', data, timestamp: Date.now() });
      break;

    case 'text_delta': {
      const text = data.content as string;
      if (text) {
        store.appendStreamingText(text);
        store.appendTextToTimeline(text, data.iteration as number);
      }
      break;
    }

    case 'thinking': {
      const thinkText = data.content as string;
      if (thinkText) {
        store.appendThinkingText(thinkText, data.iteration as number);
      }
      break;
    }

    case 'thinking_complete':
      break;

    case 'plan_proposed': {
      store.setAgentPlanProposed(true);
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
      });
      store.initPlanSteps(safeSteps);
      store.addEvent({ type: 'plan_proposed', data, timestamp: Date.now() });
      break;
    }

    case 'skill_created':
    case 'skill_updated':
      store.addEvent({ type: eventType, data, timestamp: Date.now() });
      break;

    case 'pipeline_complete':
      store.completePlanSteps();
      store.completePipeline(data.status as string, (data.duration_ms as number) || 0);
      store.addConversationTurn('assistant', '处理完成');
      store.addEvent({ type: 'pipeline_complete', data, timestamp: Date.now() });
      break;

    case 'heartbeat':
    case 'keepalive':
      break;

    case 'tool_executed': {
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
      store.addEvent({ type: 'tool_executed', data, timestamp: Date.now() });
      break;
    }

    case 'plan_steps_init': {
      let rawSteps2 = data.steps;
      if (typeof rawSteps2 === 'string') {
        try { rawSteps2 = JSON.parse(rawSteps2); } catch { rawSteps2 = []; }
      }
      const safeSteps2 = Array.isArray(rawSteps2)
        ? rawSteps2.map((s: unknown, i: number) => {
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
      store.initPlanSteps(safeSteps2);
      break;
    }

    case 'step_started':
      store.startPlanStep(data.step_index as number);
      break;

    case 'step_completed':
      store.completePlanStep(data.step_index as number);
      break;

    case 'step_failed':
      store.failPlanStep(data.step_index as number);
      break;

    case 'browser_action':
    case 'browser_screenshot':
      store.addEvent({ type: eventType, data, timestamp: Date.now() });
      break;

    case 'file_artifact':
      store.addFileArtifact({
        path: (data.path as string) || '',
        filename: (data.filename as string) || '',
        sizeBytes: (data.size_bytes as number) || 0,
        contentType: (data.content_type as string) || 'application/octet-stream',
        sessionId: (data.session_id as string) || '',
      });
      store.addEvent({ type: 'file_artifact', data, timestamp: Date.now() });
      break;

    case 'error':
      store.setError((data.message as string) || 'Unknown error');
      store.setErrorDetail({
        message: (data.message as string) || '',
        category: (data.category as string) || 'internal',
        affectedStep: (data.affected_step as string) || '',
        suggestedAction: (data.suggested_action as string) || '',
        traceId: (data.trace_id as string) || '',
      });
      store.addEvent({ type: 'error', data, timestamp: Date.now() });
      break;

    case 'agent_partial_result':
      store.setError(`部分完成: ${(data.error as string) || '工作流中途异常'}`);
      store.setErrorDetail({
        message: (data.error as string) || '工作流中途异常',
        category: 'partial_failure',
        affectedStep: (data.failed_step as string) || '',
        suggestedAction: (data.suggested_action as string) || '可保留已完成步骤的结果，手动处理未完成部分',
        traceId: (data.trace_id as string) || '',
      });
      store.addEvent({ type: 'agent_partial_result', data, timestamp: Date.now() });
      break;

    case 'parallel_review_started':
      store.setParallelReview({
        roles: (data.roles as string[]) || [],
        status: 'running',
        overallStatus: '',
        overallConfidence: 0,
        results: [],
        durationMs: 0,
      });
      store.addEvent({ type: 'parallel_review_started', data, timestamp: Date.now() });
      break;

    case 'parallel_review_result':
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
      store.addEvent({ type: 'parallel_review_result', data, timestamp: Date.now() });
      break;

    case 'request_upload':
      store.setPendingInteraction({
        type: 'upload',
        prompt: (data.prompt as string) || '请上传文件',
        accept: (data.accept as string) || '*',
      });
      store.addEvent({ type: 'request_upload', data, timestamp: Date.now() });
      break;

    case 'request_confirmation': {
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
      break;
    }

    case 'request_input':
      store.setPendingInteraction({
        type: 'input',
        prompt: (data.prompt as string) || '请输入',
        fieldType: (data.field_type as string) || 'text',
      });
      store.addEvent({ type: 'request_input', data, timestamp: Date.now() });
      break;

    default:
      // Unknown event type — log for debugging
      console.debug('[pipeline-dispatcher] Unknown event:', eventType, data);
      break;
  }
}

/**
 * 将后端快照应用到 pipeline store。
 *
 * 最小化原则：只恢复真正丢失的数据 (streamingText + status)。
 * 其他状态 (toolExecutions, timeline, planSteps, loadedSkills 等)
 * 由 API 历史 + WS 增量事件提供，和首次进入完全一致。
 */
export function applyPipelineSnapshot(snapshot: PipelineSnapshot): void {
  if (snapshot.is_complete) {
    // pipeline 已结束：标记完成，不覆盖其他状态
    usePipelineStore.getState().completePipeline(
      snapshot.error ? 'failed' : 'success', 0,
    );
    return;
  }

  // pipeline 运行中：只恢复流式文本
  // 不设 status、不动 toolExecutions/timelineEntries，
  // 让 WS 事件自然驱动，和首次进入效果完全一致。
  const updates: Record<string, unknown> = {};

  // 恢复流式文本（F5/切走期间丢失的核心内容）
  if (snapshot.streaming_text) {
    updates.streamingText = snapshot.streaming_text;
    updates.isStreaming = true;
  }

  // 恢复 agent 最终回复（如果有）
  if (snapshot.agent_message) {
    updates.agentMessage = snapshot.agent_message;
  }

  // 恢复错误状态
  if (snapshot.error) {
    updates.error = snapshot.error;
  }

  usePipelineStore.setState(updates);
}
