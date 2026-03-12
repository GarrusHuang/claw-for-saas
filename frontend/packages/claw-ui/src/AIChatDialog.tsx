import { useEffect, useRef, useCallback } from 'react';
import { useAIChatStore, useAIChat, usePipelineStore } from '@claw/core';
import ChatMessageList from './chat/ChatMessageList';
import ChatInput from './chat/ChatInput';
import CoworkSidebar from './chat/CoworkSidebar';
import ProgressPanel from './chat/ProgressPanel';
import ScheduleView from './schedule/ScheduleView';

export type DialogMode = 'expanded' | 'collapsed';

interface AIChatDialogProps {
  onResize?: (mode: DialogMode) => void;
}

/**
 * AI 对话框 — Cowork 文档流风格三栏布局。
 *
 * 固定布局: [CoworkSidebar] [ChatCenter] [ProgressPanel]
 */
export default function AIChatDialog({ onResize }: AIChatDialogProps) {
  const chatDialogState = useAIChatStore((s) => s.chatDialogState);
  const contentView = useAIChatStore((s) => s.contentView);

  const {
    messages,
    sendMessage,
    isRunning,
  } = useAIChat();

  // ── Notify host of mode changes via onResize ──
  const onResizeRef = useRef(onResize);
  onResizeRef.current = onResize;

  useEffect(() => {
    if (chatDialogState === 'closed') return;
    const mode: DialogMode = chatDialogState === 'fullscreen' ? 'expanded' : 'collapsed';
    onResizeRef.current?.(mode);
  }, [chatDialogState]);

  if (chatDialogState === 'closed') return null;

  return (
    <div className="ai-chat-dialog ai-chat-dialog--fullscreen">
      {/* ── Header ── */}
      <div className="chat-dialog-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: '#333', letterSpacing: '-0.3px' }}>
            Claw
          </span>
        </div>
        <div style={{ width: 60 }} />
      </div>

      {/* ── Body: three-column layout ── */}
      <div className="chat-dialog-body-wrapper">
        <CoworkSidebar />

        {contentView === 'chat' && (
          <>
            {/* Center chat */}
            <div className="chat-dialog-body">
              <ChatMessageList
                messages={messages}
                showPipelineProgress
                onInteractionRespond={(value, files) => sendMessage(value, undefined, files)}
              />
            </div>

            <ProgressPanel />
          </>
        )}

        {contentView === 'schedule' && (
          <div className="chat-dialog-body">
            <ScheduleView />
          </div>
        )}
      </div>

      {/* ── Input ── */}
      {contentView === 'chat' && (
        <ChatInput
          onSend={(text, files) => sendMessage(text, undefined, files)}
          disabled={isRunning}
          placeholder="回复..."
        />
      )}
    </div>
  );
}
