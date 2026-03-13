import { useEffect, useState, useCallback } from 'react';
import { Typography } from 'antd';
import {
  PlusOutlined,
  SearchOutlined,
  CalendarOutlined,
  BulbOutlined,
  DatabaseOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import {
  useAIChatStore, usePipelineStore, aiApi, getAIConfig,
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
    const d = new Date(session.created_at);
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

  // ── Handlers ──
  const handleNewSession = useCallback(() => {
    setContentView('chat');
    dispatchSessionAction({ type: 'new' });
  }, [dispatchSessionAction, setContentView]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setContentView('chat');
    dispatchSessionAction({ type: 'load', sessionId });
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
            return (
              <div
                key={session.session_id}
                className={`cowork-sidebar-session-item${isActive ? ' cowork-sidebar-session-item--active' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => handleSelectSession(session.session_id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelectSession(session.session_id); } }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Text
                    style={{
                      fontSize: 14,
                      fontWeight: isActive ? 600 : 400,
                      color: isActive ? '#1a6fb5' : '#333',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      display: 'block',
                    }}
                  >
                    {formatSessionLabel(session)}
                  </Text>
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
