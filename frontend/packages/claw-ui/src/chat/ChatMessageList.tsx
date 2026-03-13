import React, { useEffect, useRef, useState, memo } from 'react';
import { Typography, Spin, Button, Modal } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  BulbOutlined,
  ToolOutlined,
  StopOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  FileWordOutlined,
  FileImageOutlined,
  FileZipOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { usePipelineStore, getAIConfig } from '@claw/core';
import type { PendingInteraction, ToolExecution, TimelineEntry } from '@claw/core';
import {
  MiniTypeInference,
  MiniFieldUpdates,
  MiniAuditSummary,
} from './ChatResultCards';
import DocumentPresenter from '../results/DocumentPresenter';
import InlineUploader from './InlineUploader';
import InteractiveMessage from './InteractiveMessage';
import CollapsibleBlock from './CollapsibleBlock';

import type { ChatMessage, ChatMessageFile, ChatTimelineEntry } from '@claw/core';

const { Text } = Typography;

const REMARK_PLUGINS = [remarkGfm];

interface ChatMessageListProps {
  messages: ChatMessage[];
  showPipelineProgress?: boolean;
  onInteractionRespond?: (value: string, files?: { fileId: string; filename: string }[]) => void;
}

// ── PlanCard 组件 — 在聊天流中渲染 Agent 提出的方案 ──

