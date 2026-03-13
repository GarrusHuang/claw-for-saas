import { useEffect, useState, useCallback } from 'react';
import { Typography, notification } from 'antd';
import {
  PlusOutlined,
  SearchOutlined,
  CalendarOutlined,
  BulbOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  useAIChatStore, usePipelineStore, aiApi, getAIConfig,
  useNotifications,
  type SessionInfo,
} from '@claw/core';
import SearchModal from './SearchModal.tsx';
import { SESSION_LABEL_MAP } from './constants';

const { listSessions: apiListSessions, deleteSession: apiDeleteSession } = aiApi;

const { Text } = Typography;

// ── Session label formatting ──

function formatSessionLabel(session: SessionInfo): string {
  // 优先使用动态生成的标题
  if ((session as Record<string, unknown>).title) {
    return (session as Record<string, unknown>).title as string;
  }
  const bt = session.business_type || session.type || '';
  return SESSION_LABEL_MAP[bt] || bt || '对话';
}

function formatSessionDate(session: SessionInfo): string {
  if (!session.created_at) return '';
  try {
    const ts = typeof session.created_at === 'number'
      ? (session.created_at < 1e12 ? session.created_at * 1000 : session.created_at)
      : Number(session.created_at);
    const d = new Date(ts);
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${min}`;
  } catch {
    return '';
  }
}

export default function CoworkSidebar() {
  const currentSessionId = usePipelineStore((s) => s.sessionId);
  const dispatchSessionAction = useAIChatStore((s) => s.dispatchSessionAction);
  const contentView = useAIChatStore((s) => s.contentView);
  const setContentView = useAIChatStore((s) => s.setContentView);

  // ── State ──
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [unreadIds, setUnreadIds] = useState<Set<string>>(new Set());

  // ── Session fetching ──
  const fetchSessions = useCallback(async () => {
    try {
      const list = await apiListSessions(getAIConfig().defaultUserId);
      setSessions(list);
    } catch (err) {
      console.warn('[CoworkSidebar] Failed to fetch sessions:', err);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [currentSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── WebSocket 通知: 后台产生新 session 时实时刷新列表 + 弹出提示 ──
  useNotifications(useCallback((event) => {
    if (event.type === 'session_created') {
      const sessionId = event.data?.session_id as string;
      if (sessionId) {
        setUnreadIds((prev) => new Set(prev).add(sessionId));
      }
      fetchSessions();
      const taskName = (event.data?.task_name as string) || '定时任务';
      const status = event.data?.status as string;
      notification.info({
        message: '定时任务完成',
        description: `「${taskName}」已${status === 'success' ? '执行完成' : '执行失败'}`,
        placement: 'topRight',
        duration: 5,
      });
    }
  }, [fetchSessions]));

  // ── Handlers ──
  const handleNewSession = useCallback(() => {
    setContentView('chat');
    dispatchSessionAction({ type: 'new' });
  }, [dispatchSessionAction, setContentView]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setContentView('chat');
    dispatchSessionAction({ type: 'load', sessionId });
    setUnreadIds((prev) => {
      if (!prev.has(sessionId)) return prev;
      const next = new Set(prev);
      next.delete(sessionId);
      return next;
    });
  }, [dispatchSessionAction, setContentView]);

  const handleScheduledClick = useCallback(() => {
    setContentView('schedule');
  }, [setContentView]);

  const handleSkillsClick = useCallback(() => {
    setContentView('skills');
  }, [setContentView]);

  const handleKnowledgeClick = useCallback(() => {
    setContentView('knowledge');
  }, [setContentView]);

  const handleDeleteSession = useCallback(async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await apiDeleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      // 如果删除的是当前会话，新建一个
      if (sessionId === currentSessionId) {
        dispatchSessionAction({ type: 'new' });
      }
    } catch (err) {
      console.warn('[CoworkSidebar] Failed to delete session:', err);
    }
  }, [currentSessionId, dispatchSessionAction]);

  const handleSearchSelect = useCallback((sessionId: string) => {
    setContentView('chat');
    dispatchSessionAction({ type: 'load', sessionId });
  }, [dispatchSessionAction, setContentView]);

  return (
    <div className="cowork-sidebar">
      {/* ── Function entries ── */}
      <div className="cowork-sidebar-entries">
        <button className="sidebar-entry sidebar-entry--new-task" onClick={handleNewSession}>
          <PlusOutlined style={{ fontSize: 14 }} />
          <span>新建任务</span>
        </button>
        <button className="sidebar-entry" onClick={() => setSearchOpen(true)}>
          <SearchOutlined style={{ fontSize: 14 }} />
          <span>搜索</span>
        </button>
        <button
          className={`sidebar-entry${contentView === 'schedule' ? ' sidebar-entry--active' : ''}`}
          onClick={handleScheduledClick}
        >
          <CalendarOutlined style={{ fontSize: 14 }} />
          <span>定时任务</span>
        </button>
        <button
          className={`sidebar-entry${contentView === 'skills' ? ' sidebar-entry--active' : ''}`}
          onClick={handleSkillsClick}
        >
          <BulbOutlined style={{ fontSize: 14 }} />
          <span>技能</span>
        </button>
        <button
          className={`sidebar-entry${contentView === 'knowledge' ? ' sidebar-entry--active' : ''}`}
          onClick={handleKnowledgeClick}
        >
          <DatabaseOutlined style={{ fontSize: 14 }} />
          <span>知识库</span>
        </button>
      </div>

      {/* ── Recents ── */}
      <div className="cowork-sidebar-section-title" style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 14, fontWeight: 600 }}>最近</Text>
        <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
          {sessions.length}
        </Text>
      </div>
      <div className="cowork-sidebar-session-list">
        {sessions.length === 0 ? (
          <div style={{ padding: '12px 8px', textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 14 }}>暂无会话</Text>
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.session_id === currentSessionId;
            const isUnread = unreadIds.has(session.session_id);
            const isBot = session.business_type === 'scheduled_task';
            return (
              <div
                key={session.session_id}
                className={`cowork-sidebar-session-item${isActive ? ' cowork-sidebar-session-item--active' : ''}${isUnread ? ' cowork-sidebar-session-item--unread' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => handleSelectSession(session.session_id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelectSession(session.session_id); } }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    {isBot && (
                      <RobotOutlined style={{ fontSize: 12, color: '#8b5cf6', flexShrink: 0 }} />
                    )}
                    {isUnread && (
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: '#f59e0b', flexShrink: 0,
                      }} />
                    )}
                    <Text
                      style={{
                        fontSize: 14,
                        fontWeight: isActive || isUnread ? 600 : 400,
                        color: isActive ? '#1a6fb5' : '#333',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        flex: 1,
                      }}
                    >
                      {formatSessionLabel(session)}
                    </Text>
                  </div>
                  <Text type="secondary" style={{ fontSize: 11, lineHeight: '14px' }}>
                    {formatSessionDate(session)}
                  </Text>
                </div>
                <DeleteOutlined
                  className="session-delete-btn"
                  style={{
                    fontSize: 12,
                    color: '#bbb',
                    flexShrink: 0,
                    padding: 4,
                    opacity: 0,
                    transition: 'opacity 0.15s',
                  }}
                  onClick={(e) => handleDeleteSession(e, session.session_id)}
                />
              </div>
            );
          })
        )}
      </div>

      {/* spacer */}
      <div style={{ marginTop: 'auto' }} />

      <SearchModal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelectSession={handleSearchSelect}
      />
    </div>
  );
}
