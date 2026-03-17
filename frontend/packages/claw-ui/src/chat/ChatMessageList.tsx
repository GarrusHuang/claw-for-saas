import React, { useEffect, useRef, useState, useCallback, memo } from 'react';
import { Typography, Spin } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  BulbOutlined,
  StopOutlined,
  FileImageOutlined,
  EyeOutlined,
  LoadingOutlined,
  DownOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import { usePipelineStore, getAIConfig } from '@claw/core';
import { MARKDOWN_COMPONENTS, REMARK_PLUGINS } from '../shared/markdownComponents';
import type { PendingInteraction, ToolExecution, TimelineEntry } from '@claw/core';
import InlineUploader from './InlineUploader';
import InteractiveMessage from './InteractiveMessage';
import CollapsibleBlock from './CollapsibleBlock';
import FileArtifactCard from '../preview/FileArtifactCard';
import UniversalFilePreviewModal from '../preview/FilePreviewModal';
import FileCard from './FileCard';
import { getToolLabel } from './toolLabels';
import HighlightedCode from '../shared/HighlightedCode';

import type { ChatMessage, ChatMessageFile, ChatTimelineEntry, FileArtifact } from '@claw/core';

const { Text } = Typography;

/** 简单检测 result_summary 内容的语言 (用于语法高亮) */
function tryDetectLang(text: string): string {
  const trimmed = text.trimStart();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
  if (trimmed.startsWith('<')) return 'xml';
  return 'json'; // 大多数工具结果是 dict/JSON 格式
}


interface ChatMessageListProps {
  messages: ChatMessage[];
  onInteractionRespond?: (value: string, files?: { fileId: string; filename: string }[]) => void;
}

// ── 工具调用折叠行 — 逐条嵌入文档流 ──

// ── 单个工具执行行 ──
function ToolExecutionItem({ te }: { te: ToolExecution }) {
  const label = getToolLabel(te.toolName);
  const [showResult, setShowResult] = useState(false);
  const hasDetails = !!(te.argsSummary && Object.keys(te.argsSummary).length > 0) || !!te.resultSummary;
  return (
    <div style={{ padding: '4px 0' }}>
      {/* 工具名行 — 图标 + 中文名 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
        <span style={{ flexShrink: 0 }}>
          {te.pending ? (
            <LoadingOutlined style={{ color: '#722ed1', fontSize: 13 }} />
          ) : te.blocked ? (
            <StopOutlined style={{ color: '#faad14', fontSize: 13 }} />
          ) : te.success ? (
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />
          ) : (
            <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} />
          )}
        </span>
        <span style={{ fontWeight: 500, color: '#333' }}>{label}</span>
        {te.pending && <span style={{ color: '#722ed1', fontSize: 11 }}>执行中...</span>}
      </div>
      {/* Result 区域 — 左竖线 + 可点击展开 */}
      {!te.pending && (
        <div style={{ marginLeft: 7, paddingLeft: 14, borderLeft: '2px solid #e8e8e8', marginTop: 2 }}>
          <span
            role={hasDetails ? 'button' : undefined}
            tabIndex={hasDetails ? 0 : undefined}
            onClick={hasDetails ? () => setShowResult((v) => !v) : undefined}
            onKeyDown={hasDetails ? (e) => { if (e.key === 'Enter' || e.key === ' ') setShowResult((v) => !v); } : undefined}
            style={{
              display: 'inline-block', fontSize: 11, color: '#999',
              background: '#f5f5f5', borderRadius: 4, padding: '1px 6px',
              cursor: hasDetails ? 'pointer' : 'default',
              userSelect: 'none',
            }}
          >
            Result
            {hasDetails && <span style={{ marginLeft: 3, fontSize: 10 }}>{showResult ? '▾' : '▸'}</span>}
          </span>
          {te.latencyMs > 0 && (
            <span style={{ color: '#bbb', fontSize: 11, marginLeft: 6 }}>{Math.round(te.latencyMs)}ms</span>
          )}
          {showResult && (
            <div style={{ marginTop: 4 }}>
              {te.argsSummary && Object.keys(te.argsSummary).length > 0 && (
                <div style={{ marginBottom: te.resultSummary ? 6 : 0 }}>
                  <HighlightedCode code={JSON.stringify(te.argsSummary, null, 2)} language="json" maxHeight="200px" />
                </div>
              )}
              {te.resultSummary && (
                <HighlightedCode code={te.resultSummary} language={tryDetectLang(te.resultSummary)} maxHeight="300px" />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 按迭代分组 — 对标 Claude Code: thinking→折叠块, text→正文, tools→折叠块 ──
const HIDDEN_TOOLS: string[] = [];

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

/** 工具折叠块摘要 — 动态状态前缀 + 中文工具名 + 计数 */
function buildToolSummary(
  toolNames: string[],
  opts: { hasPending?: boolean; hasFailed?: boolean },
): string {
  if (toolNames.length === 0) return '工具调用';
  const counts = new Map<string, number>();
  for (const n of toolNames) {
    const label = getToolLabel(n);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const tp: string[] = [];
  for (const [label, count] of counts) tp.push(count > 1 ? `${label} \u00d7${count}` : label);
  let text: string;
  if (tp.length <= 3) text = tp.join(', ');
  else text = `${tp.slice(0, 2).join(', ')} 等 ${toolNames.length} 个工具`;

  if (opts.hasFailed) return `${text} (失败)`;
  if (opts.hasPending) return `${text}...`;
  return text;
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
              <div className="msg-ai prose" style={{ marginBottom: hasTools ? 4 : 12 }}>
                <Markdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>{g.text!}</Markdown>
              </div>
            )}
            {/* tools → 折叠块 (所有工具统一渲染) */}
            {hasTools && (() => {
              const hasPending = g.tools.some((t) => t.pending);
              const hasFailed = g.tools.some((t) => !t.pending && !t.success);
              const allDone = !hasPending && !(isActive && isLastGroup);
              const statusEmoji = hasFailed ? '❌' : hasPending || (isActive && isLastGroup) ? '🔄' : '✅';
              return (
                <div style={{ marginBottom: 12 }}>
                  <CollapsibleBlock
                    summary={`${statusEmoji} ${buildToolSummary(g.tools.map((t) => t.toolName), { hasPending: hasPending || (isActive && isLastGroup), hasFailed })}`}
                  >
                    {g.tools.map((te) => (
                      <ToolExecutionItem key={te.id} te={te} />
                    ))}
                    {allDone && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12, color: '#8c8c8c' }}>
                        <CheckCircleOutlined style={{ fontSize: 13 }} />
                        <span style={{ fontWeight: 500 }}>Done</span>
                      </div>
                    )}
                  </CollapsibleBlock>
                </div>
              );
            })()}
          </React.Fragment>
        );
      })}
    </>
  );
}