function PlanCard() {
  const plan = usePipelineStore((s) => s.plan);
  const agentPlanProposed = usePipelineStore((s) => s.agentPlanProposed);
  const status = usePipelineStore((s) => s.status);

  // 仅当 Agent 主动 propose 时才显示 PlanCard
  if (!agentPlanProposed || !plan) return null;

  const steps = Array.isArray(plan.steps) ? plan.steps : [];
  const isExecuting = status === 'running';

  // 是否有完整的 Markdown 文档
  const hasDetail = !!plan.detail && plan.detail.trim().length > 0;

  return (
    <div className="plan-document">
      {/* ── 文档头部 ── */}
      <div className="plan-document-header">
        <div className="plan-document-title-row">
          <ThunderboltOutlined style={{ color: '#fa8c16', fontSize: 16 }} />
          <span className="plan-document-title">执行方案</span>
          {isExecuting && (
            <span className="plan-document-badge plan-document-badge--confirmed">执行中</span>
          )}
          {!isExecuting && (
            <span className="plan-document-badge plan-document-badge--auto">自主执行</span>
          )}
        </div>
        {plan.summary && (
          <div className="plan-document-summary">{plan.summary}</div>
        )}
      </div>

      {/* ── Markdown 文档正文 ── */}
      {hasDetail ? (
        <div className="plan-document-body markdown-body">
          <Markdown remarkPlugins={REMARK_PLUGINS}>{plan.detail}</Markdown>
        </div>
      ) : steps.length > 0 ? (
        /* 回退: 无 detail 时仍显示简单步骤列表 */
        <div className="plan-document-body">
          <div className="plan-document-steps-fallback">
            {steps.map((step, i) => {
              const desc = typeof step === 'string'
                ? step
                : (step as { description?: string }).description || JSON.stringify(step);
              return (
                <div key={i} className="plan-document-step-item">
                  <span className="plan-document-step-num">{i + 1}</span>
                  <Text style={{ fontSize: 13 }}>{desc}</Text>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* ── 操作区 ── */}
      <div className="plan-document-footer">
        {isExecuting && (
          <div className="plan-document-actions">
            <Text type="success" style={{ fontSize: 12 }}>
              <CheckCircleOutlined style={{ marginRight: 4 }} />
              正在执行...
            </Text>
          </div>
        )}
        {plan.estimatedActions > 0 && (
          <div className="plan-document-meta">
            预计 {plan.estimatedActions} 次工具调用
            {steps.length > 0 && ` · ${steps.length} 个步骤`}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Pipeline 进度组件 — 折叠摘要 ──

function InlinePipelineProgress() {
  const status = usePipelineStore((s) => s.status);
  const inferredType = usePipelineStore((s) => s.inferredType);
  const fieldValues = usePipelineStore((s) => s.fieldValues);
  const auditSummary = usePipelineStore((s) => s.auditSummary);
  const document = usePipelineStore((s) => s.document);
  const toolExecutions = usePipelineStore((s) => s.toolExecutions);
  const durationMs = usePipelineStore((s) => s.durationMs);

  if (status === 'idle') return null;

  // Build one-line summary
  const parts: string[] = [];
  if (toolExecutions.length > 0) parts.push(`执行了 ${toolExecutions.length} 个工具`);
  if (fieldValues.length > 0) parts.push(`填充了 ${fieldValues.length} 个字段`);
  if (inferredType) parts.push(`类型: ${inferredType.docType}`);
  if (auditSummary) parts.push(`审计: ${auditSummary.conclusion}`);
  if (document) parts.push(`文档: ${document.title}`);
  const summaryText = parts.length > 0 ? parts.join(', ') : '处理中...';

  return (
    <div>
      {/* PlanCard — Agent 提出的方案 */}
      <PlanCard />

      {/* Pipeline progress as collapsible */}
      <CollapsibleBlock
        icon={<ThunderboltOutlined style={{ color: '#fa8c16', fontSize: 12 }} />}
        summary={status === 'running' ? `Agent 工作中 — ${summaryText}` : summaryText}
      >
        {/* 实时处理状态 */}
        {status === 'running' && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Spin size="small" />
              <Text type="secondary" style={{ fontSize: 12 }}>
                Agent 自主处理中...
              </Text>
            </div>
          </div>
        )}

        {/* 结果卡片 */}
        {inferredType && <MiniTypeInference data={inferredType} />}
        {fieldValues.length > 0 && <MiniFieldUpdates fields={fieldValues} />}
        {auditSummary && <MiniAuditSummary data={auditSummary} />}
        {document && <DocumentPresenter document={document} />}
      </CollapsibleBlock>

      {/* 完成提示 */}
      {status === 'completed' && durationMs > 0 && (
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
            处理完成，用时 {(durationMs / 1000).toFixed(1)}s
          </Text>
        </div>
      )}

      {/* 失败提示 */}
      {status === 'failed' && (
        <div style={{ marginTop: 8 }}>
          <Text type="danger" style={{ fontSize: 11 }}>
            <CloseCircleOutlined style={{ marginRight: 4 }} />
            处理失败
          </Text>
        </div>
      )}
    </div>
  );
}

// ── 工具调用折叠行 — 逐条嵌入文档流 ──

// ── 单个工具执行行 ──
function ToolExecutionItem({ te }: { te: ToolExecution }) {
  return (
    <div style={{ padding: '3px 0', fontSize: 11, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
      <span style={{ flexShrink: 0, marginTop: 1 }}>
        {te.blocked ? (
          <StopOutlined style={{ color: '#faad14', fontSize: 11 }} />
        ) : te.success ? (
          <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
        ) : (
          <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />
        )}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontWeight: 500, color: '#333' }}>{te.toolName}</span>
        <span style={{ color: '#999', marginLeft: 4 }}>({Math.round(te.latencyMs)}ms)</span>
        {te.argsSummary && Object.keys(te.argsSummary).length > 0 && (
          <div style={{ color: '#888', fontSize: 10 }}>
            {'→ '}
            {Object.entries(te.argsSummary)
              .map(([k, v]) => `${k}=${v}`)
              .join(', ')}
          </div>
        )}
        {te.resultSummary && (
          <div style={{ color: '#666', fontSize: 10 }}>
            {'← '}{te.resultSummary}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 按迭代分组 — 对标 Claude Code: thinking→折叠块, text→正文, tools→折叠块 ──
const HIDDEN_TOOLS = ['propose_plan', 'update_plan_step'];

interface IterGroup {
  id: string;
  thinking?: string;
  text?: string;
  tools: ToolExecution[];
}

interface PersistedIterGroup {
  id: string;
  thinking?: string;
  text?: string;
  tools: ChatTimelineEntry[];
}

/** live entries → 按迭代分组 (thinking/text 开始新组, tool 追加到当前组) */
function groupByIteration(entries: TimelineEntry[]): IterGroup[] {
  const groups: IterGroup[] = [];
  let cur: IterGroup | null = null;
  let curIter: number | undefined;
  for (const e of entries) {
    if (e.type === 'thinking') {
      if (cur) groups.push(cur);
      cur = { id: e.id, thinking: e.content || '', tools: [] };
      curIter = e.iteration;
    } else if (e.type === 'text') {
      // 当前组已有 tools 或 iteration 变了 → 新组 (防止正文推着工具走)
      const iterChanged = e.iteration !== undefined && e.iteration !== curIter;
      if (!cur || cur.tools.length > 0 || iterChanged) {
        if (cur) groups.push(cur);
        cur = { id: e.id, text: e.content || '', tools: [] };
        curIter = e.iteration;
      } else {
        cur.text = (cur.text || '') + (e.content || '');
      }
    } else if (e.type === 'tool' && e.toolExecution) {
      if (!cur) cur = { id: e.id, tools: [] };
      if (!HIDDEN_TOOLS.includes(e.toolExecution.toolName)) {
        cur.tools.push(e.toolExecution);
      }
    }
  }
  if (cur) groups.push(cur);
  return groups;
}

/** persisted entries → 按迭代分组 */
function groupPersistedByIteration(entries: ChatTimelineEntry[]): PersistedIterGroup[] {
  const groups: PersistedIterGroup[] = [];
  let cur: PersistedIterGroup | null = null;
  let curIter: number | undefined;
  for (const e of entries) {
    if (e.type === 'thinking') {
      if (cur && cur.tools.length === 0 && cur.thinking !== undefined && !cur.text) {
        cur.thinking = (cur.thinking || '') + (e.content || '');
      } else {
        if (cur) groups.push(cur);
        cur = { id: `pg-${groups.length}`, thinking: e.content || '', tools: [] };
        curIter = e.iteration;
      }
    } else if (e.type === 'text') {
      const iterChanged = e.iteration !== undefined && e.iteration !== curIter;
      if (!cur || cur.tools.length > 0 || iterChanged) {
        if (cur) groups.push(cur);
        cur = { id: `pg-${groups.length}`, text: e.content || '', tools: [] };
        curIter = e.iteration;
      } else {
        cur.text = (cur.text || '') + (e.content || '');
      }
    } else if (e.type === 'tool') {
      if (!cur) cur = { id: `pg-${groups.length}`, tools: [] };
      if (!HIDDEN_TOOLS.includes(e.tool_name || '')) {
        cur.tools.push(e);
      }
    }
  }
  if (cur) groups.push(cur);
  return groups;
}

/** 工具折叠块标签: "tool1, tool2 ×2" */
function buildToolLabel(toolNames: string[], isActive?: boolean): string {
  if (toolNames.length === 0) return '工具调用';
  const counts = new Map<string, number>();
  for (const n of toolNames) counts.set(n, (counts.get(n) || 0) + 1);
  const tp: string[] = [];
  for (const [name, count] of counts) tp.push(count > 1 ? `${name} ×${count}` : name);
  let label: string;
  if (tp.length <= 3) label = tp.join(', ');
  else label = `${tp.slice(0, 2).join(', ')} 等 ${toolNames.length} 个工具`;
  if (isActive) label += '...';
  return label;
}

/** 检查 timeline 是否包含 text 条目 (有则抑制 message body 避免重复) */
function timelineHasText(entries: TimelineEntry[] | ChatTimelineEntry[] | undefined): boolean {
  if (!entries || entries.length === 0) return false;
  return entries.some((e) => e.type === 'text' && e.content);
}

// ── 实时时间线: thinking→折叠块, text→正文, tools→折叠块 ──
function AgentTimeline() {
  const timelineEntries = usePipelineStore((s) => s.timelineEntries) as TimelineEntry[];
  const pipelineStatus = usePipelineStore((s) => s.status);

  if (!timelineEntries || timelineEntries.length === 0) return null;

  const groups = groupByIteration(timelineEntries);
  if (groups.length === 0) return null;

  const isActive = pipelineStatus === 'running';

  return (
    <>
      {groups.map((g, gi) => {
        const isLastGroup = gi === groups.length - 1;
        const hasThinking = !!g.thinking;
        const hasText = !!g.text;
        const hasTools = g.tools.length > 0;
        if (!hasThinking && !hasText && !hasTools) return null;

        return (
          <React.Fragment key={g.id}>
            {/* thinking → 折叠块 */}
            {hasThinking && (
              <div style={{ marginBottom: hasText || hasTools ? 4 : 12 }}>
                <CollapsibleBlock
                  icon={<BulbOutlined style={{ color: '#8c8c8c', fontSize: 12 }} />}
                  summary="思考过程"
                >
                  <div style={{ fontSize: 12, color: '#666', whiteSpace: 'pre-wrap' }}>{g.thinking}</div>
                </CollapsibleBlock>
              </div>
            )}
            {/* text → 正文 (ReactMarkdown) */}
            {hasText && (
              <div className="msg-ai markdown-body" style={{ marginBottom: hasTools ? 4 : 12 }}>
                <Markdown remarkPlugins={REMARK_PLUGINS}>{g.text!}</Markdown>
              </div>
            )}
            {/* tools → 折叠块 */}
            {hasTools && (
              <div style={{ marginBottom: 12 }}>
                <CollapsibleBlock
                  icon={
                    isActive && isLastGroup
                      ? <ToolOutlined style={{ color: '#722ed1', fontSize: 12 }} />
                      : <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
                  }
                  summary={buildToolLabel(g.tools.map((t) => t.toolName), isActive && isLastGroup)}
                >
                  {g.tools.map((te) => (
                    <ToolExecutionItem key={te.id} te={te} />
                  ))}
                </CollapsibleBlock>
              </div>
            )}
          </React.Fragment>
        );
      })}
    </>
  );
}

// ── 持久化时间线 ──
// showText=false(默认): 只渲染 thinking + tools，正文由 MessageItem 负责
// showText=true: 也渲染 text entries (当 msg.content 为空时，text 是唯一内容来源)
function PersistedTimeline({ entries, showText = false }: { entries: ChatTimelineEntry[]; showText?: boolean }) {
  if (!entries || entries.length === 0) return null;

  const groups = groupPersistedByIteration(entries);
  if (groups.length === 0) return null;

  return (
    <>
      {groups.map((g) => {
        const hasThinking = !!g.thinking;
        const hasText = showText && !!g.text?.trim();
        const hasTools = g.tools.length > 0;
        if (!hasThinking && !hasText && !hasTools) return null;

        return (
          <React.Fragment key={g.id}>
            {hasThinking && (
              <div style={{ marginBottom: (hasText || hasTools) ? 4 : 12 }}>
                <CollapsibleBlock
                  icon={<BulbOutlined style={{ color: '#8c8c8c', fontSize: 12 }} />}
                  summary="思考过程"
                >
                  <div style={{ fontSize: 12, color: '#666', whiteSpace: 'pre-wrap' }}>{g.thinking}</div>
                </CollapsibleBlock>
              </div>
            )}
            {hasText && (
              <div className="msg-ai markdown-body" style={{ marginBottom: hasTools ? 4 : 12 }}>
                <Markdown remarkPlugins={REMARK_PLUGINS}>{g.text!}</Markdown>
              </div>
            )}
            {hasTools && (
              <div style={{ marginBottom: 12 }}>
                <CollapsibleBlock
                  icon={<CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />}
                  summary={buildToolLabel(g.tools.map((t) => t.tool_name || ''))}
                >
                  {g.tools.map((te, ti) => (
                    <div key={ti} style={{ padding: '3px 0', fontSize: 11, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
                      <span style={{ flexShrink: 0, marginTop: 1 }}>
                        {te.blocked ? (
                          <StopOutlined style={{ color: '#faad14', fontSize: 11 }} />
                        ) : te.success ? (
                          <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
                        ) : (
                          <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />
                        )}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ fontWeight: 500, color: '#333' }}>{te.tool_name}</span>
                        {te.latency_ms != null && (
                          <span style={{ color: '#999', marginLeft: 4 }}>({Math.round(te.latency_ms)}ms)</span>
                        )}
                        {te.args_summary && Object.keys(te.args_summary).length > 0 && (
                          <div style={{ color: '#888', fontSize: 10 }}>
                            {'→ '}
                            {Object.entries(te.args_summary).map(([k, v]) => `${k}=${v}`).join(', ')}
                          </div>
                        )}
                        {te.result_summary && (
                          <div style={{ color: '#666', fontSize: 10 }}>
                            {'← '}{te.result_summary}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </CollapsibleBlock>
              </div>
            )}
          </React.Fragment>
        );
      })}
    </>
  );
}

// ── 文件附件渲染 ──

function isImageFile(file: ChatMessageFile): boolean {
  if (file.contentType?.startsWith('image/')) return true;
  const ext = file.filename.split('.').pop()?.toLowerCase() || '';
  return ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext);
}

function getFileIcon(file: ChatMessageFile) {
  const ext = file.filename.split('.').pop()?.toLowerCase() || '';
  if (isImageFile(file)) return <FileImageOutlined style={{ color: '#1890ff' }} />;
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#ff4d4f' }} />;
  if (['doc', 'docx'].includes(ext)) return <FileWordOutlined style={{ color: '#2f54eb' }} />;
  if (['xls', 'xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#52c41a' }} />;
  if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext)) return <FileZipOutlined style={{ color: '#faad14' }} />;
  return <FileOutlined style={{ color: '#8c8c8c' }} />;
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileDownloadUrl(fileId: string): string {
  return `${getAIConfig().aiBaseUrl}/api/files/${fileId}/download`;
}

function getFileTextUrl(fileId: string): string {
  return `${getAIConfig().aiBaseUrl}/api/files/${fileId}/text`;
}

/** 带认证的文件 URL 获取 (img 标签不支持 Authorization header) */
function useAuthBlobUrl(fileId: string) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const blobRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = getAIConfig();
        const headers: Record<string, string> = {};
        if (config.getAuthToken) {
          const token = await config.getAuthToken();
          if (token) headers['Authorization'] = `Bearer ${token}`;
        } else if (config.authToken) {
          headers['Authorization'] = `Bearer ${config.authToken}`;
        }
        const res = await fetch(getFileDownloadUrl(fileId), { headers });
        if (!res.ok) { setError(true); return; }
        const blob = await res.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        blobRef.current = url;
        setBlobUrl(url);
      } catch {
        setError(true);
      }
    })();
    return () => {
      cancelled = true;
      if (blobRef.current) URL.revokeObjectURL(blobRef.current);
    };
  }, [fileId]); // eslint-disable-line react-hooks/exhaustive-deps

  return { blobUrl, error };
}

function ImageThumb({ file, onClick }: { file: ChatMessageFile; onClick: () => void }) {
  const { blobUrl, error } = useAuthBlobUrl(file.fileId);
  const [imgError, setImgError] = useState(false);
  const showFallback = error || imgError;
  return (
    <div
      style={{
        position: 'relative', width: 160, height: 120, borderRadius: 10,
        overflow: 'hidden', border: '1px solid #e0e0e0', cursor: 'pointer',
        background: '#f8f9fa', transition: 'box-shadow 0.2s, transform 0.15s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.08)';
        e.currentTarget.style.transform = 'none';
      }}
    >
      {blobUrl && !showFallback ? (
        <img
          src={blobUrl}
          alt={file.filename}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setImgError(true)}
        />
      ) : showFallback ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 4, height: '100%' }}>
          <FileImageOutlined style={{ fontSize: 28, color: '#bfbfbf' }} />
          <span style={{ fontSize: 10, color: '#999', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '0 6px' }}>{file.filename}</span>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
          <Spin size="small" />
        </div>
      )}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        background: 'linear-gradient(transparent, rgba(0,0,0,0.55))',
        padding: '16px 8px 6px', color: '#fff', fontSize: 11,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {file.filename}
      </div>
      {/* Hover overlay with eye icon */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'rgba(0,0,0,0.15)', opacity: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'opacity 0.2s',
      }}
        onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
        onMouseLeave={(e) => { e.currentTarget.style.opacity = '0'; }}
      >
        <EyeOutlined style={{ fontSize: 22, color: '#fff', filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.3))' }} />
      </div>
    </div>
  );
}

/** 判断是否可以在浏览器中预览 */
function isPdfFile(file: ChatMessageFile): boolean {
  if (file.contentType === 'application/pdf') return true;
  return file.filename.toLowerCase().endsWith('.pdf');
}

function isTextFile(file: ChatMessageFile): boolean {
  if (file.contentType?.startsWith('text/')) return true;
  const ext = file.filename.split('.').pop()?.toLowerCase() || '';
  return ['txt', 'csv', 'json', 'xml', 'yaml', 'yml', 'md', 'log', 'ini', 'conf'].includes(ext);
}

/** 获取认证 headers */
async function getAuthHeaders(): Promise<Record<string, string>> {
  const config = getAIConfig();
  const headers: Record<string, string> = {};
  if (config.getAuthToken) {
    const token = await config.getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }
  return headers;
}

/** 通用文件预览 Modal — 图片/PDF/文本 */
function FilePreviewModal({ file, onClose }: { file: ChatMessageFile; onClose: () => void }) {
  const { blobUrl } = useAuthBlobUrl(file.fileId);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isImg = isImageFile(file);
  const isPdf = isPdfFile(file);
  const isTxt = isTextFile(file);

  // 文本文件: 先尝试 /text 端点，失败则直接下载原文
  useEffect(() => {
    if (!isTxt || isImg) return;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const headers = await getAuthHeaders();
        // 优先 /text 端点
        let text = '';
        try {
          const textRes = await fetch(getFileTextUrl(file.fileId), { headers });
          if (textRes.ok) {
            const data = await textRes.json();
            text = data.text || '';
          }
        } catch { /* /text endpoint failed, try raw download */ }
        // 为空则直接读取原始文件
        if (!text) {
          const rawRes = await fetch(getFileDownloadUrl(file.fileId), { headers });
          if (rawRes.ok) text = await rawRes.text();
        }
        setTextContent(text || '(文件内容为空)');
      } catch {
        setError('无法加载文件内容');
      }
      setLoading(false);
    })();
  }, [file.fileId, isTxt, isImg]);

  return (
    <Modal
      open
      footer={null}
      onCancel={onClose}
      width={isPdf ? '80vw' : isTxt ? 720 : 'auto'}
      style={{ maxWidth: '90vw' }}
      styles={{ body: { padding: isPdf ? 0 : undefined } }}
      centered
      title={file.filename}
    >
      {isImg && blobUrl && (
        <img src={blobUrl} alt={file.filename} style={{ maxWidth: '100%', maxHeight: '80vh', objectFit: 'contain', display: 'block', margin: '0 auto' }} />
      )}
      {isPdf && blobUrl && (
        <iframe
          src={blobUrl}
          style={{ width: '100%', height: '80vh', border: 'none' }}
          title={file.filename}
        />
      )}
      {isTxt && !isImg && (
        loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : error ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#ff4d4f' }}>
            <CloseCircleOutlined style={{ fontSize: 32, marginBottom: 8, display: 'block' }} />
            {error}
          </div>
        ) : (
          <pre style={{
            maxHeight: '70vh', overflow: 'auto', padding: 16,
            background: '#fafafa', borderRadius: 6, fontSize: 13,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            lineHeight: 1.6,
          }}>
            {textContent ?? ''}
          </pre>
        )
      )}
      {!isImg && !isPdf && !isTxt && (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
          <FileOutlined style={{ fontSize: 48, marginBottom: 12, display: 'block' }} />
          <div>该文件类型不支持预览</div>
          <Button
            type="link"
            style={{ marginTop: 8 }}
            onClick={async () => {
              const headers = await getAuthHeaders();
              const res = await fetch(getFileDownloadUrl(file.fileId), { headers });
              if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = file.filename;
                a.click();
                URL.revokeObjectURL(url);
              }
            }}
          >下载文件</Button>
        </div>
      )}
      {!blobUrl && (isImg || isPdf) && (
        <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
      )}
    </Modal>
  );
}

