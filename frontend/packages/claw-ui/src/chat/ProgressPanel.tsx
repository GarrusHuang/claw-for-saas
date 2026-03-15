/**
 * 右栏面板 — Progress + Artifacts + Uploaded Files + Knowledge Base
 */

import { useState, useEffect, useCallback } from 'react';
import { Typography, Tag, Spin } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  FileImageOutlined,
  CodeOutlined,
  DownloadOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { usePipelineStore, aiApi, getAIConfig } from '@claw/core';
import type { PlanStepTracking, ToolExecution, KBFileInfo, FileInfo } from '@claw/core';

const { Text } = Typography;

/* ── Helper: file type tag color ── */

function getFileTypeTag(filename: string): { label: string; color: string } {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, { label: string; color: string }> = {
    pdf: { label: 'PDF', color: 'red' },
    doc: { label: 'DOC', color: 'blue' },
    docx: { label: 'DOCX', color: 'blue' },
    xls: { label: 'XLS', color: 'green' },
    xlsx: { label: 'XLSX', color: 'green' },
    csv: { label: 'CSV', color: 'green' },
    html: { label: 'HTML', color: 'orange' },
    py: { label: 'PY', color: 'cyan' },
    js: { label: 'JS', color: 'gold' },
    ts: { label: 'TS', color: 'geekblue' },
    tsx: { label: 'TSX', color: 'geekblue' },
    jsx: { label: 'JSX', color: 'gold' },
    json: { label: 'JSON', color: 'purple' },
    md: { label: 'MD', color: 'default' },
    txt: { label: 'TXT', color: 'default' },
    png: { label: 'PNG', color: 'magenta' },
    jpg: { label: 'JPG', color: 'magenta' },
    jpeg: { label: 'JPEG', color: 'magenta' },
    gif: { label: 'GIF', color: 'magenta' },
    svg: { label: 'SVG', color: 'magenta' },
    sql: { label: 'SQL', color: 'volcano' },
    yaml: { label: 'YAML', color: 'lime' },
    yml: { label: 'YML', color: 'lime' },
  };
  return map[ext] || { label: ext.toUpperCase() || 'FILE', color: 'default' };
}

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext))
    return <FileImageOutlined style={{ color: '#1890ff' }} />;
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#ff4d4f' }} />;
  if (['doc', 'docx'].includes(ext)) return <FileWordOutlined style={{ color: '#2f54eb' }} />;
  if (['xls', 'xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#52c41a' }} />;
  if (['py', 'js', 'ts', 'tsx', 'jsx', 'java', 'go', 'rs', 'c', 'cpp', 'rb', 'php', 'sh', 'sql'].includes(ext))
    return <CodeOutlined style={{ color: '#722ed1' }} />;
  return <FileOutlined style={{ color: '#8c8c8c' }} />;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function extractFilename(path: string): string {
  return path.split('/').pop() || path;
}

/* ── 统一竖形文件卡片 ── */

function FileCard({
  filename,
  subtitle,
  onClick,
  onDownload,
}: {
  filename: string;
  subtitle?: string;
  onClick: () => void;
  onDownload?: () => void;
}) {
  const tag = getFileTypeTag(filename);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
      style={{
        padding: '10px 8px 8px',
        border: '1px solid #e8e8e8',
        borderRadius: 8,
        cursor: 'pointer',
        transition: 'all 0.15s',
        background: '#fafafa',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 4,
        position: 'relative',
        minWidth: 0,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#91d5ff'; e.currentTarget.style.background = '#f0f7ff'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fafafa'; }}
    >
      {onDownload && (
        <DownloadOutlined
          style={{ position: 'absolute', top: 4, right: 6, fontSize: 11, color: '#bfbfbf' }}
          onClick={(e) => { e.stopPropagation(); onDownload(); }}
          title="下载"
        />
      )}
      <span style={{ fontSize: 22 }}>{getFileIcon(filename)}</span>
      <div style={{
        width: '100%', textAlign: 'center',
        fontWeight: 500, fontSize: 11, lineHeight: '15px',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        padding: '0 2px',
      }} title={filename}>
        {filename}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        {subtitle && <span style={{ fontSize: 10, color: '#bfbfbf' }}>{subtitle}</span>}
        <Tag color={tag.color} style={{ fontSize: 9, lineHeight: '16px', padding: '0 3px', margin: 0 }}>
          {tag.label}
        </Tag>
      </div>
    </div>
  );
}

/* ── 2 列 grid，超 2 行滚动 ── */

const FILE_GRID_MAX_HEIGHT = 172; // ~2 rows of vertical cards

function FileGrid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(2, 1fr)',
      gap: 6,
      maxHeight: FILE_GRID_MAX_HEIGHT,
      overflowY: 'auto',
    }}>
      {children}
    </div>
  );
}

