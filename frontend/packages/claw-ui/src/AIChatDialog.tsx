import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from 'antd';
import {
  CloseOutlined,
  ExpandOutlined,
  CompressOutlined,
} from '@ant-design/icons';
import { useAIChatStore, useAIChat, usePipelineStore } from '@claw/core';
import ChatMessageList from './chat/ChatMessageList';
import ChatInput from './chat/ChatInput';
import PromptCards from './chat/PromptCards';
import ProgressPanel from './chat/ProgressPanel';

export type DialogMode = 'expanded' | 'collapsed';

interface AIChatDialogProps {
  onResize?: (mode: DialogMode) => void;
}

/**
 * AI 对话框 — Claude Cowork 风格布局。
 *
 * Phase 22B: 支持 expanded/collapsed 自动切换 + onResize 回调。
 *
 * expanded (fullscreen):
 * ┌──────────┬──────────────────────────┬────────────────────┐
 * │ Cowork   │ Center (Chat)            │ Right (Progress)   │
 * │ Sidebar  │                          │                    │
 * │ 200px    │ [messages...]            │ ⚡ Progress         │
 * │ (Claw     │ [PlanCard: 方案+确认]    │ ✅ Step 1           │
 * │  Sider)  │ [results...]             │ 🔄 Step 2           │
 * │          │                          │ 🕐 Step 3           │
 * │ Sessions │                          │                    │
 * │ Skills   │                          │                    │
 * │ MCP Tools│ [input box]              │                    │
 * └──────────┴──────────────────────────┴────────────────────┘
 *
 * collapsed (sidepanel):
 * 只有 Chat 列 (无 Progress 面板), 右侧窄面板
 */
export default function AIChatDialog({ onResize }: AIChatDialogProps) {
  const chatDialogState = useAIChatStore((s) => s.chatDialogState);
  const setChatDialogState = useAIChatStore((s) => s.setChatDialogState);
  const closeChat = useAIChatStore((s) => s.closeChat);
  const activeScenario = useAIChatStore((s) => s.activeScenario);

  const {
    messages,
    sendMessage,
    selectScenario,
    approvePlan,
    isRunning,
    isPlanAwaiting,
    scenarioConfig,
  } = useAIChat();

  const plan = usePipelineStore((s) => s.plan);
  const pipelineStatus = usePipelineStore((s) => s.status);
  const pipelineScenario = usePipelineStore((s) => s.scenario);
  const toolExecutions = usePipelineStore((s) => s.toolExecutions);

  const [showThinking, setShowThinking] = useState(false);

  // ── Phase 22B: Notify host of mode changes via onResize ──
  const onResizeRef = useRef(onResize);
  onResizeRef.current = onResize;

  useEffect(() => {
    if (chatDialogState === 'closed') return;
    const mode: DialogMode = chatDialogState === 'fullscreen' ? 'expanded' : 'collapsed';
    onResizeRef.current?.(mode);
  }, [chatDialogState]);

  const handleExpand = useCallback(() => {
    setChatDialogState('fullscreen');
  }, [setChatDialogState]);

  const handleCollapse = useCallback(() => {
    setChatDialogState('sidepanel');
  }, [setChatDialogState]);

  // 对话框关闭时不渲染
  if (chatDialogState === 'closed') return null;

  const isFullscreen = chatDialogState === 'fullscreen';
  const isSidepanel = chatDialogState === 'sidepanel';

  // 是否显示提示卡片（智能模式 + 无消息 + 无选定场景）
  const showPromptCards = messages.length === 0 && !activeScenario;

  // 是否显示右侧 Progress 面板
  const isBusinessScenario = pipelineScenario && pipelineScenario !== 'general_chat';
  const showProgress = isBusinessScenario && (
    pipelineStatus === 'running' ||
    pipelineStatus === 'completed' ||
    pipelineStatus === 'plan_awaiting' ||
    toolExecutions.length > 0 ||
    !!plan
  );

  return (
    <div
      className={`ai-chat-dialog ${
        isFullscreen
          ? 'ai-chat-dialog--fullscreen'
          : isSidepanel
          ? 'ai-chat-dialog--sidepanel'
          : 'ai-chat-dialog--closed'
      }`}
    >
      {/* ── Header ── */}
      <div className="chat-dialog-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <img
            src="/assets/claw-icon.svg"
            alt="Claw"
            style={{ width: 28, height: 28, borderRadius: '50%' }}
          />
          <span style={{ fontSize: 14, fontWeight: 600, color: '#333' }}>
            Claw AI Assistant
          </span>
          {scenarioConfig && (
            <span style={{ fontSize: 12, color: '#999' }}>
              — {scenarioConfig.title}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {isSidepanel && (
            <Button
              type="text"
              size="small"
              icon={<ExpandOutlined />}
              onClick={handleExpand}
              title="展开全屏"
            />
          )}
          {isFullscreen && (
            <Button
              type="text"
              size="small"
              icon={<CompressOutlined />}
              onClick={handleCollapse}
              title="收缩为侧面板"
            />
          )}
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            onClick={closeChat}
            title="关闭"
          />
        </div>
      </div>

      {/* ── Body: Chat + Progress Panel (Claude Cowork 风格) ── */}
      <div className="chat-dialog-body-wrapper">
        {/* 聊天区 */}
        <div className="chat-dialog-body">
          {showPromptCards ? (
            <div style={{ flex: 1, overflow: 'auto' }}>
              <PromptCards onSelect={selectScenario} onAsk={(q) => sendMessage(q)} />
            </div>
          ) : (
            <ChatMessageList
              messages={messages}
              showPipelineProgress
              onApprovePlan={approvePlan}
              showThinking={showThinking}
              onInteractionRespond={(value, files) => sendMessage(value, undefined, files)}
            />
          )}
        </div>

        {/* 右侧：Progress 面板 (仅 fullscreen + 执行中/完成时) */}
        {showProgress && isFullscreen && (
          <ProgressPanel plan={plan} showThinking={showThinking} />
        )}
      </div>

      {/* ── Input ── */}
      <ChatInput
        onSend={(text, files) => sendMessage(text, undefined, files)}
        disabled={isRunning}
        showThinking={showThinking}
        onShowThinkingChange={setShowThinking}
        placeholder={
          isPlanAwaiting
            ? '输入修改意见，或点击上方确认执行...'
            : activeScenario
              ? `继续对话，或输入新的需求...`
              : '请输入您的问题...'
        }
      />
    </div>
  );
}
