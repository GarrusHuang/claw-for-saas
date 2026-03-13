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
import { listSessions as apiListSessions, getSessionHistory, injectMessage } from '../services/ai-api.ts';
import type { SessionInfo } from '../services/ai-api.ts';
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
  const sessionAction = useAIChatStore((s) => s.sessionAction);
  const clearSessionAction = useAIChatStore((s) => s.clearSessionAction);
  const pipelineStatus = usePipelineStore((s) => s.status);
  const plan = usePipelineStore((s) => s.plan);
  const agentMessage = usePipelineStore((s) => s.agentMessage);
  const streamingText = usePipelineStore((s) => s.streamingText);
  const isStreaming = usePipelineStore((s) => s.isStreaming);

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
    (role: 'user' | 'assistant', content: string, files?: ChatMessageFile[]) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          role,
          content,
          timestamp: Date.now(),
          ...(files && files.length > 0 ? { files } : {}),
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

    let cancelled = false;

    if (sessionAction.type === 'new') {
      setMessages([]);
      usePipelineStore.getState().reset();
      setActiveScenario(null);
      autoStartedRef.current = null;
      prevAgentMessageRef.current = null;
      streamingMsgIdRef.current = null;
      clearSessionAction();
    } else if (sessionAction.type === 'load') {
      const loadSession = async (sessionId: string) => {
        try {
          const detail = await getSessionHistory(defaultUserId, sessionId);
          // 构建 timeline 查找表: turn_index → entries
          const timelineMap = new Map<number, ChatTimelineEntry[]>();
          if (detail.timelines) {
            for (const tl of detail.timelines) {
              const entries = (tl.entries || []).map((e) => ({
                type: e.type as 'thinking' | 'tool' | 'text',
                content: e.content,
                iteration: e.iteration,
                tool_name: e.tool_name,
                success: e.success,
                blocked: e.blocked,
                latency_ms: e.latency_ms,
                args_summary: e.args_summary,
                result_summary: e.result_summary,
                ts: e.ts,
              }));
              // 合并同一 turn 的 entries
              const existing = timelineMap.get(tl.turn_index) || [];
              timelineMap.set(tl.turn_index, [...existing, ...entries]);
            }
          }

          // 构建消息列表:
          // - 跳过 ReAct 循环中的中间 assistant 消息 (仅保留每轮最后一条)
          // - 附加 timeline 到对应的 assistant 消息
          const filtered = detail.messages.filter(
            (m) => m.role === 'user' || m.role === 'assistant',
          );
          let assistantIdx = 0;
          const loaded: ChatMessage[] = [];
          for (let i = 0; i < filtered.length; i++) {
            const m = filtered[i];
            if (m.role === 'assistant') {
              const isLastInRun =
                i + 1 >= filtered.length || filtered[i + 1].role !== 'assistant';
              if (isLastInRun) {
                // 仅保留连续 assistant 消息中的最后一条 (最终回复)
                const msg: ChatMessage = {
                  id: `hist-${sessionId}-${loaded.length}`,
                  role: 'assistant',
                  content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                  timestamp: Date.now() - (filtered.length - i) * 1000,
                };
                const tl = timelineMap.get(assistantIdx);
                if (tl && tl.length > 0) {
                  msg.timeline = tl;
                }
                loaded.push(msg);
              }
              assistantIdx++;
            } else {
              // 恢复用户消息附带的文件
              const rawFiles = (m as Record<string, unknown>).files;
              const files: ChatMessageFile[] | undefined = Array.isArray(rawFiles)
                ? rawFiles.map((f: Record<string, unknown>) => ({
                    fileId: (f.fileId ?? f.file_id ?? '') as string,
                    filename: (f.filename ?? '') as string,
                    contentType: (f.contentType ?? f.content_type) as string | undefined,
                    sizeBytes: (f.sizeBytes ?? f.size_bytes) as number | undefined,
                  })).filter((f) => f.fileId)
                : undefined;
              loaded.push({
                id: `hist-${sessionId}-${loaded.length}`,
                role: 'user',
                content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                timestamp: Date.now() - (filtered.length - i) * 1000,
                ...(files && files.length > 0 ? { files } : {}),
              });
            }
          }
          if (cancelled) return;
          setMessages(loaded);
          usePipelineStore.getState().reset();
          usePipelineStore.getState().setSessionId(sessionId);
          // 恢复 plan steps (右栏常驻显示)
          if (detail.plan_steps && detail.plan_steps.length > 0) {
            usePipelineStore.getState().initPlanSteps(
              detail.plan_steps.map((s) => ({
                step: s.index,
                description: s.description || s.action || '',
              })),
            );
            // 恢复每个步骤的完成状态
            for (const s of detail.plan_steps) {
              if (s.status === 'completed') {
                usePipelineStore.getState().completePlanStep(s.index);
              } else if (s.status === 'failed') {
                usePipelineStore.getState().failPlanStep(s.index);
              }
            }
          }
          autoStartedRef.current = 'loaded';
          prevAgentMessageRef.current = null;
        } catch (e) {
          console.warn('[useAIChat] Failed to load session:', e);
        }
        clearSessionAction();
      };
      loadSession(sessionAction.sessionId);
    }

    return () => { cancelled = true; };
  }, [sessionAction, clearSessionAction, setActiveScenario, defaultUserId]);

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
        return;
      }

      // ── 场景对话 ──
      const config = scenarios[scenarioKey];
      if (!config) return;

      if (scenarioKey !== activeScenario) {
        setActiveScenario(scenarioKey);
      }

      addMessage('user', text, msgFiles);

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

  // ── 多 Session 管理 ──

  const fetchSessions = useCallback(async () => {
    try {
      const list = await apiListSessions();
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

      // 将当前 pipeline 的 timeline 附加到最后一条 assistant 消息
      const { timelineEntries } = usePipelineStore.getState();
      if (timelineEntries && timelineEntries.length > 0) {
        setMessages((prev) => {
          const copy = [...prev];
          // 找到最后一条 assistant 消息
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].role === 'assistant') {
              copy[i] = {
                ...copy[i],
                timeline: timelineEntries.map((e) => ({
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
                })),
              };
              break;
            }
          }
          return copy;
        });
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