/** 文件类型对应的背景色 */
function getFileColor(file: ChatMessageFile): { bg: string; border: string; iconColor: string } {
  const ext = file.filename.split('.').pop()?.toLowerCase() || '';
  if (isImageFile(file)) return { bg: '#e6f7ff', border: '#91d5ff', iconColor: '#1890ff' };
  if (ext === 'pdf') return { bg: '#fff1f0', border: '#ffa39e', iconColor: '#ff4d4f' };
  if (['doc', 'docx'].includes(ext)) return { bg: '#f0f5ff', border: '#adc6ff', iconColor: '#2f54eb' };
  if (['xls', 'xlsx', 'csv'].includes(ext)) return { bg: '#f6ffed', border: '#b7eb8f', iconColor: '#52c41a' };
  if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext)) return { bg: '#fffbe6', border: '#ffe58f', iconColor: '#faad14' };
  return { bg: '#fafafa', border: '#e8e8e8', iconColor: '#8c8c8c' };
}

function FileAttachments({ files }: { files: ChatMessageFile[] }) {
  const [previewFile, setPreviewFile] = useState<ChatMessageFile | null>(null);
  const images = files.filter(isImageFile);
  const others = files.filter((f) => !isImageFile(f));

  return (
    <div style={{ marginTop: 10 }}>
      {/* 图片预览网格 */}
      {images.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: others.length > 0 ? 10 : 0 }}>
          {images.map((file) => (
            <ImageThumb key={file.fileId} file={file} onClick={() => setPreviewFile(file)} />
          ))}
        </div>
      )}

      {/* 非图片文件卡片 */}
      {others.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {others.map((file) => {
            const colors = getFileColor(file);
            return (
              <div
                key={file.fileId}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 14px', minWidth: 180, maxWidth: 280,
                  background: colors.bg, borderRadius: 10,
                  border: `1px solid ${colors.border}`, fontSize: 12,
                  cursor: 'pointer', transition: 'box-shadow 0.2s, transform 0.15s',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                }}
                onClick={() => setPreviewFile(file)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.boxShadow = '0 3px 10px rgba(0,0,0,0.12)';
                  e.currentTarget.style.transform = 'translateY(-1px)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
                  e.currentTarget.style.transform = 'none';
                }}
              >
                <div style={{ fontSize: 22, lineHeight: 1, flexShrink: 0 }}>
                  {getFileIcon(file)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontWeight: 500, color: '#262626',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    fontSize: 13, lineHeight: '18px',
                  }}>
                    {file.filename}
                  </div>
                  {file.sizeBytes != null && (
                    <div style={{ color: '#8c8c8c', fontSize: 11, marginTop: 1 }}>
                      {formatFileSize(file.sizeBytes)}
                    </div>
                  )}
                </div>
                <EyeOutlined style={{ color: colors.iconColor, fontSize: 14, flexShrink: 0, opacity: 0.7 }} />
              </div>
            );
          })}
        </div>
      )}

      {/* 文件预览 Modal */}
      {previewFile && (
        <FilePreviewModal file={previewFile} onClose={() => setPreviewFile(null)} />
      )}
    </div>
  );
}

