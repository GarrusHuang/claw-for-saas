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
import { usePipelineStore, aiApi } from '@claw/core';
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

/* ── Artifact file card ── */

function ArtifactCard({
  filename,
  path,
  onPreview,
  onDownload,
}: {
  filename: string;
  path: string;
  onPreview: () => void;
  onDownload: () => void;
}) {
  const tag = getFileTypeTag(filename);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onPreview}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPreview(); } }}
      style={{
        padding: '8px 10px',
        border: '1px solid #e8e8e8',
        borderRadius: 8,
        cursor: 'pointer',
        transition: 'all 0.15s',
        background: '#fafafa',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#91d5ff'; e.currentTarget.style.background = '#f0f7ff'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fafafa'; }}
    >
      <span style={{ fontSize: 18, flexShrink: 0 }}>{getFileIcon(filename)}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontWeight: 500, fontSize: 12,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }} title={path}>
          {filename}
        </div>
      </div>
      <Tag color={tag.color} style={{ fontSize: 10, lineHeight: '18px', padding: '0 4px', margin: 0 }}>
        {tag.label}
      </Tag>
      <DownloadOutlined
        style={{ fontSize: 13, color: '#8c8c8c', flexShrink: 0, cursor: 'pointer' }}
        onClick={(e) => { e.stopPropagation(); onDownload(); }}
        title="下载"
      />
    </div>
  );
}

/* ── Knowledge file card (grid) ── */

function KnowledgeCard({
  file,
  onPreview,
}: {
  file: KBFileInfo;
  onPreview: () => void;
}) {
  const tag = getFileTypeTag(file.filename);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onPreview}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPreview(); } }}
      style={{
        padding: '8px 10px',
        border: '1px solid #e8e8e8',
        borderRadius: 8,
        cursor: 'pointer',
        transition: 'all 0.15s',
        background: '#fafafa',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#91d5ff'; e.currentTarget.style.background = '#f0f7ff'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fafafa'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 16, flexShrink: 0 }}>{getFileIcon(file.filename)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontWeight: 500, fontSize: 12,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={file.filename}>
            {file.filename}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
            <span style={{ fontSize: 10, color: '#bfbfbf' }}>{formatSize(file.size_bytes)}</span>
            <Tag color={tag.color} style={{ fontSize: 9, lineHeight: '16px', padding: '0 3px', margin: 0 }}>
              {tag.label}
            </Tag>
          </div>
        </div>
      </div>
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

  useEffect(() => {
    loadUploadedFiles();
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

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
      const encodedPath = encodeURIComponent(filePath);
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
    setPreviewHideDownload(false);
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {artifacts.map((a) => (
              <ArtifactCard
                key={a.path}
                filename={a.filename}
                path={a.path}
                onPreview={() => openArtifactPreview(a.path, a.filename)}
                onDownload={() => downloadArtifact(a.path, a.filename)}
              />
            ))}
          </div>
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
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 6,
          }}>
            {uploadedFiles.map((f) => (
              <div
                key={f.file_id}
                role="button"
                tabIndex={0}
                onClick={() => openUploadedFilePreview(f)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openUploadedFilePreview(f); } }}
                style={{
                  padding: '8px 10px',
                  border: '1px solid #e8e8e8',
                  borderRadius: 8,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  background: '#fafafa',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#87e8de'; e.currentTarget.style.background = '#e6fffb'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fafafa'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 16, flexShrink: 0 }}>{getFileIcon(f.filename)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontWeight: 500, fontSize: 12,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }} title={f.filename}>
                      {f.filename}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                      <span style={{ fontSize: 10, color: '#bfbfbf' }}>{formatSize(f.size_bytes)}</span>
                      <Tag color={getFileTypeTag(f.filename).color} style={{ fontSize: 9, lineHeight: '16px', padding: '0 3px', margin: 0 }}>
                        {getFileTypeTag(f.filename).label}
                      </Tag>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
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
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 6,
          }}>
            {kbFiles.map((f) => (
              <KnowledgeCard
                key={f.file_id}
                file={f}
                onPreview={() => openKnowledgePreview(f)}
              />
            ))}
          </div>
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
