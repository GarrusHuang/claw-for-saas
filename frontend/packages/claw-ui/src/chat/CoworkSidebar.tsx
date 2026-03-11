import { useEffect, useState, useCallback } from 'react';
import {
  Typography, Button, Spin, Empty, Input, Tag,
  Popconfirm, Tooltip, message,
} from 'antd';
import {
  PlusOutlined,
  SearchOutlined,
  CalendarOutlined,
  BulbOutlined,
  SettingOutlined,
  DeleteOutlined,
  ImportOutlined,
} from '@ant-design/icons';
import {
  useAIChatStore, usePipelineStore, aiApi,
  type SessionInfo, type SkillMetadata, type SkillDetail,
} from '@claw/core';
import SkillEditorModal from '../skills/SkillEditorModal.tsx';
import ImportModal from '../skills/ImportModal.tsx';

const { listSkills, getSkillDetail, deleteSkill, listSessions: apiListSessions } = aiApi;

const { Text } = Typography;

// ── Session label formatting ──

const SESSION_LABEL_MAP: Record<string, string> = {
  reimbursement_create: '报销创建',
  reimbursement_review: '报销审核',
  contract_draft: '合同起草',
  contract_review: '合同审核',
  general_chat: '自由对话',
};

function formatSessionLabel(session: SessionInfo): string {
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

const SKILL_TYPE_COLOR: Record<string, string> = {
  domain: '#2db7f5',
  scenario: '#87d068',
  capability: '#f50',
};

const DEFAULT_USER_ID = 'U001';

export default function CoworkSidebar() {
  const currentSessionId = usePipelineStore((s) => s.sessionId);
  const dispatchSessionAction = useAIChatStore((s) => s.dispatchSessionAction);

  // ── Sessions state ──
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  // ── Skills state ──
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const [skillSearch, setSkillSearch] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editData, setEditData] = useState<SkillDetail | null>(null);

  // ── Session fetching ──
  const fetchSessions = useCallback(async () => {
    try {
      const list = await apiListSessions(DEFAULT_USER_ID);
      setSessions(list);
    } catch (err) {
      console.warn('[CoworkSidebar] Failed to fetch sessions:', err);
    }
  }, []);

  // ── Skills lazy loading ──
  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      const data = await listSkills();
      setSkills(data.skills);
    } catch (err) {
      console.error('Failed to load skills:', err);
    } finally {
      setSkillsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [currentSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ──
  const handleNewSession = useCallback(() => {
    dispatchSessionAction({ type: 'new' });
  }, [dispatchSessionAction]);

  const handleSelectSession = useCallback((sessionId: string) => {
    dispatchSessionAction({ type: 'load', sessionId });
  }, [dispatchSessionAction]);

  const handleSkillsClick = useCallback(() => {
    if (!skillsExpanded) {
      setSkillsExpanded(true);
      loadSkills();
    } else {
      setSkillsExpanded(false);
    }
  }, [skillsExpanded, loadSkills]);

  const handleSkillDelete = useCallback(async (name: string) => {
    const result = await deleteSkill(name);
    if (result.ok) {
      message.success(`Skill "${name}" 已删除`);
      loadSkills();
    } else {
      message.error(result.error || '删除失败');
    }
  }, [loadSkills]);

  const handleSkillClick = useCallback(async (name: string) => {
    try {
      const detail = await getSkillDetail(name);
      setEditData(detail);
      setEditorOpen(true);
    } catch {
      message.error('加载 Skill 详情失败');
    }
  }, []);

  const handleEditorSuccess = useCallback(() => {
    loadSkills();
  }, [loadSkills]);

  const filteredSkills = skills.filter((s) => {
    if (!skillSearch) return true;
    const q = skillSearch.toLowerCase();
    return s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q);
  });

  return (
    <div className="cowork-sidebar">
      {/* ── Function entries ── */}
      <div className="cowork-sidebar-entries">
        <div className="sidebar-entry" onClick={handleNewSession}>
          <PlusOutlined style={{ fontSize: 13 }} />
          <span>New task</span>
        </div>
        <div className="sidebar-entry sidebar-entry--disabled">
          <SearchOutlined style={{ fontSize: 13 }} />
          <span>Search</span>
        </div>
        <div className="sidebar-entry sidebar-entry--disabled">
          <CalendarOutlined style={{ fontSize: 13 }} />
          <span>Scheduled</span>
        </div>
        <div className="sidebar-entry" onClick={handleSkillsClick}>
          <BulbOutlined style={{ fontSize: 13 }} />
          <span>Skills</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#999' }}>
            {skills.length > 0 ? skills.length : ''}
          </span>
        </div>
        <div className="sidebar-entry sidebar-entry--disabled">
          <SettingOutlined style={{ fontSize: 13 }} />
          <span>Customize</span>
        </div>
      </div>

      {/* ── Skills sub-view (lazy) ── */}
      {skillsExpanded && (
        <div className="cowork-sidebar-skills-view">
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 6 }}>
            <Input
              prefix={<SearchOutlined style={{ color: '#bbb', fontSize: 10 }} />}
              placeholder="Search skills..."
              size="small"
              allowClear
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
              style={{ flex: 1, borderRadius: 4, fontSize: 11 }}
            />
            <Tooltip title="Create">
              <Button
                type="text"
                size="small"
                icon={<PlusOutlined style={{ fontSize: 11 }} />}
                onClick={() => { setEditData(null); setEditorOpen(true); }}
              />
            </Tooltip>
            <Tooltip title="Import">
              <Button
                type="text"
                size="small"
                icon={<ImportOutlined style={{ fontSize: 11 }} />}
                onClick={() => setImportOpen(true)}
              />
            </Tooltip>
          </div>
          {skillsLoading ? (
            <div style={{ textAlign: 'center', padding: 12 }}><Spin size="small" /></div>
          ) : filteredSkills.length === 0 ? (
            <Empty description="No skills" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '8px 0' }} imageStyle={{ height: 24 }} />
          ) : (
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {filteredSkills.map((skill) => (
                <div
                  key={skill.name}
                  className="cowork-sidebar-skill-item"
                  onClick={() => handleSkillClick(skill.name)}
                >
                  <Text style={{ fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {skill.name}
                  </Text>
                  <Tag
                    color={SKILL_TYPE_COLOR[skill.type || ''] || '#999'}
                    style={{ fontSize: 8, lineHeight: '12px', padding: '0 2px', margin: 0, flexShrink: 0 }}
                  >
                    {skill.type || '?'}
                  </Tag>
                  <Popconfirm
                    title={`Delete "${skill.name}"?`}
                    onConfirm={(e) => { e?.stopPropagation(); handleSkillDelete(skill.name); }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="Delete"
                    cancelText="Cancel"
                    okButtonProps={{ danger: true, size: 'small' }}
                    cancelButtonProps={{ size: 'small' }}
                  >
                    <DeleteOutlined
                      className="cowork-sidebar-skill-delete"
                      style={{ fontSize: 10, color: '#ff4d4f', flexShrink: 0 }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Recents ── */}
      <div className="cowork-sidebar-section-title" style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>Recents</Text>
        <Text type="secondary" style={{ fontSize: 10, marginLeft: 'auto' }}>
          {sessions.length}
        </Text>
      </div>
      <div className="cowork-sidebar-session-list">
        {sessions.length === 0 ? (
          <div style={{ padding: '12px 8px', textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>暂无会话</Text>
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.session_id === currentSessionId;
            return (
              <div
                key={session.session_id}
                className={`cowork-sidebar-session-item${isActive ? ' cowork-sidebar-session-item--active' : ''}`}
                onClick={() => handleSelectSession(session.session_id)}
              >
                <Text
                  style={{
                    fontSize: 11,
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
                <Text type="secondary" style={{ fontSize: 9, lineHeight: '14px' }}>
                  {formatSessionDate(session)}
                </Text>
              </div>
            );
          })
        )}
      </div>

      {/* ── Bottom note ── */}
      <div style={{ marginTop: 'auto', padding: '12px 8px' }}>
        <Text type="secondary" style={{ fontSize: 10, lineHeight: '14px' }}>
          These tasks run locally and aren't synced across devices.
        </Text>
      </div>

      {/* ── Modals ── */}
      <SkillEditorModal
        open={editorOpen}
        onClose={() => { setEditorOpen(false); setEditData(null); }}
        onSuccess={handleEditorSuccess}
        editData={editData}
      />
      <ImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSuccess={handleEditorSuccess}
      />
    </div>
  );
}
