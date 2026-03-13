import { useEffect, useRef, useCallback, useState } from 'react';
import { Button, Tooltip } from 'antd';
import {
  ThunderboltOutlined,
  FileTextOutlined,
  SearchOutlined,
  CalendarOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { useAIChatStore, useAIChat, usePipelineStore, useAuthStore } from '@claw/core';
import ChatMessageList from './chat/ChatMessageList';
import ChatInput from './chat/ChatInput';
import CoworkSidebar from './chat/CoworkSidebar';
import ProgressPanel from './chat/ProgressPanel';
import ScheduleView from './schedule/ScheduleView';
import SkillsView from './skills/SkillsView';

export type DialogMode = 'expanded' | 'collapsed';

interface AIChatDialogProps {
  onResize?: (mode: DialogMode) => void;
}

/* ── 欢迎屏 — 新会话无消息时居中展示 ── */

const QUICK_ACTIONS = [
  { icon: <ThunderboltOutlined />, label: '起草一份合同', prompt: '请帮我起草一份合同' },
  { icon: <FileTextOutlined />, label: '创建报销单', prompt: '请帮我创建一份报销单' },
  { icon: <SearchOutlined />, label: '查询文档', prompt: '帮我查询相关文档' },
  { icon: <CalendarOutlined />, label: '创建定时任务', prompt: '帮我创建一个定时任务' },
];

function WelcomeScreen({
  onAction,
  onSend,
  isRunning,
}: {
  onAction: (prompt: string) => void;
  onSend: (text: string, files?: { fileId: string; filename: string }[]) => void;
  isRunning: boolean;
}) {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '40px 24px 24px',
      minHeight: 0,
    }}>
      {/* 标题区 */}
      <div style={{
        fontSize: 28,
        fontWeight: 700,
        color: '#1a1a1a',
        letterSpacing: '-0.5px',
        marginBottom: 4,
      }}>
        Xisoft Claw
      </div>
      <div style={{
        fontSize: 15,
        color: '#8c8c8c',
        marginBottom: 28,
      }}>
        有什么可以帮到你的？
      </div>

      {/* 输入框 — 居中 */}
      <div style={{ width: '100%', maxWidth: 640, marginBottom: 20 }}>
        <ChatInput
          onSend={(text, files) => onSend(text, files)}
          disabled={isRunning}
          placeholder="输入你的问题..."
        />
      </div>

      {/* 快捷操作 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 10,
        maxWidth: 520,
        width: '100%',
      }}>
        {QUICK_ACTIONS.map((action) => (
          <div
            key={action.label}
            role="button"
            tabIndex={0}
            onClick={() => onAction(action.prompt)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onAction(action.prompt); } }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '12px 16px',
              border: '1px solid #e8e8e8',
              borderRadius: 12,
              cursor: 'pointer',
              transition: 'all 0.15s',
              fontSize: 14,
              color: '#595959',
              background: '#fff',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = '#4096ff';
              e.currentTarget.style.background = '#f0f7ff';
              e.currentTarget.style.color = '#1677ff';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#e8e8e8';
              e.currentTarget.style.background = '#fff';
              e.currentTarget.style.color = '#595959';
            }}
          >
            <span style={{ fontSize: 16, display: 'flex' }}>{action.icon}</span>
            <span>{action.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * AI 对话框 — Cowork 文档流风格三栏布局。
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

  const logout = useAuthStore((s) => s.logout);
  const userId = useAuthStore((s) => s.userId);

  const handleLogout = useCallback(() => {
    logout();
  }, [logout]);

  const hasMessages = messages.length > 0;
  const pipelineStatus = usePipelineStore((s) => s.status);
  const pipelineActive = pipelineStatus !== 'idle';

  if (chatDialogState === 'closed') return null;

  return (
    <div className="ai-chat-dialog ai-chat-dialog--fullscreen">
      {/* ── Header ── */}
      <div className="chat-dialog-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#1a1a1a', letterSpacing: '-0.3px' }}>
            Xisoft Claw
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {userId && (
            <span style={{ fontSize: 13, color: '#8c8c8c' }}>{userId}</span>
          )}
          <Tooltip title="退出登录">
            <Button
              type="text"
              size="small"
              icon={<LogoutOutlined />}
              onClick={handleLogout}
              style={{ color: '#8c8c8c' }}
            />
          </Tooltip>
        </div>
      </div>

      {/* ── Body: three-column layout ── */}
      <div className="chat-dialog-body-wrapper">
        <CoworkSidebar />

        {contentView === 'chat' && (
          <>
            <div className="chat-center-column">
              {!hasMessages && !pipelineActive ? (
                /* ── 空会话: 输入框与欢迎内容一起居中 ── */
                <WelcomeScreen
                  onAction={(prompt) => sendMessage(prompt)}
                  onSend={(text, files) => sendMessage(text, undefined, files)}
                  isRunning={isRunning}
                />
              ) : (
                /* ── 有消息: 正常聊天布局 ── */
                <>
                  <div className="chat-dialog-body">
                    <ChatMessageList
                      messages={messages}
                      showPipelineProgress
                      onInteractionRespond={(value, files) => sendMessage(value, undefined, files)}
                    />
                  </div>
                  <ChatInput
                    onSend={(text, files) => sendMessage(text, undefined, files)}
                    disabled={isRunning}
                    placeholder="回复..."
                  />
                </>
              )}
            </div>

            <ProgressPanel />
          </>
        )}

        {contentView === 'schedule' && (
          <div className="chat-center-column">
            <div className="chat-dialog-body">
              <ScheduleView />
            </div>
          </div>
        )}

        {contentView === 'skills' && (
          <div className="chat-center-column">
            <div className="chat-dialog-body">
              <SkillsView />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
