/**
 * 右栏面板 — Progress + Files + Instructions + Context
 */

import { useState, useEffect, useCallback } from 'react';
import { Typography, Modal, Spin } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  FileOutlined,
  BookOutlined,
  DatabaseOutlined,
  ToolOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { usePipelineStore, aiApi } from '@claw/core';
import type { PlanStepTracking, ToolExecution } from '@claw/core';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { Text } = Typography;
const REMARK_PLUGINS = [remarkGfm];

/* ── 文件预览 Modal ── */

function FilePreviewModal({
  open,
  title,
  onClose,
  fetchContent,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  fetchContent: () => Promise<string>;
}) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetchContent()
      .then((c) => setContent(c))
      .catch(() => setContent('加载失败'))
      .finally(() => setLoading(false));
  }, [open, fetchContent]);

  return (
    <Modal
      open={open}
      title={title}
      onCancel={onClose}
      footer={null}
      width={640}
      styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
      ) : (
        <div className="msg-ai" style={{ fontSize: 13, lineHeight: 1.7 }}>
          <Markdown remarkPlugins={REMARK_PLUGINS}>{content}</Markdown>
        </div>
      )}
    </Modal>
  );
}

/* ── 可点击的文件条目 ── */

function FileItem({
  name,
  icon,
  onClick,
}: {
  name: string;
  icon?: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } } : undefined}
      style={{
        fontSize: 13,
        color: '#595959',
        padding: '6px 10px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        borderRadius: 6,
        background: '#f7f8fa',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 0.15s',
      }}
      onMouseEnter={onClick ? (e) => { e.currentTarget.style.background = '#eef0f4'; } : undefined}
      onMouseLeave={onClick ? (e) => { e.currentTarget.style.background = '#f7f8fa'; } : undefined}
    >
      {icon || <FileOutlined style={{ fontSize: 12, color: '#8c8c8c', flexShrink: 0 }} />}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
        {name}
      </span>
      {onClick && (
        <EyeOutlined style={{ fontSize: 12, color: '#bfbfbf', flexShrink: 0 }} />
      )}
    </div>
  );
}

/* ── 主面板 ── */

