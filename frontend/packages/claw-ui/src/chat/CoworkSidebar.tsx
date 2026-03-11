import { useEffect, useState, useCallback } from 'react';
import {
  Typography, Tag, Input, Collapse, Tooltip, Button,
  Popconfirm, Spin, Empty, message,
} from 'antd';
import {
  PlusOutlined,
  MessageOutlined,
  AppstoreOutlined,
  ApiOutlined,
  ToolOutlined,
  ImportOutlined,
  DeleteOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  useAIChatStore, usePipelineStore, aiApi,
  type SessionInfo, type SkillMetadata, type SkillDetail,
} from '@claw/core';
import SkillEditorModal from '../skills/SkillEditorModal.tsx';
import ImportModal from '../skills/ImportModal.tsx';

const { listSkills, getSkillDetail, deleteSkill, listSessions: apiListSessions, listTools } = aiApi;
type ToolInfo = Awaited<ReturnType<typeof listTools>>[number];

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

// ── Skill type color mapping ──

const SKILL_TYPE_COLOR: Record<string, string> = {
  domain: '#2db7f5',
  scenario: '#87d068',
  capability: '#f50',
};

const DEFAULT_USER_ID = 'U001';

/**
 * Cowork Sidebar — 自管理的统一侧栏组件。
 *
 * 渲染在 Claw Layout 的左侧 Sider 内 (fullscreen 模式时替换菜单)。
 * 自行管理 Sessions / Skills / MCP Tools 的数据加载。
 * 通过 useAppStore.dispatchSessionAction 与 useAIChat 通信。
 */
