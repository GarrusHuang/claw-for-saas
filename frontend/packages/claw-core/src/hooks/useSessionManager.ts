/**
 * useSessionManager — Session CRUD + 切换 + cache + F5 保护。
 *
 * 从 useAIChat 提取，管理:
 * - sessionAction 消费 (来自 CoworkSidebar)
 * - F5 beforeunload 保存
 * - 运行中定期自动保存
 * - sessions 列表获取
 * - 启动时缓存清理
 */

import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getAIConfig } from '../config.ts';
import { useAIChatStore } from '../stores/ai-chat.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import { listSessions as apiListSessions, getSessionHistory, fetchPipelineSnapshot } from '../services/ai-api.ts';
import { applyPipelineSnapshot } from '../services/pipeline-dispatcher.ts';
import { saveSession, restoreSession, saveMessages, restoreMessages, getCachedStatus, cleanupExpiredSessions } from '../stores/pipeline-cache.ts';
import { useSessionStatusStore } from '../stores/session-status.ts';
import type { SessionInfo, SessionDetail } from '../services/ai-api.ts';
import type { ToolExecution } from '../types/pipeline.ts';
import type { ChatMessage, ChatMessageFile, ChatTimelineEntry } from './useAIChat.ts';

// ── loadSession 子函数 ──

/** 尝试从 sessionStorage 缓存恢复。成功返回 true。 */
function tryRestoreFromCache(
  sessionId: string,
  setMessages: (msgs: ChatMessage[]) => void,
  refs: {
    autoStarted: React.MutableRefObject<string | null>;
    prevAgentMessage: React.MutableRefObject<string | null>;
    streamingMsgId: React.MutableRefObject<string | null>;
  },
): boolean {
  const cachedMessages = restoreMessages(sessionId);
  if (!cachedMessages || !restoreSession(sessionId)) return false;
  const restored = cachedMessages as ChatMessage[];
  setMessages(restored);
  refs.autoStarted.current = 'loaded';
  refs.prevAgentMessage.current = null;
  const streamingMsg = restored.find(m => m.id.startsWith('msg-stream-'));
  refs.streamingMsgId.current = streamingMsg?.id || null;
  return true;
}

