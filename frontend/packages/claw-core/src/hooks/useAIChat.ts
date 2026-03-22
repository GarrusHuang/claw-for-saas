/**
 * useAIChat — 对话框专用 Hook (解耦版)。
 *
 * 组合 useChatMessages + useSessionManager，增加:
 * - Pipeline dispatch (sendMessage)
 * - 场景选择 (selectScenario)
 * - 自动启动 (auto-start)
 * - 完成转场 (completion transition)
 *
 * 返回签名不变，AIChatDialog.tsx 无需改动。
 */

import { useCallback, useEffect, useRef } from 'react';
import { getAIConfig } from '../config.ts';
import { useAIChatStore } from '../stores/ai-chat.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import { usePipeline } from './usePipeline.ts';
import { useChatMessages } from './useChatMessages.ts';
import { useSessionManager } from './useSessionManager.ts';
import { injectMessage, bindFilesToSession } from '../services/ai-api.ts';
import { scheduleSessionCleanup } from '../stores/pipeline-cache.ts';
import type { ScenarioConfig } from '../types/scenario.ts';

/** 时间线条目 (持久化到 session，加载时恢复) */
export interface ChatTimelineEntry {
  type: 'thinking' | 'tool' | 'text';
  content?: string;
  iteration?: number;
  tool_name?: string;
  success?: boolean;
  blocked?: boolean;
  latency_ms?: number;
  args_summary?: Record<string, string>;
  result_summary?: string;
  ts: number;
}

/** 消息附件文件 */
export interface ChatMessageFile {
  fileId: string;
  filename: string;
  contentType?: string;
  sizeBytes?: number;
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  /** 该消息关联的时间线 (thinking + tool 记录) */
  timeline?: ChatTimelineEntry[];
  /** 用户消息附带的文件 */
  files?: ChatMessageFile[];
  /** Agent 生成的文件制品 */
  fileArtifacts?: Array<{ path: string; filename: string; sizeBytes: number; contentType: string; sessionId: string }>;
}

/**
 * useAIChat — 对话框专用 Hook。
 */
