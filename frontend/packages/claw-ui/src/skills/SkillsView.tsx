/**
 * F6: Skills 主内容区视图 — 双列卡片网格 + 搜索 + 添加。
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Input, Button, Spin, Empty, Tag, Popconfirm,
  Dropdown, message,
} from 'antd';
import {
  SearchOutlined,
  PlusOutlined,
  ImportOutlined,
  DeleteOutlined,
  EditOutlined,
  GithubOutlined,
  FolderOpenOutlined,
  FileZipOutlined,
} from '@ant-design/icons';
import { aiApi, type SkillMetadata, type SkillDetail } from '@claw/core';
import SkillEditorModal from './SkillEditorModal.tsx';
import ImportModal from './ImportModal.tsx';

const { listSkills, getSkillDetail, deleteSkill } = aiApi;

const SKILL_TYPE_LABEL: Record<string, string> = {
  domain: '领域',
  scenario: '场景',
  capability: '能力',
};

const SKILL_TYPE_COLOR: Record<string, string> = {
  domain: '#2db7f5',
  scenario: '#87d068',
  capability: '#fa8c16',
};

export default function SkillsView() {
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editData, setEditData] = useState<SkillDetail | null>(null);

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSkills();
      setSkills(data.skills);
    } catch (err) {
      console.error('[SkillsView] Failed to load skills:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSkills();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = useCallback(async (name: string) => {
    const result = await deleteSkill(name);
    if (result.ok) {
      message.success(`"${name}" 已删除`);
      fetchSkills();
    } else {
      message.error(result.error || '删除失败');
    }
  }, [fetchSkills]);

  const handleCardClick = useCallback(async (name: string) => {
    try {
      const detail = await getSkillDetail(name);
      setEditData(detail);
      setEditorOpen(true);
    } catch {
      message.error('加载 Skill 详情失败');
    }
  }, []);

  const handleEditorSuccess = useCallback(() => {
    fetchSkills();
  }, [fetchSkills]);

  const filtered = skills.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      (s.tags || []).some((t) => t.toLowerCase().includes(q))
    );
  });

  const addMenuItems = [
    {
      key: 'create',
      label: '创建新技能',
      icon: <PlusOutlined />,
      onClick: () => { setEditData(null); setEditorOpen(true); },
    },
    {
      key: 'import',
      label: '从 GitHub 导入',
      icon: <GithubOutlined />,
      onClick: () => setImportOpen(true),
    },
    {
      key: 'upload-file',
      label: '上传文件',
      icon: <FolderOpenOutlined />,
      onClick: () => setImportOpen(true),
    },
    {
      key: 'upload-zip',
      label: '上传 .zip',
      icon: <FileZipOutlined />,
      onClick: () => setImportOpen(true),
    },
  ];

  return (
    <div className="skills-view">
      {/* ── Header ── */}
      <div className="skills-view-header">
        <h2 className="skills-view-title">技能</h2>
        <p className="skills-view-desc">
          为您的智能体提供预构建且可重复的最佳实践与工具
        </p>
      </div>

      {/* ── Toolbar: search + add ── */}
      <div className="skills-view-toolbar">
        <Input
          prefix={<SearchOutlined style={{ color: '#bbb' }} />}
          placeholder="搜索技能"
          allowClear
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="skills-view-search"
        />
        <Dropdown menu={{ items: addMenuItems }} trigger={['click']}>
          <Button type="primary" icon={<ImportOutlined />}>
            添加
          </Button>
        </Dropdown>
      </div>

      {/* ── Cards grid ── */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <Empty
          description={search ? '没有匹配的技能' : '暂无技能'}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      ) : (
        <div className="skills-card-grid">
          {filtered.map((skill) => (
            <div
              key={skill.name}
              className="skills-card"
              role="button"
              tabIndex={0}
              onClick={() => handleCardClick(skill.name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleCardClick(skill.name);
                }
              }}
            >
              {/* Card header: name + actions */}
              <div className="skills-card-header">
                <span className="skills-card-name">{skill.name}</span>
                <div className="skills-card-actions">
                  <EditOutlined
                    className="skills-card-action-icon"
                    onClick={(e) => { e.stopPropagation(); handleCardClick(skill.name); }}
                  />
                  <Popconfirm
                    title={`确定删除 "${skill.name}"?`}
                    onConfirm={(e) => { e?.stopPropagation(); handleDelete(skill.name); }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true, size: 'small' }}
                    cancelButtonProps={{ size: 'small' }}
                  >
                    <DeleteOutlined
                      className="skills-card-action-icon skills-card-action-icon--danger"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              </div>

              {/* Description */}
              <div className="skills-card-desc">
                {skill.description || '暂无描述'}
              </div>

              {/* Footer: type tag + version */}
              <div className="skills-card-footer">
                <Tag
                  color={SKILL_TYPE_COLOR[skill.type || ''] || '#999'}
                  style={{ margin: 0, fontSize: 11 }}
                >
                  {SKILL_TYPE_LABEL[skill.type || ''] || skill.type || '未知'}
                </Tag>
                {skill.version && (
                  <span className="skills-card-version">v{skill.version}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

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
