/**
 * useChatMessages — 消息状态 + streaming 效果。
 *
 * 从 useAIChat 提取，管理:
 * - ChatMessage[] 状态
 * - addMessage 回调
 * - streaming text → 实时聊天气泡
 * - agent 完整回复 → 最终确认气泡
 */

import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { usePipelineStore } from '../stores/pipeline.ts';
import type { ChatMessage, ChatMessageFile } from './useAIChat.ts';

export interface UseChatMessagesReturn {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  addMessage: (role: 'user' | 'assistant', content: string, files?: ChatMessageFile[]) => void;
  streamingMsgIdRef: React.MutableRefObject<string | null>;
  prevAgentMessageRef: React.MutableRefObject<string | null>;
}

export function useChatMessages(): UseChatMessagesReturn {
  const agentMessage = usePipelineStore((s) => s.agentMessage);
  const streamingText = usePipelineStore((s) => s.streamingText);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const prevAgentMessageRef = useRef<string | null>(null);
  const streamingMsgIdRef = useRef<string | null>(null);

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

  return {
    messages,
    setMessages,
    addMessage,
    streamingMsgIdRef,
    prevAgentMessageRef,
  };
}