export default function CoworkSidebar() {
  const currentSessionId = usePipelineStore((s) => s.sessionId);
  const dispatchSessionAction = useAIChatStore((s) => s.dispatchSessionAction);

  // ── Sessions state (self-managed) ──
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  // ── Skills state ──
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsLoaded, setSkillsLoaded] = useState(false);

  // ── MCP Tools state ──
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsLoaded, setToolsLoaded] = useState(false);
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

  // ── MCP Tools lazy loading ──
  const loadTools = useCallback(async () => {
    setToolsLoading(true);
    try {
      const data = await listTools();
      setTools(data);
    } catch (err) {
      console.error('Failed to load tools:', err);
    } finally {
      setToolsLoading(false);
      setToolsLoaded(true);
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
      setSkillsLoaded(true);
    }
  }, []);

  // ── Fetch sessions on mount + when sessionId changes (new session created) ──
  useEffect(() => {
    fetchSessions();
  }, [currentSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Collapse change handler for lazy loading ──
  const handleCollapseChange = useCallback((keys: string | string[]) => {
    const activeKeys = Array.isArray(keys) ? keys : [keys];
    if (activeKeys.includes('skills') && !skillsLoaded) {
      loadSkills();
    }
    if (activeKeys.includes('tools') && !toolsLoaded) {
      loadTools();
    }
  }, [skillsLoaded, loadSkills, toolsLoaded, loadTools]);

  // ── Session handlers → dispatch to store ──
  const handleNewSession = useCallback(() => {
    dispatchSessionAction({ type: 'new' });
  }, [dispatchSessionAction]);

  const handleSelectSession = useCallback((sessionId: string) => {
    dispatchSessionAction({ type: 'load', sessionId });
  }, [dispatchSessionAction]);

  // ── Skill handlers ──
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

  // ── Filtered skills ──
  const filteredSkills = skills.filter((s) => {
    if (!skillSearch) return true;
    const q = skillSearch.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q)
    );
  });

  // ── Render ──
  return (
    <div className="cowork-sidebar">
      {/* ── New session button ── */}
      <div className="cowork-sidebar-new-btn">
        <Button
          type="dashed"
          icon={<PlusOutlined />}
          onClick={handleNewSession}
          block
          size="small"
        >
          新对话
        </Button>
      </div>

      {/* ── Sessions section ── */}
      <div className="cowork-sidebar-section-title">
        <MessageOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
        <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>Sessions</Text>
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

      {/* ── Collapse: Skills + MCP Tools ── */}
      <div className="cowork-sidebar-toolbox">
        <Collapse
          ghost
          size="small"
          onChange={handleCollapseChange}
          items={[
            // ── Skills panel ──
            {
              key: 'skills',
              label: (
                <div className="cowork-sidebar-collapse-header">
                  <AppstoreOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(0,0,0,0.65)' }}>Skills</span>
                  <Tag
                    color="blue"
                    style={{ fontSize: 9, lineHeight: '14px', padding: '0 3px', margin: '0 0 0 4px' }}
                  >
                    {skills.length}
                  </Tag>
                  <span style={{ flex: 1 }} />
                  <Tooltip title="创建 Skill">
                    <PlusOutlined
                      style={{ fontSize: 11, color: '#1a6fb5', cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditData(null);
                        setEditorOpen(true);
                      }}
                    />
                  </Tooltip>
                  <Tooltip title="导入 Skill">
                    <ImportOutlined
                      style={{ fontSize: 11, color: '#1a6fb5', cursor: 'pointer', marginLeft: 6 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setImportOpen(true);
                      }}
                    />
                  </Tooltip>
                </div>
              ),
              children: (
                <div>
                  {/* Search */}
                  <Input
                    prefix={<SearchOutlined style={{ color: '#bbb', fontSize: 10 }} />}
                    placeholder="搜索..."
                    size="small"
                    allowClear
                    value={skillSearch}
                    onChange={(e) => setSkillSearch(e.target.value)}
                    style={{ marginBottom: 6, borderRadius: 4, fontSize: 11 }}
                  />
                  {/* List */}
                  {skillsLoading ? (
                    <div style={{ textAlign: 'center', padding: 12 }}>
                      <Spin size="small" />
                    </div>
                  ) : filteredSkills.length === 0 ? (
                    <Empty
                      description="无 Skill"
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      style={{ margin: '8px 0' }}
                      imageStyle={{ height: 24 }}
                    />
                  ) : (
                    <div style={{ maxHeight: 200, overflow: 'auto' }}>
                      {filteredSkills.map((skill) => (
                        <div
                          key={skill.name}
                          className="cowork-sidebar-skill-item"
                          onClick={() => handleSkillClick(skill.name)}
                        >
                          <Text
                            style={{
                              fontSize: 11,
                              flex: 1,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {skill.name}
                          </Text>
                          <Tag
                            color={SKILL_TYPE_COLOR[skill.type || ''] || '#999'}
                            style={{
                              fontSize: 8,
                              lineHeight: '12px',
                              padding: '0 2px',
                              margin: 0,
                              flexShrink: 0,
                            }}
                          >
                            {skill.type || '?'}
                          </Tag>
                          <Popconfirm
                            title={`删除 "${skill.name}"？`}
                            onConfirm={(e) => {
                              e?.stopPropagation();
                              handleSkillDelete(skill.name);
                            }}
                            onCancel={(e) => e?.stopPropagation()}
                            okText="删除"
                            cancelText="取消"
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
              ),
            },

            // ── MCP Tools panel ──
            {
              key: 'tools',
              label: (
                <div className="cowork-sidebar-collapse-header">
                  <ApiOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(0,0,0,0.65)' }}>MCP Tools</span>
                  <Tag
                    color="purple"
                    style={{ fontSize: 9, lineHeight: '14px', padding: '0 3px', margin: '0 0 0 4px' }}
                  >
                    {tools.length}
                  </Tag>
                </div>
              ),
              children: (
                <div>
                  {toolsLoading ? (
                    <div style={{ textAlign: 'center', padding: 12 }}>
                      <Spin size="small" />
                    </div>
                  ) : tools.length === 0 ? (
                    <Empty
                      description="无工具"
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      style={{ margin: '8px 0' }}
                      imageStyle={{ height: 24 }}
                    />
                  ) : (
                    <div style={{ maxHeight: 200, overflow: 'auto' }}>
                      {tools.map((tool) => (
                        <Tooltip key={tool.name} title={tool.description} placement="right">
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: 4,
                            padding: '4px 6px', fontSize: 11, borderRadius: 4,
                            cursor: 'default',
                          }}>
                            <ToolOutlined style={{ fontSize: 10, color: '#8c8c8c', flexShrink: 0 }} />
                            <Text
                              style={{
                                fontSize: 11, flex: 1,
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                              }}
                            >
                              {tool.name}
                            </Text>
                            {tool.read_only && (
                              <Tag
                                color="default"
                                style={{ fontSize: 8, lineHeight: '12px', padding: '0 2px', margin: 0 }}
                              >
                                RO
                              </Tag>
                            )}
                          </div>
                        </Tooltip>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },

          ]}
        />
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
