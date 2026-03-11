/**
 * useAIChat — 对话框专用 Hook (解耦版)。
 *
 * 与宿主应用解耦:
 * - 不依赖 react-router-dom (通过 getAIConfig().onScenarioComplete 回调)
 * - 不硬编码场景 (通过 getAIConfig().scenarios 读取)
 * - 使用 useAIChatStore 替代 useAppStore
 *
 * 包装 usePipeline，增加：
 * - 场景配置读取
 * - 聊天消息管理
 * - Agent 文字回复 (agentMessage SSE → 聊天气泡)
 * - 自由对话 (无场景时使用 general_chat)
 * - 多 Session 管理：通过 sessionAction store 与 CoworkSidebar 通信
 * - Pipeline 完成后自动回调 (fullscreen → sidepanel + onScenarioComplete)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getAIConfig } from '../config.ts';
import { useAIChatStore } from '../stores/ai-chat.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import { usePipeline } from './usePipeline.ts';
import { listSessions as apiListSessions, getSessionHistory } from '../services/ai-api.ts';
import type { SessionInfo } from '../services/ai-api.ts';
import type { ScenarioConfig } from '../types/scenario.ts';

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

/**
 * useAIChat — 对话框专用 Hook。
 */
export function useAIChat() {
  const pipeline = usePipeline();
  const activeScenario = useAIChatStore((s) => s.activeScenario);
  const setChatDialogState = useAIChatStore((s) => s.setChatDialogState);
  const setActiveScenario = useAIChatStore((s) => s.setActiveScenario);
  const sessionAction = useAIChatStore((s) => s.sessionAction);
  const clearSessionAction = useAIChatStore((s) => s.clearSessionAction);
  const pipelineStatus = usePipelineStore((s) => s.status);
  const plan = usePipelineStore((s) => s.plan);
  const agentMessage = usePipelineStore((s) => s.agentMessage);
  const streamingText = usePipelineStore((s) => s.streamingText);
  const isStreaming = usePipelineStore((s) => s.isStreaming);
  const pipelineStore = usePipelineStore();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const prevStatusRef = useRef(pipelineStatus);
  const autoStartedRef = useRef<string | null>(null);
  const prevAgentMessageRef = useRef<string | null>(null);
  const streamingMsgIdRef = useRef<string | null>(null);

  /** 获取当前场景配置 */
  const scenarioConfig: ScenarioConfig | null =
    activeScenario ? getAIConfig().scenarios[activeScenario] || null : null;

  /** 获取默认用户ID */
  const defaultUserId = getAIConfig().defaultUserId;

  /** 添加消息 */
  const addMessage = useCallback(
    (role: 'user' | 'assistant', content: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          role,
          content,
          timestamp: Date.now(),
        },
      ]);
    },
    [],
  );

  // ── 流式文本 → 实时更新聊天气泡 ──
  useEffect(() => {
    if (!streamingText) return;

    if (!streamingMsgIdRef.current) {
      const id = `msg-stream-${Date.now()}`;
      streamingMsgIdRef.current = id;
      setMessages((prev) => [
        ...prev,
        { id, role: 'assistant', content: streamingText, timestamp: Date.now() },
      ]);
    } else {
      const streamId = streamingMsgIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === streamId ? { ...m, content: streamingText } : m,
        ),
      );
    }
  }, [streamingText]);

  // ── Agent 完整回复 → 最终确认气泡 ──
  useEffect(() => {
    if (agentMessage && agentMessage !== prevAgentMessageRef.current) {
      prevAgentMessageRef.current = agentMessage;

      if (streamingMsgIdRef.current) {
        const streamId = streamingMsgIdRef.current;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamId ? { ...m, content: agentMessage } : m,
          ),
        );
        streamingMsgIdRef.current = null;
      } else {
        addMessage('assistant', agentMessage);
      }
    }
  }, [agentMessage, addMessage]);

  // ── Session Action 消费 (来自 CoworkSidebar) ──
  useEffect(() => {
    if (!sessionAction) return;

    if (sessionAction.type === 'new') {
      setMessages([]);
      pipelineStore.reset();
      setActiveScenario(null);
      autoStartedRef.current = null;
      prevAgentMessageRef.current = null;
      streamingMsgIdRef.current = null;
    } else if (sessionAction.type === 'load') {
      const loadSession = async (sessionId: string) => {
        try {
          const detail = await getSessionHistory(defaultUserId, sessionId);
          const loaded: ChatMessage[] = detail.messages
            .filter((m) => m.role === 'user' || m.role === 'assistant')
            .map((m, i) => ({
              id: `hist-${sessionId}-${i}`,
              role: m.role as 'user' | 'assistant',
              content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
              timestamp: Date.now() - (detail.messages.length - i) * 1000,
            }));
          setMessages(loaded);
          pipelineStore.reset();
          pipelineStore.setSessionId(sessionId);
          autoStartedRef.current = 'loaded';
          prevAgentMessageRef.current = null;
        } catch (e) {
          console.warn('[useAIChat] Failed to load session:', e);
        }
      };
      loadSession(sessionAction.sessionId);
    }

    clearSessionAction();
  }, [sessionAction, clearSessionAction, pipelineStore, setActiveScenario, defaultUserId]);

  /** 发送用户消息并调用 Pipeline */
  const sendMessage = useCallback(
    async (text: string, scenario?: string, files?: { fileId: string; filename: string }[]) => {
      const scenarioKey = scenario || activeScenario;
      const scenarios = getAIConfig().scenarios;

      // ── 自由对话 (无场景) ──
      if (!scenarioKey) {
        addMessage('user', text);
        const fileMaterials = files?.map((f) => ({
          material_id: `file-${f.fileId}`,
          material_type: 'file' as const,
          content: `[用户上传文件] ${f.filename} (file_id: ${f.fileId})`,
          filename: f.filename,
        }));
        await pipeline.invoke({
          action: 'general_chat',
          businessType: 'general_chat',
          userMessage: text,
          sessionId: pipeline.sessionId || undefined,
          materials: fileMaterials,
        });
        return;
      }

      // ── 场景对话 ──
      const config = scenarios[scenarioKey];
      if (!config) return;

      if (scenarioKey !== activeScenario) {
        setActiveScenario(scenarioKey);
      }

      addMessage('user', text);

      const fileMaterials = files?.map(f => ({
        material_id: `file-${f.fileId}`,
        material_type: 'file' as const,
        content: `[用户上传文件] ${f.filename} (file_id: ${f.fileId})`,
        filename: f.filename,
      })) || [];

      await pipeline.invoke({
        action: config.action,
        businessType: config.businessType,
        userMessage: text,
        sessionId: pipeline.sessionId || undefined,
        materials: fileMaterials.length > 0 ? fileMaterials : undefined,
        candidateTypes: config.candidateTypes,
        formFields: config.formFields,
        auditRules: config.auditRules,
        knownValues: config.knownValues,
      });
    },
    [activeScenario, pipelineStatus, pipeline, addMessage, setActiveScenario],
  );

  /** 通过提示卡片选择场景 */
  const selectScenario = useCallback(
    (config: ScenarioConfig) => {
      setActiveScenario(config.key);
      sendMessage(config.promptDescription, config.key);
    },
    [sendMessage, setActiveScenario],
  );

  // ── 多 Session 管理 ──

  const fetchSessions = useCallback(async () => {
    try {
      const list = await apiListSessions(defaultUserId);
      setSessions(list);
    } catch (e) {
      console.warn('[useAIChat] Failed to fetch sessions:', e);
    }
  }, [defaultUserId]);

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
    }
    prevStatusRef.current = pipelineStatus;
  }, [pipelineStatus, scenarioConfig, setChatDialogState, addMessage]);

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