// ── 单条消息组件 (memo 避免无关消息重渲染) ──

const MessageItem = memo(function MessageItem({ msg }: { msg: ChatMessage }) {
  return (
    <div style={{ marginBottom: 16 }}>
      {msg.role === 'user' ? (
        <div className="msg-user-row">
          <div>
            <div className="msg-user">
              <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
            </div>
            {msg.files && msg.files.length > 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                <FileAttachments files={msg.files} />
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="msg-ai markdown-body">
          <Markdown remarkPlugins={REMARK_PLUGINS}>{msg.content}</Markdown>
        </div>
      )}
    </div>
  );
});

// ── 主组件 ──

export default function ChatMessageList({
  messages,
  showPipelineProgress = true,
  onInteractionRespond,
}: ChatMessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const pipelineStatus = usePipelineStore((s) => s.status);
  const pipelineScenario = usePipelineStore((s) => s.scenario);
  const thinkingText = usePipelineStore((s) => s.thinkingText);
  const liveTimelineEntries = usePipelineStore((s) => s.timelineEntries) as TimelineEntry[];
  const pendingInteraction = usePipelineStore((s) => s.pendingInteraction) as PendingInteraction | null;
  const resolveInteraction = usePipelineStore((s) => s.resolveInteraction);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, pipelineStatus, thinkingText]);

  // 找到最后一条用户消息的索引，用于定位时间线插入点
  const lastUserIdx = messages.reduce((acc, m, i) => (m.role === 'user' ? i : acc), -1);

  return (
    <div
      style={{
        flex: 1,
        overflow: 'auto',
        padding: '16px 24px 8px',
      }}
    >
      {messages.map((msg, idx) => {
        // 每条 assistant 消息前渲染其持久化的时间线 (历史数据)
        const hasPersistedTimeline = msg.role === 'assistant' && msg.timeline && msg.timeline.length > 0;
        // 实时时间线: 当 store 中有 entries 时优先使用 (保持交错布局，避免完成后跳动)
        const showLiveTimeline = idx === lastUserIdx + 1 && msg.role === 'assistant' && (liveTimelineEntries?.length ?? 0) > 0;
        // 持久化时间线: 仅当无实时数据时才使用 (加载历史 session 时)
        const showPersistedTimeline = hasPersistedTimeline && !showLiveTimeline;
        // 实时 timeline 有 text 条目时抑制 body (避免和 timeline 正文重复)
        // 不论 running/completed 都保持同样布局，防止完成瞬间元素跳动
        const suppressBody = msg.role === 'assistant' &&
          showLiveTimeline && timelineHasText(liveTimelineEntries);
        // 持久化时间线: 始终显示 text entries 保持交错布局 (与实时一致)
        // 当 timeline 有 text 时由 PersistedTimeline 负责渲染正文，抑制 MessageItem body 避免重复
        const persistedTimelineHasText = showPersistedTimeline && timelineHasText(msg.timeline);
        const persistedShowText = true;
        const suppressPersistedBody = persistedTimelineHasText;
        return (
          <React.Fragment key={msg.id}>
            {showPersistedTimeline && <PersistedTimeline entries={msg.timeline!} showText={persistedShowText} />}
            {showLiveTimeline && <AgentTimeline />}
            {!suppressBody && !suppressPersistedBody && <MessageItem msg={msg} />}
          </React.Fragment>
        );
      })}

      {/* 无 assistant 响应时 (pipeline 进行中)，实时时间线显示在消息末尾 */}
      {lastUserIdx === messages.length - 1 && <AgentTimeline />}

      {/* Pipeline 实时进度 — 折叠摘要 */}
      {showPipelineProgress && pipelineStatus !== 'idle' && pipelineScenario !== 'general_chat' && (
        <div style={{ marginBottom: 16 }}>
          <InlinePipelineProgress />
        </div>
      )}

      {/* Agent 交互请求 (内联上传 / 确认 / 输入) */}
      {pendingInteraction && (
        <div style={{ marginBottom: 16 }}>
          {pendingInteraction.type === 'upload' && (
            <InlineUploader
              prompt={pendingInteraction.prompt}
              accept={pendingInteraction.accept}
              onSubmit={(files) => {
                resolveInteraction();
                onInteractionRespond?.(
                  `[已上传 ${files.length} 个文件: ${files.map((f) => f.filename).join(', ')}]`,
                  files,
                );
              }}
            />
          )}
          {pendingInteraction.type === 'confirmation' && (
            <InteractiveMessage
              type="confirmation"
              message={pendingInteraction.message}
              options={pendingInteraction.options}
              onRespond={(value) => {
                resolveInteraction();
                onInteractionRespond?.(value);
              }}
            />
          )}
          {pendingInteraction.type === 'input' && (
            <InteractiveMessage
              type="input"
              prompt={pendingInteraction.prompt}
              fieldType={pendingInteraction.fieldType}
              onRespond={(value) => {
                resolveInteraction();
                onInteractionRespond?.(value);
              }}
            />
          )}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