// ── 持久化时间线 ──
// showText=false(默认): 只渲染 thinking + tools，正文由 MessageItem 负责
// showText=true: 也渲染 text entries (当 msg.content 为空时，text 是唯一内容来源)
/** 持久化工具条目 — 点击 Result 展开详情 */
function PersistedToolItem({ te }: { te: ChatTimelineEntry }) {
  const label = getToolLabel(te.tool_name || '');
  const [showResult, setShowResult] = useState(false);
  const hasDetails = !!(te.args_summary && Object.keys(te.args_summary).length > 0) || !!te.result_summary;
  return (
    <div style={{ padding: '4px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
        <span style={{ flexShrink: 0 }}>
          {te.blocked ? (
            <StopOutlined style={{ color: '#faad14', fontSize: 13 }} />
          ) : te.success ? (
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />
          ) : (
            <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} />
          )}
        </span>
        <span style={{ fontWeight: 500, color: '#333' }}>{label}</span>
      </div>
      <div style={{ marginLeft: 7, paddingLeft: 14, borderLeft: '2px solid #e8e8e8', marginTop: 2 }}>
        <span
          role={hasDetails ? 'button' : undefined}
          tabIndex={hasDetails ? 0 : undefined}
          onClick={hasDetails ? () => setShowResult((v) => !v) : undefined}
          onKeyDown={hasDetails ? (e) => { if (e.key === 'Enter' || e.key === ' ') setShowResult((v) => !v); } : undefined}
          style={{
            display: 'inline-block', fontSize: 11, color: '#999',
            background: '#f5f5f5', borderRadius: 4, padding: '1px 6px',
            cursor: hasDetails ? 'pointer' : 'default',
            userSelect: 'none',
          }}
        >
          Result
          {hasDetails && <span style={{ marginLeft: 3, fontSize: 10 }}>{showResult ? '▾' : '▸'}</span>}
        </span>
        {te.latency_ms != null && te.latency_ms > 0 && (
          <span style={{ color: '#bbb', fontSize: 11, marginLeft: 6 }}>{Math.round(te.latency_ms)}ms</span>
        )}
        {showResult && (
          <div style={{ marginTop: 4 }}>
            {te.args_summary && Object.keys(te.args_summary).length > 0 && (
              <div style={{ marginBottom: te.result_summary ? 6 : 0 }}>
                <HighlightedCode code={JSON.stringify(te.args_summary, null, 2)} language="json" maxHeight="200px" />
              </div>
            )}
            {te.result_summary && (
              <HighlightedCode code={te.result_summary} language={tryDetectLang(te.result_summary)} maxHeight="300px" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

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
              <div className="msg-ai prose" style={{ marginBottom: hasTools ? 4 : 12 }}>
                <Markdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>{g.text!}</Markdown>
              </div>
            )}
            {hasTools && (() => {
              const hasFailed = g.tools.some((t) => !t.success);
              const statusEmoji = hasFailed ? '❌' : '✅';
              return (
                <div style={{ marginBottom: 12 }}>
                  <CollapsibleBlock
                    summary={`${statusEmoji} ${buildToolSummary(g.tools.map((t) => t.tool_name || ''), { hasFailed })}`}
                  >
                    {g.tools.map((te, ti) => (
                      <PersistedToolItem key={ti} te={te} />
                    ))}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12, color: '#8c8c8c' }}>
                      <CheckCircleOutlined style={{ fontSize: 13 }} />
                      <span style={{ fontWeight: 500 }}>Done</span>
                    </div>
                  </CollapsibleBlock>
                </div>
              );
            })()}
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

/* Local FilePreviewModal removed — using UniversalFilePreviewModal from ../preview/FilePreviewModal */

function FileAttachments({ files }: { files: ChatMessageFile[] }) {
  const [previewFile, setPreviewFile] = useState<ChatMessageFile | null>(null);
  const images = files.filter(isImageFile);
  const others = files.filter((f) => !isImageFile(f));

  return (
    <div style={{ marginTop: 10 }}>
      {/* 图片预览网格 */}
      {images.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: others.length > 0 ? 10 : 0, justifyContent: 'flex-end' }}>
          {images.map((file) => (
            <ImageThumb key={file.fileId} file={file} onClick={() => setPreviewFile(file)} />
          ))}
        </div>
      )}

      {/* 非图片文件 — FileCard 卡片 */}
      {others.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
          {others.map((file) => (
            <FileCard
              key={file.fileId}
              file={file}
              onPreview={() => setPreviewFile(file)}
            />
          ))}
        </div>
      )}

      {/* 文件预览 Modal */}
      {previewFile && (
        <UniversalFilePreviewModal
          open={true}
          fileId={previewFile.fileId}
          filename={previewFile.filename}
          onClose={() => setPreviewFile(null)}
          hideDownload={true}
        />
      )}
    </div>
  );
}

