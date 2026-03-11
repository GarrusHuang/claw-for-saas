import { useEffect, useRef } from 'react';
import { Typography, Spin, Button } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  BulbOutlined,
  ToolOutlined,
  StopOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { usePipelineStore } from '@claw/core';
import type { PendingInteraction, ToolExecution } from '@claw/core';
import {
  MiniTypeInference,
  MiniFieldUpdates,
  MiniAuditSummary,
} from './ChatResultCards';
import DocumentPresenter from '../results/DocumentPresenter';
import InlineUploader from './InlineUploader';
import InteractiveMessage from './InteractiveMessage';
import CollapsibleBlock from './CollapsibleBlock';

const { Text } = Typography;

/** 聊天消息类型 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
}

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
  const isPlanAwaiting = plan.requiresApproval && status === 'plan_awaiting';
  const isConfirmed = plan.requiresApproval && status !== 'plan_awaiting' && status !== 'idle';

  // 是否有完整的 Markdown 文档
  const hasDetail = !!plan.detail && plan.detail.trim().length > 0;

  return (
    <div className="plan-document">
      {/* ── 文档头部 ── */}
      <div className="plan-document-header">
        <div className="plan-document-title-row">
          <ThunderboltOutlined style={{ color: '#fa8c16', fontSize: 16 }} />
          <span className="plan-document-title">执行方案</span>
          {isPlanAwaiting && (
            <span className="plan-document-badge plan-document-badge--awaiting">待确认</span>
          )}
          {isConfirmed && (
            <span className="plan-document-badge plan-document-badge--confirmed">执行中</span>
          )}
          {!plan.requiresApproval && (
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
          <Markdown remarkPlugins={[remarkGfm]}>{plan.detail}</Markdown>
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
        {isConfirmed && (
          <div className="plan-document-actions">
            <Text type="success" style={{ fontSize: 12 }}>
              <CheckCircleOutlined style={{ marginRight: 4 }} />
              已确认，正在执行...
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
  if (toolExecutions.length > 0) parts.push(`Ran ${toolExecutions.length} tools`);
  if (fieldValues.length > 0) parts.push(`filled ${fieldValues.length} fields`);
  if (inferredType) parts.push(`type: ${inferredType.docType}`);
  if (auditSummary) parts.push(`audit: ${auditSummary.conclusion}`);
  if (document) parts.push(`doc: ${document.title}`);
  const summaryText = parts.length > 0 ? parts.join(', ') : 'Processing...';

  return (
    <div>
      {/* PlanCard — Agent 提出的方案 */}
      <PlanCard />

      {/* Pipeline progress as collapsible */}
      <CollapsibleBlock
        icon={<ThunderboltOutlined style={{ color: '#fa8c16', fontSize: 12 }} />}
        summary={status === 'running' ? `Agent working — ${summaryText}` : summaryText}
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

      {/* Plan Mode 等待确认 */}
      {status === 'plan_awaiting' && (
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Text type="warning" style={{ fontSize: 11 }}>
            <ClockCircleOutlined style={{ color: '#faad14', marginRight: 4 }} />
            方案待确认
          </Text>
        </div>
      )}

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

function ToolExecutionLog() {
  const toolExecutions = usePipelineStore((s) => s.toolExecutions) as ToolExecution[];

  if (toolExecutions.length === 0) return null;

  // 构建一行汇总
  const summaryParts: string[] = [];
  const toolNames = new Set(toolExecutions.map((te) => te.toolName));
  summaryParts.push(`Ran ${toolExecutions.length} command${toolExecutions.length > 1 ? 's' : ''}`);

  // 提取文件相关操作
  const fileOps = toolExecutions.filter(
    (te) => te.argsSummary && (te.argsSummary.file_path || te.argsSummary.filename || te.argsSummary.path),
  );
  if (fileOps.length > 0) summaryParts.push(`touched ${fileOps.length} file${fileOps.length > 1 ? 's' : ''}`);

  const blocked = toolExecutions.filter((te) => te.blocked);
  if (blocked.length > 0) summaryParts.push(`${blocked.length} blocked`);

  return (
    <div style={{ marginBottom: 16 }}>
      <CollapsibleBlock
        icon={<ToolOutlined style={{ color: '#722ed1', fontSize: 12 }} />}
        summary={summaryParts.join(', ')}
      >
        {toolExecutions.map((te) => (
          <div key={te.id} style={{ padding: '3px 0', fontSize: 11, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
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
        ))}
      </CollapsibleBlock>
    </div>
  );
}

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
  const isStreaming = usePipelineStore((s) => s.isStreaming);
  const pendingInteraction = usePipelineStore((s) => s.pendingInteraction) as PendingInteraction | null;
  const resolveInteraction = usePipelineStore((s) => s.resolveInteraction);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, pipelineStatus, thinkingText]);

  return (
    <div
      style={{
        flex: 1,
        overflow: 'auto',
        padding: '16px 24px 8px',
      }}
    >
      {messages.map((msg) => (
        <div key={msg.id} style={{ marginBottom: 16 }}>
          {msg.role === 'user' ? (
            /* 用户消息 — 左对齐 + 左边框 */
            <div className="msg-user">
              <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{msg.content}</Text>
            </div>
          ) : (
            /* AI 消息 — 纯文档流 */
            <div className="msg-ai markdown-body">
              <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
            </div>
          )}
        </div>
      ))}

      {/* 思考过程 — 始终可见但默认折叠 */}
      {thinkingText && (isStreaming || pipelineStatus === 'running') && (
        <div style={{ marginBottom: 16 }}>
          <CollapsibleBlock
            icon={<BulbOutlined style={{ color: '#faad14', fontSize: 12 }} />}
            summary="Thought process"
          >
            <div style={{ fontSize: 12, color: '#666', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {thinkingText}
            </div>
          </CollapsibleBlock>
        </div>
      )}

      {/* 工具调用日志 — 逐条折叠行嵌入文档流 */}
      <ToolExecutionLog />

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