/** 从 API 历史构建消息列表（含 timeline 合并、assistant 去重）。 */
function buildMessagesFromHistory(
  detail: SessionDetail,
  sessionId: string,
): ChatMessage[] {
  // timeline 查找表
  const timelineMap = new Map<number, ChatTimelineEntry[]>();
  if (detail.timelines) {
    for (const tl of detail.timelines) {
      const entries = (tl.entries || []).map(e => ({
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
      const existing = timelineMap.get(tl.turn_index) || [];
      timelineMap.set(tl.turn_index, [...existing, ...entries]);
    }
  }

  // 消息构建（跳过 ReAct 中间 assistant、合并 timeline）
  const filtered = detail.messages.filter(m => m.role === 'user' || m.role === 'assistant');
  let assistantIdx = 0;
  const loaded: ChatMessage[] = [];
  for (let i = 0; i < filtered.length; i++) {
    const m = filtered[i];
    if (m.role === 'assistant') {
      const isLastInRun = i + 1 >= filtered.length || filtered[i + 1].role !== 'assistant';
      if (isLastInRun) {
        const msg: ChatMessage = {
          id: `hist-${sessionId}-${loaded.length}`,
          role: 'assistant',
          content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
          timestamp: Date.now() - (filtered.length - i) * 1000,
        };
        const tl = timelineMap.get(assistantIdx);
        if (tl && tl.length > 0) {
          msg.timeline = tl;
          // 从 write_source_file 工具调用重建 fileArtifacts
          const artifacts = tl
            .filter(e => e.type === 'tool' && e.tool_name === 'write_source_file' && e.success)
            .map(e => {
              const args = e.args_summary || {};
              const path = args.path || args.file_path || '';
              return { path, filename: path.split('/').pop() || path, sizeBytes: 0, contentType: 'application/octet-stream', sessionId };
            })
            .filter(a => a.path);
          if (artifacts.length > 0) msg.fileArtifacts = artifacts;
        }
        loaded.push(msg);
        assistantIdx++;
      }
    } else {
      // 用户消息（含附件恢复）
      const rawFiles = (m as Record<string, unknown>).files;
      const files: ChatMessageFile[] | undefined = Array.isArray(rawFiles)
        ? rawFiles.map((f: Record<string, unknown>) => ({
            fileId: (f.fileId ?? f.file_id ?? '') as string,
            filename: (f.filename ?? '') as string,
            contentType: (f.contentType ?? f.content_type) as string | undefined,
            sizeBytes: (f.sizeBytes ?? f.size_bytes) as number | undefined,
          })).filter(f => f.fileId)
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
  return loaded;
}

/** 从 API detail 恢复 pipeline store 状态。 */
function restoreStoreState(detail: SessionDetail, sessionId: string): void {
  usePipelineStore.getState().reset();
  usePipelineStore.getState().setSessionId(sessionId);

  // Plan steps
  if (detail.plan_steps && detail.plan_steps.length > 0) {
    usePipelineStore.getState().initPlanSteps(
      detail.plan_steps.map(s => ({ step: s.index, description: s.description || s.action || '' })),
    );
    for (const s of detail.plan_steps) {
      if (s.status === 'running') usePipelineStore.getState().startPlanStep(s.index);
      else if (s.status === 'completed') usePipelineStore.getState().completePlanStep(s.index);
      else if (s.status === 'failed') usePipelineStore.getState().failPlanStep(s.index);
    }
  }

  // Loaded skills
  if (detail.loaded_skills && detail.loaded_skills.length > 0) {
    usePipelineStore.getState().setLoadedSkills(detail.loaded_skills);
  }

  // Tool executions (直接 setState，不用 addToolExecution 避免 timelineEntries 污染)
  if (detail.timelines) {
    const histTools: ToolExecution[] = [];
    for (const tl of detail.timelines) {
      for (const e of (tl.entries || [])) {
        if (e.type === 'tool' && e.tool_name) {
          histTools.push({
            id: `hist-tool-${tl.turn_index}-${e.ts}`,
            toolName: e.tool_name,
            success: e.success ?? true,
            latencyMs: e.latency_ms || 0,
            timestamp: e.ts ? e.ts * 1000 : Date.now(),
            argsSummary: e.args_summary,
            resultSummary: e.result_summary,
            blocked: e.blocked,
          });
        }
      }
    }
    if (histTools.length > 0) {
      usePipelineStore.setState({ toolExecutions: histTools });
    }
  }

  // File artifacts: 已在 buildMessagesFromHistory 中按消息重建，不再放 store

  // Running session: 设 status
  if (useSessionStatusStore.getState().runningIds.has(sessionId)) {
    usePipelineStore.setState({ status: 'running' as const, startedAt: Date.now() });
  }
}

export interface UseSessionManagerParams {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  streamingMsgIdRef: React.MutableRefObject<string | null>;
  prevAgentMessageRef: React.MutableRefObject<string | null>;
}

export interface UseSessionManagerReturn {
  sessions: SessionInfo[];
  fetchSessions: () => Promise<void>;
  autoStartedRef: React.MutableRefObject<string | null>;
}

export function useSessionManager(params: UseSessionManagerParams): UseSessionManagerReturn {
  const { messages, setMessages, streamingMsgIdRef, prevAgentMessageRef } = params;

  const setActiveScenario = useAIChatStore((s) => s.setActiveScenario);
  const sessionAction = useAIChatStore((s) => s.sessionAction);
  const clearSessionAction = useAIChatStore((s) => s.clearSessionAction);
  const pipelineStatus = usePipelineStore((s) => s.status);

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const autoStartedRef = useRef<string | null>(null);

  const defaultUserId = getAIConfig().defaultUserId;

  // ── 启动时清理过期 sessionStorage 缓存 ──
  useEffect(() => {
    cleanupExpiredSessions();
  }, []);

  // ── Session Action 消费 (来自 CoworkSidebar) ──
  useEffect(() => {
    if (!sessionAction) return;

    let cancelled = false;

    if (sessionAction.type === 'new') {
      // 切走前保存当前 session 的消息和 pipeline 状态
      const currentSid = usePipelineStore.getState().sessionId;
      if (currentSid) {
        saveSession(currentSid);
        saveMessages(currentSid, messages);
      }
      setMessages([]);
      usePipelineStore.getState().reset();
      setActiveScenario(null);
      autoStartedRef.current = null;
      prevAgentMessageRef.current = null;
      streamingMsgIdRef.current = null;
      clearSessionAction();
    } else if (sessionAction.type === 'load') {
      const loadSession = async (sessionId: string) => {
        // 切走前保存当前 session
        const currentSid = usePipelineStore.getState().sessionId;
        if (currentSid && currentSid !== sessionId) {
          saveSession(currentSid);
          saveMessages(currentSid, messages);
        }

        // 运行中的 session: 优先从缓存恢复 (API 没有未完成的消息)
        // F5 后 runningIds 丢失 (内存状态)，用 getCachedStatus 从 sessionStorage 补充检测
        const wasCachedRunning = getCachedStatus(sessionId) === 'running';
        if (wasCachedRunning || useSessionStatusStore.getState().runningIds.has(sessionId)) {
          if (tryRestoreFromCache(sessionId, setMessages, {
            autoStarted: autoStartedRef,
            prevAgentMessage: prevAgentMessageRef,
            streamingMsgId: streamingMsgIdRef,
          })) {
            // 缓存恢复成功后仍需拉取快照：检测 pipeline 是否已完成
            fetchPipelineSnapshot(sessionId)
              .then((snapshot) => {
                if (usePipelineStore.getState().sessionId === sessionId) {
                  if (!snapshot.is_complete) {
                    useSessionStatusStore.getState().addRunning(sessionId);
                  }
                  applyPipelineSnapshot(snapshot);
                }
              })
              .catch(() => {
                // 快照不存在 (404) → pipeline 已结束，清理 running 状态
                if (usePipelineStore.getState().sessionId === sessionId) {
                  usePipelineStore.getState().completePipeline('success', 0);
                  useSessionStatusStore.getState().removeRunning(sessionId);
                }
              });
            clearSessionAction();
            return;
          }
        }

        // API 加载
        try {
          const detail = await getSessionHistory(defaultUserId, sessionId);
          if (cancelled) return;
          setMessages(buildMessagesFromHistory(detail, sessionId));
          restoreStoreState(detail, sessionId);

          // 快照补全 (running session 的流式文本)
          fetchPipelineSnapshot(sessionId)
            .then((snapshot) => {
              if (usePipelineStore.getState().sessionId === sessionId) {
                if (!snapshot.is_complete) {
                  useSessionStatusStore.getState().addRunning(sessionId);
                }
                applyPipelineSnapshot(snapshot);
              }
            })
            .catch(() => {
              // 快照不存在 → pipeline 已结束
              if (usePipelineStore.getState().sessionId === sessionId
                  && usePipelineStore.getState().status === 'running') {
                usePipelineStore.getState().completePipeline('success', 0);
                useSessionStatusStore.getState().removeRunning(sessionId);
              }
            });

          autoStartedRef.current = 'loaded';
          prevAgentMessageRef.current = null;
          streamingMsgIdRef.current = null;
        } catch (e) {
          console.warn('[useAIChat] Failed to load session:', e);
        }
        clearSessionAction();
      };
      loadSession(sessionAction.sessionId);
    }

    return () => { cancelled = true; };
  }, [sessionAction, clearSessionAction, setActiveScenario, defaultUserId]);

  // ── 多 Session 管理 ──

  const fetchSessions = useCallback(async () => {
    try {
      const list = await apiListSessions();
      setSessions(list);
    } catch (e) {
      console.warn('[useAIChat] Failed to fetch sessions:', e);
    }
  }, [defaultUserId]);

  // ── F5 保护：beforeunload 时保存当前 session 状态到 sessionStorage ──
  useEffect(() => {
    const handleBeforeUnload = () => {
      const sid = usePipelineStore.getState().sessionId;
      if (sid) {
        saveSession(sid);
        saveMessages(sid, messages);
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [messages]);

  // ── 运行中定期保存（每 3 秒，防止 crash 丢失）──
  useEffect(() => {
    if (pipelineStatus !== 'running') return;
    const timer = setInterval(() => {
      const sid = usePipelineStore.getState().sessionId;
      if (sid) {
        saveSession(sid);
        saveMessages(sid, messages);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pipelineStatus, messages]);

  return {
    sessions,
    fetchSessions,
    autoStartedRef,
  };
}