export default function ProgressPanel() {
  const pipelineStatus = usePipelineStore((s) => s.status);
  const planSteps = usePipelineStore((s) => s.planSteps);
  const toolExecutions = usePipelineStore((s) => s.toolExecutions);

  const isRunning = pipelineStatus === 'running';
  const isCompleted = pipelineStatus === 'completed';
  const isFailed = pipelineStatus === 'failed';

  const hasPlanSteps = planSteps.length > 0;

  // ── Files: extract from tool executions ──
  const fileNames = Array.from(
    new Set(
      toolExecutions
        .filter((te: ToolExecution) => te.argsSummary && (te.argsSummary.file_path || te.argsSummary.filename || te.argsSummary.path))
        .map((te: ToolExecution) => te.argsSummary?.file_path || te.argsSummary?.filename || te.argsSummary?.path)
        .filter(Boolean) as string[]
    )
  );

  // ── Context: tool count + memory stats from API ──
  const [toolCount, setToolCount] = useState(0);
  const [memorySummary, setMemorySummary] = useState('');

  const loadContext = useCallback(async () => {
    try {
      const [tools, memStats] = await Promise.all([
        aiApi.listTools(),
        aiApi.getMemoryStats(),
      ]);
      setToolCount(tools.length);

      const parts: string[] = [];
      const corrCount = typeof memStats.corrections === 'number'
        ? memStats.corrections
        : (memStats.corrections as { total?: number })?.total ?? 0;
      if (corrCount > 0) parts.push(`${corrCount} 条纠正`);
      if (memStats.learning_entries > 0) parts.push(`${memStats.learning_entries} 条学习`);
      const sessCount = (memStats.sessions as { count?: number })?.count ?? 0;
      if (sessCount > 0) parts.push(`${sessCount} 次会话`);
      setMemorySummary(parts.length > 0 ? parts.join('，') : '暂无数据');
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadContext();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── File preview modal state ──
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState('');
  const [previewFetcher, setPreviewFetcher] = useState<() => Promise<string>>(() => () => Promise.resolve(''));

  const openSoulPreview = useCallback(() => {
    setPreviewTitle('soul.md — Agent 角色定义');
    setPreviewFetcher(() => async () => {
      try {
        const resp = await fetch('/api/soul', {
          headers: { 'Authorization': `Bearer ${localStorage.getItem('claw_token') || ''}` },
        });
        if (resp.ok) {
          const data = await resp.json();
          return data.content || '(内容为空)';
        }
      } catch { /* ignore */ }
      return '无法加载 soul.md 内容';
    });
    setPreviewOpen(true);
  }, []);

  const openFilePreview = useCallback((filename: string) => {
    setPreviewTitle(filename);
    setPreviewFetcher(() => async () => {
      // Try read via source file API
      try {
        const resp = await fetch(`/api/files/preview/${encodeURIComponent(filename)}`, {
          headers: { 'Authorization': `Bearer ${localStorage.getItem('claw_token') || ''}` },
        });
        if (resp.ok) {
          const data = await resp.json();
          return data.content || '(空文件)';
        }
      } catch { /* ignore */ }
      return `文件: ${filename}\n\n该文件由 Agent 在工具执行过程中操作。\n要查看完整内容，请在对话中让 Agent 读取此文件。`;
    });
    setPreviewOpen(true);
  }, []);

  return (
    <div className="progress-panel">
      {/* ── Section 1: Progress ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <ThunderboltOutlined style={{ fontSize: 14, color: '#fa8c16' }} />
          <span>进度</span>
          {isRunning && (
            <LoadingOutlined style={{ color: '#1677ff', fontSize: 14, marginLeft: 'auto' }} />
          )}
          {isCompleted && (
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 14, marginLeft: 'auto' }} />
          )}
          {isFailed && (
            <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 14, marginLeft: 'auto' }} />
          )}
        </div>
        {hasPlanSteps ? (
          <div className="progress-plan-steps">
            {planSteps.map((step: PlanStepTracking, i: number) => (
              <div key={i} className={`progress-plan-step progress-plan-step--${step.status}`}>
                <span className="progress-plan-step-icon">
                  {step.status === 'completed' && (
                    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 14 }} />
                  )}
                  {step.status === 'running' && (
                    <LoadingOutlined style={{ color: '#1677ff', fontSize: 14 }} />
                  )}
                  {step.status === 'failed' && (
                    <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 14 }} />
                  )}
                  {step.status === 'pending' && (
                    <ClockCircleOutlined style={{ color: '#d9d9d9', fontSize: 14 }} />
                  )}
                </span>
                <Text
                  style={{ fontSize: 13, flex: 1 }}
                  type={step.status === 'pending' ? 'secondary' : undefined}
                >
                  {step.description}
                </Text>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '6px 0' }}>
            <Text type="secondary" style={{ fontSize: 13 }}>暂无活跃任务</Text>
          </div>
        )}
      </div>

      {/* ── Section 2: Files ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <FileOutlined style={{ fontSize: 14, color: '#1677ff' }} />
          <span>文件</span>
          {fileNames.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#8c8c8c' }}>
              {fileNames.length}
            </span>
          )}
        </div>
        {fileNames.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {fileNames.map((name) => (
              <FileItem
                key={name}
                name={name}
                onClick={() => openFilePreview(name)}
              />
            ))}
          </div>
        ) : (
          <div style={{ padding: '6px 0' }}>
            <Text type="secondary" style={{ fontSize: 13 }}>暂无文件</Text>
          </div>
        )}
      </div>

      {/* ── Section 3: Instructions ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <BookOutlined style={{ fontSize: 14, color: '#722ed1' }} />
          <span>说明</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <FileItem
            name="soul.md"
            icon={<BookOutlined style={{ fontSize: 12, color: '#722ed1', flexShrink: 0 }} />}
            onClick={openSoulPreview}
          />
        </div>
      </div>

      {/* ── Section 4: Context ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <DatabaseOutlined style={{ fontSize: 14, color: '#13c2c2' }} />
          <span>上下文</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <FileItem
            name={`MCP 工具 (${toolCount})`}
            icon={<ToolOutlined style={{ fontSize: 12, color: '#8c8c8c', flexShrink: 0 }} />}
          />
          <FileItem
            name={`记忆 — ${memorySummary}`}
            icon={<DatabaseOutlined style={{ fontSize: 12, color: '#8c8c8c', flexShrink: 0 }} />}
          />
        </div>
      </div>

      {/* ── File Preview Modal ── */}
      <FilePreviewModal
        open={previewOpen}
        title={previewTitle}
        onClose={() => setPreviewOpen(false)}
        fetchContent={previewFetcher}
      />
    </div>
  );
}
