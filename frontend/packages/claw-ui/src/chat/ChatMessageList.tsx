import { useEffect, useRef } from 'react';
import { Typography, Spin, Button } from 'antd';
import {
  RobotOutlined,
  UserOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  BulbOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { usePipelineStore } from '@claw/core';
import type { PendingInteraction } from '@claw/core';
import {
  MiniTypeInference,
  MiniFieldUpdates,
  MiniAuditSummary,
} from './ChatResultCards';
import DocumentPresenter from '../results/DocumentPresenter';
import InlineUploader from './InlineUploader';
import InteractiveMessage from './InteractiveMessage';

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
  onApprovePlan?: () => void;
  showThinking?: boolean;
  onInteractionRespond?: (value: string, files?: { fileId: string; filename: string }[]) => void;
}

// ── PlanCard 组件 — 在聊天流中渲染 Agent 提出的方案 ──

function PlanCard({ onApprove }: { onApprove?: () => void }) {
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
        {isPlanAwaiting && onApprove && (
          <div className="plan-document-actions">
            <Button
              type="primary"
              size="small"
              onClick={onApprove}
              style={{ borderRadius: 6, height: 32, paddingInline: 20 }}
            >
              <CheckCircleOutlined />
              确认执行
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              或在下方输入修改意见
            </Text>
          </div>
        )}
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

// ── Pipeline 进度组件（事件驱动，嵌入聊天气泡） ──

function InlinePipelineProgress({ onApprovePlan }: { onApprovePlan?: () => void }) {
  const status = usePipelineStore((s) => s.status);
  const inferredType = usePipelineStore((s) => s.inferredType);
  const fieldValues = usePipelineStore((s) => s.fieldValues);
  const auditSummary = usePipelineStore((s) => s.auditSummary);
  const document = usePipelineStore((s) => s.document);
  const durationMs = usePipelineStore((s) => s.durationMs);

  if (status === 'idle') return null;

  // 事件驱动进度提示
  const progressHints: string[] = [];
  if (inferredType) progressHints.push(`类型推断: ${inferredType.docType}`);
  if (fieldValues.length > 0) progressHints.push(`已填写 ${fieldValues.length} 个字段`);
  if (auditSummary) progressHints.push(`审计完成: ${auditSummary.conclusion}`);
  if (document) progressHints.push(`文档生成: ${document.title}`);

  return (
    <div>
      {/* PlanCard — Agent 提出的方案 */}
      <PlanCard onApprove={onApprovePlan} />

      {/* 实时处理状态 */}
      {status === 'running' && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Spin size="small" />
            <Text type="secondary" style={{ fontSize: 12 }}>
              Agent 自主处理中...
            </Text>
          </div>
          {progressHints.length > 0 && (
            <div style={{ paddingLeft: 24 }}>
              {progressHints.map((hint, i) => (
                <div key={i} style={{ fontSize: 11, color: '#52c41a', marginBottom: 2 }}>
                  <CheckCircleOutlined style={{ marginRight: 4, fontSize: 10 }} />
                  {hint}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 结果卡片 — 内联显示关键结果 */}
      {inferredType && <MiniTypeInference data={inferredType} />}
      {fieldValues.length > 0 && <MiniFieldUpdates fields={fieldValues} />}
      {auditSummary && <MiniAuditSummary data={auditSummary} />}
      {document && <DocumentPresenter document={document} />}

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
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
            处理完成，用时 {(durationMs / 1000).toFixed(1)}s
          </Text>
        </div>
      )}

      {/* 失败提示 */}
      {status === 'failed' && (
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Text type="danger" style={{ fontSize: 11 }}>
            <CloseCircleOutlined style={{ marginRight: 4 }} />
            处理失败
          </Text>
        </div>
      )}
    </div>
  );
}

// ── 主组件 ──

export default function ChatMessageList({
  messages,
  showPipelineProgress = true,
  onApprovePlan,
  showThinking = false,
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
        padding: '16px 16px 8px',
      }}
    >
      {messages.map((msg) => (
        <div key={msg.id} className="chat-bubble" style={{ marginBottom: 16 }}>
          {msg.role === 'user' ? (
            // 用户消息 — 右对齐蓝色气泡
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <div className="chat-bubble-user">
                <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{msg.content}</Text>
              </div>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: '50%',
                  background: '#1a6fb5',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <UserOutlined style={{ color: '#fff', fontSize: 16 }} />
              </div>
            </div>
          ) : (
            // AI 消息 — 左对齐灰色气泡
            <div style={{ display: 'flex', justifyContent: 'flex-start', gap: 8 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  flexShrink: 0,
                }}
              >
                <img
                  src="/assets/claw-avatar.svg"
                  alt="Claw"
                  style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                />
              </div>
              <div className="chat-bubble-ai markdown-body">
                <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Agent 思考过程（仅当开关开启 + 有内容 + 正在处理） */}
      {showThinking && thinkingText && (isStreaming || pipelineStatus === 'running') && (
        <div className="chat-bubble" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-start', gap: 8 }}>
            <div style={{ width: 40, height: 40, flexShrink: 0 }}>
              <img src="/assets/claw-avatar.svg" alt="Claw" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            </div>
            <div className="chat-thinking-bubble">
              <div className="chat-thinking-header">
                <BulbOutlined style={{ color: '#faad14', fontSize: 12 }} />
                <Text type="secondary" style={{ fontSize: 11 }}>思考中...</Text>
              </div>
              <div className="chat-thinking-content">
                {thinkingText}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Pipeline 实时进度（跟随最后一条 AI 消息之后，自由对话不显示） */}
      {showPipelineProgress && pipelineStatus !== 'idle' && pipelineScenario !== 'general_chat' && (
        <div className="chat-bubble" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-start', gap: 8 }}>
            <div
              style={{
                width: 40,
                height: 40,
                flexShrink: 0,
              }}
            >
              <img
                src="/assets/claw-avatar.svg"
                alt="Claw"
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
            <div className="chat-bubble-ai" style={{ minWidth: 240 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <RobotOutlined style={{ color: '#1a6fb5' }} />
                <Text strong style={{ fontSize: 13 }}>AI Agent 处理中</Text>
              </div>
              <InlinePipelineProgress onApprovePlan={onApprovePlan} />
            </div>
          </div>
        </div>
      )}

      {/* Phase 24: Agent 交互请求 (内联上传 / 确认 / 输入) */}
      {pendingInteraction && (
        <div className="chat-bubble" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-start', gap: 8 }}>
            <div style={{ width: 40, height: 40, flexShrink: 0 }}>
              <img src="/assets/claw-avatar.svg" alt="Claw" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
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
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