// ── 单条消息组件 (memo 避免无关消息重渲染) ──

const MessageItem = memo(function MessageItem({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
        <div className="msg-user">{msg.content}</div>
        {msg.files && msg.files.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <FileAttachments files={msg.files} />
          </div>
        )}
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="msg-ai prose">
        <Markdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>{msg.content}</Markdown>
      </div>
    </div>
  );
});

// ── Timeline 渲染模式判断 ──

type TimelineMode =
  | { type: 'live' }
  | { type: 'persisted'; entries: ChatTimelineEntry[] }
  | { type: 'none' };

function computeTimelineMode(
  msg: ChatMessage,
  idx: number,
  lastUserIdx: number,
  liveEntries: TimelineEntry[],
): TimelineMode {
  if (msg.role !== 'assistant') return { type: 'none' };
  // 实时 timeline：仅最后一条用户消息后的 assistant 消息
  if (idx === lastUserIdx + 1 && liveEntries.length > 0) {
    return { type: 'live' };
  }
  // 持久化 timeline：历史消息自带的 timeline
  if (msg.timeline && msg.timeline.length > 0) {
    return { type: 'persisted', entries: msg.timeline };
  }
  return { type: 'none' };
}

// ── 主组件 ──

export default function ChatMessageList({
  messages,
  onInteractionRespond,
}: ChatMessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const pipelineStatus = usePipelineStore((s) => s.status);
  const thinkingText = usePipelineStore((s) => s.thinkingText);
  const liveTimelineEntries = usePipelineStore((s) => s.timelineEntries) as TimelineEntry[];
  const pendingInteraction = usePipelineStore((s) => s.pendingInteraction) as PendingInteraction | null;
  const resolveInteraction = usePipelineStore((s) => s.resolveInteraction);
  const fileArtifacts = usePipelineStore((s) => s.fileArtifacts) as FileArtifact[];

  // ── 切换会话时重置滚动状态 ──
  const sessionKey = messages.length > 0 ? messages[0].id : '';
  useEffect(() => {
    isNearBottomRef.current = true;
    setShowScrollBtn(false);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [sessionKey]);

  // ── 智能自动滚动 ──
  // 用户在底部附近 → 新内容来了自动滚底
  // 用户往上翻了 → 停止自动滚动，显示「跳到最新」按钮

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    isNearBottomRef.current = nearBottom;
    setShowScrollBtn(!nearBottom);
  }, []);

  // MutationObserver: DOM 变化时如果在底部就自动滚（rAF 节流）
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let rafId: number | null = null;
    const scrollIfNeeded = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (isNearBottomRef.current && el) {
          el.scrollTop = el.scrollHeight;
        }
      });
    };
    const observer = new MutationObserver(scrollIfNeeded);
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    isNearBottomRef.current = true;
    setShowScrollBtn(false);
  }, []);

  // 找到最后一条用户消息的索引，用于定位时间线插入点
  const lastUserIdx = messages.reduce((acc, m, i) => (m.role === 'user' ? i : acc), -1);

  return (
    <div style={{ flex: 1, position: 'relative', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          padding: '16px 24px 8px',
        }}
      >
        {messages.map((msg, idx) => {
          const mode = computeTimelineMode(msg, idx, lastUserIdx, liveTimelineEntries);
          const hasTimelineText = mode.type === 'live'
            ? timelineHasText(liveTimelineEntries)
            : mode.type === 'persisted'
              ? timelineHasText(mode.entries)
              : false;

          return (
            <React.Fragment key={msg.id}>
              {mode.type === 'persisted' && <PersistedTimeline entries={mode.entries} showText={true} />}
              {mode.type === 'live' && <AgentTimeline />}
              {!hasTimelineText && <MessageItem msg={msg} />}
              {/* 该消息关联的文件制品 — 内联显示 */}
              {msg.fileArtifacts && msg.fileArtifacts.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  {msg.fileArtifacts.map((artifact, i) => (
                    <FileArtifactCard key={`${artifact.path}-${i}`} artifact={artifact} />
                  ))}
                </div>
              )}
            </React.Fragment>
          );
        })}

        {/* 无 assistant 响应时 (pipeline 进行中)，实时时间线显示在消息末尾 */}
        {lastUserIdx === messages.length - 1 && <AgentTimeline />}

        {/* 实时生成的文件 — 仅 pipeline 运行中显示 (完成后会附加到消息上) */}
        {pipelineStatus === 'running' && fileArtifacts.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            {fileArtifacts.map((artifact, i) => (
              <FileArtifactCard key={`${artifact.path}-${i}`} artifact={artifact} />
            ))}
          </div>
        )}

        {/* 运行指示器: pipeline 运行中但 timeline 还没有内容时显示 */}
        {pipelineStatus === 'running' && (liveTimelineEntries?.length ?? 0) === 0 &&
         lastUserIdx === messages.length - 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
            <Spin size="small" />
            <Text type="secondary" style={{ fontSize: 12 }}>Agent 处理中...</Text>
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

      {/* 跳到最新内容 */}
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          aria-label="跳到最新"
          style={{
            position: 'absolute',
            bottom: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 10,
            width: 36,
            height: 36,
            borderRadius: '50%',
            border: 'none',
            background: 'rgba(22,119,255,0.9)',
            boxShadow: '0 2px 10px rgba(22,119,255,0.35)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'transform 0.15s, box-shadow 0.15s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateX(-50%) scale(1.1)'; e.currentTarget.style.boxShadow = '0 4px 14px rgba(22,119,255,0.45)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateX(-50%)'; e.currentTarget.style.boxShadow = '0 2px 10px rgba(22,119,255,0.35)'; }}
        >
          <DownOutlined style={{ fontSize: 16, color: '#fff' }} />
        </button>
      )}
    </div>
  );
}