export function useAIChat() {
  const pipeline = usePipeline();
  const pipelineRef = useRef(pipeline);
  pipelineRef.current = pipeline;
  const activeScenario = useAIChatStore((s) => s.activeScenario);
  const setChatDialogState = useAIChatStore((s) => s.setChatDialogState);
  const setActiveScenario = useAIChatStore((s) => s.setActiveScenario);
  const pipelineStatus = usePipelineStore((s) => s.status);
  const plan = usePipelineStore((s) => s.plan);
  const isStreaming = usePipelineStore((s) => s.isStreaming);

  // ── 子 Hook: 消息状态 + streaming ──
  const { messages, setMessages, addMessage, streamingMsgIdRef, prevAgentMessageRef } = useChatMessages();

  // ── 子 Hook: Session 管理 ──
  const { sessions, fetchSessions, autoStartedRef } = useSessionManager({
    messages,
    setMessages,
    streamingMsgIdRef,
    prevAgentMessageRef,
  });

  const prevStatusRef = useRef(pipelineStatus);

  /** 获取当前场景配置 */
  const scenarioConfig: ScenarioConfig | null =
    activeScenario ? getAIConfig().scenarios[activeScenario] || null : null;

  /** 发送用户消息并调用 Pipeline */
  const sendMessage = useCallback(
    async (text: string, scenario?: string, files?: { fileId: string; filename: string }[]) => {
      // If pipeline is running, inject message to backend in real-time
      if (usePipelineStore.getState().status === 'running') {
        const currentSessionId = usePipelineStore.getState().sessionId;
        const msgFiles = files?.map(f => ({
          fileId: f.fileId,
          filename: f.filename,
          contentType: (f as { contentType?: string }).contentType,
          sizeBytes: (f as { sizeBytes?: number }).sizeBytes,
        }));
        addMessage('user', text, msgFiles);
        if (currentSessionId) {
          injectMessage(currentSessionId, text, files).catch((err) => {
            console.warn('[useAIChat] Failed to inject message:', err);
          });
        }
        return;
      }

      const scenarioKey = scenario || activeScenario;
      const scenarios = getAIConfig().scenarios;

      // 转换附件信息
      const msgFiles: ChatMessageFile[] | undefined = files?.map((f) => ({
        fileId: f.fileId,
        filename: f.filename,
        contentType: (f as { contentType?: string }).contentType,
        sizeBytes: (f as { sizeBytes?: number }).sizeBytes,
      }));

      // ── 自由对话 (无场景) ──
      if (!scenarioKey) {
        addMessage('user', text, msgFiles);
        const prevSessionId = usePipelineStore.getState().sessionId;
        const fileMaterials = files?.map((f) => ({
          material_id: `file-${f.fileId}`,
          material_type: 'file' as const,
          content: `[用户上传文件] ${f.filename} (file_id: ${f.fileId})`,
          filename: f.filename,
        }));
        await pipelineRef.current.invoke({
          action: 'general_chat',
          businessType: 'general_chat',
          userMessage: text,
          sessionId: pipelineRef.current.sessionId || undefined,
          materials: fileMaterials,
        });
        // 新会话：将上传文件绑定到刚分配的 sessionId
        if (files && files.length > 0) {
          const newSessionId = usePipelineStore.getState().sessionId;
          if (newSessionId && newSessionId !== prevSessionId) {
            bindFilesToSession(files.map(f => f.fileId), newSessionId).catch(err => {
              console.warn('[useAIChat] Failed to bind files to session:', err);
            });
          }
        }
        return;
      }

      // ── 场景对话 ──
      const config = scenarios[scenarioKey];
      if (!config) return;

      if (scenarioKey !== activeScenario) {
        setActiveScenario(scenarioKey);
      }

      addMessage('user', text, msgFiles);

      const prevSessionId = usePipelineStore.getState().sessionId;
      const fileMaterials = files?.map(f => ({
        material_id: `file-${f.fileId}`,
        material_type: 'file' as const,
        content: `[用户上传文件] ${f.filename} (file_id: ${f.fileId})`,
        filename: f.filename,
      })) || [];

      await pipelineRef.current.invoke({
        action: config.action,
        businessType: config.businessType,
        userMessage: text,
        sessionId: pipelineRef.current.sessionId || undefined,
        materials: fileMaterials.length > 0 ? fileMaterials : undefined,
        candidateTypes: config.candidateTypes,
        formFields: config.formFields,
        auditRules: config.auditRules,
        knownValues: config.knownValues,
      });
      // 新会话：将上传文件绑定到刚分配的 sessionId
      if (files && files.length > 0) {
        const newSessionId = usePipelineStore.getState().sessionId;
        if (newSessionId && newSessionId !== prevSessionId) {
          bindFilesToSession(files.map(f => f.fileId), newSessionId).catch(err => {
            console.warn('[useAIChat] Failed to bind files to session:', err);
          });
        }
      }
    },
    [activeScenario, pipelineStatus, addMessage, setActiveScenario],
  );

  /** 通过提示卡片选择场景 */
  const selectScenario = useCallback(
    (config: ScenarioConfig) => {
      setActiveScenario(config.key);
      sendMessage(config.promptDescription, config.key);
    },
    [sendMessage, setActiveScenario],
  );

  // ── 经典模式自动启动：按钮点击 → 直接开始工作 ──

  useEffect(() => {
    if (
      activeScenario &&
      messages.length === 0 &&
      pipelineStatus === 'idle' &&
      autoStartedRef.current !== activeScenario
    ) {
      const config = getAIConfig().scenarios[activeScenario];
      if (!config) return;

      autoStartedRef.current = activeScenario;

      const autoText = `请帮我${config.smartButtonLabel}`;
      sendMessage(autoText, activeScenario);
    }
  }, [activeScenario, messages.length, pipelineStatus, sendMessage]);

  // ── 自动转场：Pipeline 完成 → sidepanel + onScenarioComplete ──

  useEffect(() => {
    if (
      prevStatusRef.current === 'running' &&
      (pipelineStatus === 'completed' || pipelineStatus === 'failed')
    ) {
      const currentAgentMsg = usePipelineStore.getState().agentMessage;
      const hasStreamingBubble = !!streamingMsgIdRef.current;
      if (!currentAgentMsg && !hasStreamingBubble) {
        if (pipelineStatus === 'completed') {
          addMessage('assistant', '处理完成！已为您填写好表单，您可以在左侧查看并编辑。');
        } else {
          addMessage('assistant', '处理过程中遇到了问题，请稍后重试或联系管理员。');
        }
      }

      // 将当前 pipeline 的 timeline + fileArtifacts 附加到最后一条 assistant 消息
      const { timelineEntries, fileArtifacts: storeArtifacts } = usePipelineStore.getState();
      if ((timelineEntries && timelineEntries.length > 0) || storeArtifacts.length > 0) {
        setMessages((prev) => {
          const copy = [...prev];
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].role === 'assistant') {
              const updates: Partial<ChatMessage> = {};
              if (timelineEntries && timelineEntries.length > 0) {
                updates.timeline = timelineEntries.map((e) => ({
                  type: e.type,
                  content: e.content,
                  iteration: e.iteration,
                  tool_name: e.toolExecution?.toolName,
                  success: e.toolExecution?.success,
                  blocked: e.toolExecution?.blocked,
                  latency_ms: e.toolExecution?.latencyMs,
                  args_summary: e.toolExecution?.argsSummary as Record<string, string> | undefined,
                  result_summary: e.toolExecution?.resultSummary,
                  ts: e.timestamp,
                }));
              }
              if (storeArtifacts.length > 0) {
                updates.fileArtifacts = storeArtifacts.map((a) => ({ ...a }));
              }
              copy[i] = { ...copy[i], ...updates };
              break;
            }
          }
          return copy;
        });
        // artifacts 已附加到消息，清空 store 避免堆积
        if (storeArtifacts.length > 0) {
          usePipelineStore.setState({ fileArtifacts: [] });
        }
      }

      // 智能缩小: 填单场景 (有字段值) → 缩到侧边让表单可见
      if (pipelineStatus === 'completed') {
        const { fieldValues } = usePipelineStore.getState();
        if (fieldValues.length > 0) {
          setChatDialogState('sidepanel');
        }
        if (scenarioConfig) {
          getAIConfig().onScenarioComplete?.(scenarioConfig.key, 'completed');
        }
      }

      // 延迟清理已完成 session 的缓存（保留 5 分钟供 F5 恢复）
      const completedSessionId = usePipelineStore.getState().sessionId;
      if (completedSessionId) {
        scheduleSessionCleanup(completedSessionId);
      }

    }
    prevStatusRef.current = pipelineStatus;
  }, [pipelineStatus, scenarioConfig, setChatDialogState, addMessage, sendMessage]);

  return {
    messages,
    sendMessage,
    selectScenario,
    addMessage,
    scenarioConfig,
    // 多 Session
    sessions,
    fetchSessions,
    // 状态
    isRunning: pipelineStatus === 'running',
    isCompleted: pipelineStatus === 'completed',
    isFailed: pipelineStatus === 'failed',
    hasPlan: !!plan,
    plan,
    pipeline,
    // 流式输出
    isStreaming,
  };
}