/* ── 主面板 ── */

export default function ProgressPanel() {
  const pipelineStatus = usePipelineStore((s) => s.status);
  const planSteps = usePipelineStore((s) => s.planSteps);
  const toolExecutions = usePipelineStore((s) => s.toolExecutions);
  const sessionId = usePipelineStore((s) => s.sessionId);

  const isRunning = pipelineStatus === 'running';
  const isCompleted = pipelineStatus === 'completed';
  const isFailed = pipelineStatus === 'failed';

  const hasPlanSteps = planSteps.length > 0;

  // ── Artifacts: extract from write_source_file tool executions ──
  const artifacts = Array.from(
    new Map(
      toolExecutions
        .filter((te: ToolExecution) =>
          te.toolName === 'write_source_file' &&
          te.argsSummary &&
          (te.argsSummary.file_path || te.argsSummary.filename || te.argsSummary.path)
        )
        .map((te: ToolExecution) => {
          const filePath = te.argsSummary?.file_path || te.argsSummary?.filename || te.argsSummary?.path || '';
          return [filePath, { path: filePath, filename: extractFilename(filePath) }] as const;
        })
    ).values()
  );

  // ── Uploaded files (user uploads for this session) ──
  const [uploadedFiles, setUploadedFiles] = useState<FileInfo[]>([]);
  const [uploadedLoading, setUploadedLoading] = useState(false);

  const loadUploadedFiles = useCallback(async () => {
    if (!sessionId) { setUploadedFiles([]); return; }
    setUploadedLoading(true);
    try {
      const files = await aiApi.listUserFiles(undefined, sessionId);
      setUploadedFiles(files);
    } catch {
      // ignore
    }
    setUploadedLoading(false);
  }, [sessionId]);

  // sessionId 变化 或 pipeline 状态变化时刷新上传文件列表
  // (用户发送带附件的消息后，status 变为 running → 触发刷新)
  useEffect(() => {
    loadUploadedFiles();
  }, [sessionId, pipelineStatus]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Referenced knowledge files (only those read by Agent via read_knowledge_file) ──
  const referencedKbFileIds = Array.from(
    new Set(
      toolExecutions
        .filter((te: ToolExecution) => te.toolName === 'read_knowledge_file' && te.argsSummary?.file_id)
        .map((te: ToolExecution) => te.argsSummary!.file_id as string)
    )
  );

  const [kbFiles, setKbFiles] = useState<KBFileInfo[]>([]);
  const [kbLoading, setKbLoading] = useState(false);

  useEffect(() => {
    if (referencedKbFileIds.length === 0) { setKbFiles([]); return; }
    let cancelled = false;
    const load = async () => {
      setKbLoading(true);
      try {
        const data = await aiApi.listKnowledgeFiles();
        if (!cancelled) {
          setKbFiles(data.files.filter((f: KBFileInfo) => referencedKbFileIds.includes(f.file_id)));
        }
      } catch {
        // ignore
      }
      if (!cancelled) setKbLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [referencedKbFileIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── FilePreviewModal (lazy import) ──
  const [FilePreviewModal, setFilePreviewModal] = useState<any>(null);
  useEffect(() => {
    import('../preview/FilePreviewModal').then(m => setFilePreviewModal(() => m.default)).catch(() => {});
  }, []);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFileId, setPreviewFileId] = useState('');
  const [previewFilename, setPreviewFilename] = useState('');
  const [previewApiBase, setPreviewApiBase] = useState('/api/files');
  const [previewHideDownload, setPreviewHideDownload] = useState(false);

  const openArtifactPreview = useCallback((filePath: string, filename: string) => {
    if (!sessionId) return;
    setPreviewFileId(`${sessionId}/files/${filePath}`);
    setPreviewFilename(filename);
    setPreviewApiBase('/api/workspace');
    setPreviewHideDownload(false);
    setPreviewOpen(true);
  }, [sessionId]);

  const downloadArtifact = useCallback(async (filePath: string, filename: string) => {
    if (!sessionId) return;
    try {
      const config = getAIConfig();
      const headers: Record<string, string> = {};
      if (config.getAuthToken) {
        const token = await config.getAuthToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
      } else if (config.authToken) {
        headers['Authorization'] = `Bearer ${config.authToken}`;
      }
      const encodedPath = filePath.split('/').map(encodeURIComponent).join('/');
      const res = await fetch(
        `${config.aiBaseUrl}/api/workspace/${sessionId}/files/${encodedPath}/download`,
        { headers }
      );
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // ignore
    }
  }, [sessionId]);

  const openUploadedFilePreview = useCallback((file: FileInfo) => {
    setPreviewFileId(file.file_id);
    setPreviewFilename(file.filename);
    setPreviewApiBase('/api/files');
    setPreviewHideDownload(true);
    setPreviewOpen(true);
  }, []);

  const openKnowledgePreview = useCallback((file: KBFileInfo) => {
    setPreviewFileId(file.file_id);
    setPreviewFilename(file.filename);
    setPreviewApiBase('/api/knowledge');
    setPreviewHideDownload(true);
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

      {/* ── Section 2: Artifacts (Agent 生成的文件) ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <AppstoreOutlined style={{ fontSize: 14, color: '#1677ff' }} />
          <span>制品</span>
          {artifacts.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#8c8c8c' }}>
              {artifacts.length}
            </span>
          )}
        </div>
        {artifacts.length > 0 ? (
          <FileGrid>
            {artifacts.map((a) => (
              <FileCard
                key={a.path}
                filename={a.filename}
                onClick={() => openArtifactPreview(a.path, a.filename)}
                onDownload={() => downloadArtifact(a.path, a.filename)}
              />
            ))}
          </FileGrid>
        ) : (
          <div style={{ padding: '6px 0' }}>
            <Text type="secondary" style={{ fontSize: 13 }}>暂无制品</Text>
          </div>
        )}
      </div>

      {/* ── Section 3: Uploaded Files (用户上传的文件) ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <CloudUploadOutlined style={{ fontSize: 14, color: '#13c2c2' }} />
          <span>上传文件</span>
          {uploadedFiles.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#8c8c8c' }}>
              {uploadedFiles.length}
            </span>
          )}
        </div>
        {uploadedLoading ? (
          <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
        ) : uploadedFiles.length > 0 ? (
          <FileGrid>
            {uploadedFiles.map((f) => (
              <FileCard
                key={f.file_id}
                filename={f.filename}
                subtitle={formatSize(f.size_bytes)}
                onClick={() => openUploadedFilePreview(f)}
              />
            ))}
          </FileGrid>
        ) : (
          <div style={{ padding: '6px 0' }}>
            <Text type="secondary" style={{ fontSize: 13 }}>暂无上传文件</Text>
          </div>
        )}
      </div>

      {/* ── Section 4: Knowledge Base (知识库文件) ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <DatabaseOutlined style={{ fontSize: 14, color: '#52c41a' }} />
          <span>知识库</span>
          {kbFiles.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#8c8c8c' }}>
              {kbFiles.length}
            </span>
          )}
        </div>
        {kbLoading ? (
          <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
        ) : kbFiles.length > 0 ? (
          <FileGrid>
            {kbFiles.map((f) => (
              <FileCard
                key={f.file_id}
                filename={f.filename}
                subtitle={formatSize(f.size_bytes)}
                onClick={() => openKnowledgePreview(f)}
              />
            ))}
          </FileGrid>
        ) : (
          <div style={{ padding: '6px 0' }}>
            <Text type="secondary" style={{ fontSize: 13 }}>暂无引用</Text>
          </div>
        )}
      </div>

      {/* ── File Preview Modal ── */}
      {FilePreviewModal && previewOpen && (
        <FilePreviewModal
          open={previewOpen}
          fileId={previewFileId}
          filename={previewFilename}
          onClose={() => setPreviewOpen(false)}
          apiBase={previewApiBase}
          hideDownload={previewHideDownload}
        />
      )}
    </div>
  );
}
