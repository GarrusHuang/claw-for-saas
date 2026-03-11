import { useState, useEffect, useRef, useCallback } from 'react';
import { useAIChatStore, useAIChat, usePipelineStore } from '@claw/core';
import ChatMessageList from './chat/ChatMessageList';
import ChatInput from './chat/ChatInput';
import CoworkSidebar from './chat/CoworkSidebar';
import ProgressPanel from './chat/ProgressPanel';

export type DialogMode = 'expanded' | 'collapsed';

interface AIChatDialogProps {
  onResize?: (mode: DialogMode) => void;
}

/**
 * AI 对话框 — Claude Cowork 文档流风格布局。
 *
 * cowork 模式: [CoworkSidebar] [ChatCenter] [ProgressPanel]
 * chat 模式:   [ChatCenter only]
 */
export default function AIChatDialog({ onResize }: AIChatDialogProps) {
  const chatDialogState = useAIChatStore((s) => s.chatDialogState);
  const closeChat = useAIChatStore((s) => s.closeChat);

  const {
    messages,
    sendMessage,
    isRunning,
  } = useAIChat();

  const [activeTab, setActiveTab] = useState<'chat' | 'cowork' | 'code'>('cowork');

  // ── Notify host of mode changes via onResize ──
  const onResizeRef = useRef(onResize);
  onResizeRef.current = onResize;

  useEffect(() => {
    if (chatDialogState === 'closed') return;
    const mode: DialogMode = chatDialogState === 'fullscreen' ? 'expanded' : 'collapsed';
    onResizeRef.current?.(mode);
  }, [chatDialogState]);

  if (chatDialogState === 'closed') return null;

  const isCowork = activeTab === 'cowork';

  return (
    <div className="ai-chat-dialog ai-chat-dialog--fullscreen">
      {/* ── Header with tabs ── */}
      <div className="chat-dialog-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: '#333', letterSpacing: '-0.3px' }}>
            Claw
          </span>
        </div>
        <div className="header-tabs">
          {(['chat', 'cowork', 'code'] as const).map((tab) => (
            <button
              key={tab}
              className={`header-tab${activeTab === tab ? ' header-tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
        <div style={{ width: 60 }} />
      </div>

      {/* ── Body: three-column layout ── */}
      <div className="chat-dialog-body-wrapper">
        {/* Left sidebar (cowork mode only) */}
        {isCowork && <CoworkSidebar />}

        {/* Center chat */}
        <div className="chat-dialog-body">
          <ChatMessageList
            messages={messages}
            showPipelineProgress
            onInteractionRespond={(value, files) => sendMessage(value, undefined, files)}
          />
        </div>

        {/* Right panel (cowork mode only) */}
        {isCowork && <ProgressPanel />}
      </div>

      {/* ── Input ── */}
      <ChatInput
        onSend={(text, files) => sendMessage(text, undefined, files)}
        disabled={isRunning}
        placeholder="Reply..."
      />
    </div>
  );
}
