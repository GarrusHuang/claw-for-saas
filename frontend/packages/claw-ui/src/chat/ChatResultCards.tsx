/**
 * 紧凑版结果卡片 (Mini 组件) — 增强版。
 *
 * Phase 8: MiniErrorCard — 结构化错误详情
 * Phase 13: MiniParallelReviewCard — 并行审查结果
 * 其余: 原有 Mini 组件 (TypeInference, FieldUpdates, AuditSummary, DocumentPreview, PlanCard)
 */

import { Tag, Typography, Progress, Button } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  FileTextOutlined,
  BulbOutlined,
  ThunderboltOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { usePipelineStore } from '@claw/core';
import type {
  InferredType,
  FieldValue,
  AuditSummary,
  GeneratedDocument,
  PlanProposal,
  ErrorDetail,
  ParallelReviewState,
} from '@claw/core';

const { Text } = Typography;

// ── Mini 类型推断卡片 ──

export function MiniTypeInference({ data }: { data: InferredType }) {
  const pct = Math.round(data.confidence * 100);
  return (
    <div style={{ background: '#f6ffed', borderRadius: 8, padding: '10px 14px', marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <BulbOutlined style={{ color: '#52c41a' }} />
        <Text strong style={{ fontSize: 13 }}>类型推断</Text>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag color="blue">{data.docType}</Tag>
        <Progress
          percent={pct}
          size="small"
          style={{ flex: 1, maxWidth: 120 }}
          strokeColor={pct >= 80 ? '#52c41a' : pct >= 60 ? '#faad14' : '#ff4d4f'}
        />
      </div>
      {data.reasoning && (
        <Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
          {data.reasoning}
        </Text>
      )}
    </div>
  );
}

// ── Mini 字段填写摘要卡片 ──

export function MiniFieldUpdates({ fields }: { fields: FieldValue[] }) {
  if (fields.length === 0) return null;

  return (
    <div style={{ background: '#e6f4ff', borderRadius: 8, padding: '10px 14px', marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <FileTextOutlined style={{ color: '#1a6fb5' }} />
        <Text strong style={{ fontSize: 13 }}>
          表单填写 — {fields.length} 个字段
        </Text>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {fields.slice(0, 6).map((f) => (
          <Tag key={f.fieldId} style={{ fontSize: 11 }}>
            {f.fieldId}: {String(f.value).length > 15 ? String(f.value).slice(0, 15) + '...' : String(f.value)}
          </Tag>
        ))}
        {fields.length > 6 && (
          <Tag style={{ fontSize: 11 }}>+{fields.length - 6} 更多</Tag>
        )}
      </div>
    </div>
  );
}

// ── Mini 审计摘要卡片 ──

export function MiniAuditSummary({ data }: { data: AuditSummary }) {
  const statusIcon = data.failCount > 0
    ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
    : data.warningCount > 0
    ? <WarningOutlined style={{ color: '#faad14' }} />
    : <CheckCircleOutlined style={{ color: '#52c41a' }} />;

  const statusColor = data.failCount > 0
    ? '#fff2f0'
    : data.warningCount > 0
    ? '#fffbe6'
    : '#f6ffed';

  return (
    <div style={{ background: statusColor, borderRadius: 8, padding: '10px 14px', marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        {statusIcon}
        <Text strong style={{ fontSize: 13 }}>审计结果</Text>
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <span style={{ fontSize: 12 }}>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 3 }} />
          通过 {data.passCount}
        </span>
        {data.failCount > 0 && (
          <span style={{ fontSize: 12 }}>
            <CloseCircleOutlined style={{ color: '#ff4d4f', marginRight: 3 }} />
            失败 {data.failCount}
          </span>
        )}
        {data.warningCount > 0 && (
          <span style={{ fontSize: 12 }}>
            <WarningOutlined style={{ color: '#faad14', marginRight: 3 }} />
            警告 {data.warningCount}
          </span>
        )}
      </div>
      {data.conclusion && (
        <Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
          {data.conclusion}
        </Text>
      )}
    </div>
  );
}

// ── Mini 文档预览卡片 ──

export function MiniDocumentPreview({ data }: { data: GeneratedDocument }) {
  return (
    <div style={{ background: '#f9f0ff', borderRadius: 8, padding: '10px 14px', marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <FileTextOutlined style={{ color: '#722ed1' }} />
        <Text strong style={{ fontSize: 13 }}>
          {data.title || '文档已生成'}
        </Text>
        <Tag color="purple" style={{ fontSize: 10, marginLeft: 'auto' }}>
          {data.documentType}
        </Tag>
      </div>
      <Text
        type="secondary"
        style={{
          fontSize: 11,
          display: '-webkit-box',
          WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          whiteSpace: 'pre-wrap',
        }}
      >
        {data.content.slice(0, 200)}
        {data.content.length > 200 ? '...' : ''}
      </Text>
    </div>
  );
}

// ── Phase 8: Mini 错误详情卡片 ──

const CATEGORY_LABELS: Record<string, string> = {
  rate_limit: '限流',
  auth: '认证',
  tool_error: '工具错误',
  validation: '验证失败',
  internal: '内部错误',
  network: '网络错误',
  partial_failure: '部分失败',
};

const CATEGORY_COLORS: Record<string, string> = {
  rate_limit: 'orange',
  auth: 'red',
  tool_error: 'volcano',
  validation: 'gold',
  internal: 'red',
  network: 'magenta',
  partial_failure: 'orange',
};

export function MiniErrorCard({ error }: { error: ErrorDetail }) {
  return (
    <div style={{ background: '#fff2f0', borderRadius: 8, padding: '10px 14px', marginBottom: 8, border: '1px solid #ffccc7' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
        <Text strong style={{ fontSize: 13, color: '#cf1322' }}>错误详情</Text>
        <Tag color={CATEGORY_COLORS[error.category] || 'red'} style={{ marginLeft: 'auto', fontSize: 10 }}>
          {CATEGORY_LABELS[error.category] || error.category}
        </Tag>
      </div>
      <Text style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
        {error.message}
      </Text>
      {error.affectedStep && (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 2 }}>
          出错步骤: {error.affectedStep}
        </Text>
      )}
      {error.suggestedAction && (
        <div style={{ background: '#e6f4ff', borderRadius: 4, padding: '6px 8px', marginTop: 6 }}>
          <Text style={{ fontSize: 11, color: '#1890ff' }}>
            💡 {error.suggestedAction}
          </Text>
        </div>
      )}
      {error.traceId && (
        <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 4 }}>
          Trace: {error.traceId}
        </Text>
      )}
    </div>
  );
}

// ── Phase 13: Mini 并行审查结果卡片 ──

function reviewStatusColor(status: string): string {
  if (status === '通过') return 'green';
  if (status === '警告') return 'orange';
  if (status === '失败') return 'red';
  if (status === '错误') return 'volcano';
  return 'default';
}

export function MiniParallelReviewCard({ review }: { review: ParallelReviewState }) {
  return (
    <div style={{ background: '#f0f5ff', borderRadius: 8, padding: '10px 14px', marginBottom: 8, border: '1px solid #adc6ff' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <TeamOutlined style={{ color: '#2f54eb' }} />
        <Text strong style={{ fontSize: 13 }}>多 Agent 并行审查</Text>
        <Tag color={reviewStatusColor(review.overallStatus)} style={{ marginLeft: 'auto', fontSize: 10 }}>
          整体: {review.overallStatus || '进行中'}
        </Tag>
      </div>
      {/* 整体统计 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        <Text style={{ fontSize: 12 }}>
          置信度 {Math.round(review.overallConfidence * 100)}%
        </Text>
        {review.durationMs > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            用时 {(review.durationMs / 1000).toFixed(1)}s
          </Text>
        )}
      </div>
      {/* 各 Agent 结果 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {review.results.map((r) => (
          <div key={r.agentRole} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <Tag style={{ fontSize: 10, minWidth: 60, textAlign: 'center' }}>{r.agentRole}</Tag>
            <Tag color={reviewStatusColor(r.conclusion)} style={{ fontSize: 10 }}>{r.conclusion}</Tag>
            <Text type="secondary" style={{ fontSize: 10, flex: 1 }}>
              {Math.round(r.confidence * 100)}%
            </Text>
            {r.details && (
              <Text type="secondary" style={{ fontSize: 10, flex: 2 }} ellipsis>
                {r.details}
              </Text>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Cowork 风格进度面板内置组件 ──

function useStepCompletion(steps: Array<{ description: string }>) {
  const inferredType = usePipelineStore((s) => s.inferredType);
  const fieldValues = usePipelineStore((s) => s.fieldValues);
  const auditSummary = usePipelineStore((s) => s.auditSummary);
  const document = usePipelineStore((s) => s.document);
  const status = usePipelineStore((s) => s.status);

  const signals = {
    type: !!inferredType,
    form: fieldValues.length > 0,
    audit: !!auditSummary,
    doc: !!document,
  };

  return steps.map((step) => {
    const desc = step.description.toLowerCase();
    if ((desc.includes('类型') || desc.includes('推断') || desc.includes('分类') || desc.includes('识别')) && signals.type) return 'completed';
    if ((desc.includes('填写') || desc.includes('表单') || desc.includes('字段') || desc.includes('查询') || desc.includes('获取') || desc.includes('用户')) && signals.form) return 'completed';
    if ((desc.includes('审计') || desc.includes('审核') || desc.includes('合规') || desc.includes('检查') || desc.includes('校验')) && signals.audit) return 'completed';
    if ((desc.includes('文档') || desc.includes('生成') || desc.includes('报告') || desc.includes('合同文本') || desc.includes('意见书')) && signals.doc) return 'completed';
    if (status === 'completed') return 'completed';
    if (signals.type || signals.form || signals.audit || signals.doc) return 'pending';
    return 'pending';
  });
}

export function MiniPlanCard({ data, onApprove }: { data: PlanProposal; onApprove?: () => void }) {
  const steps = Array.isArray(data.steps) ? data.steps : [];
  const normalizedSteps = steps.map((s: unknown, _i: number) => {
    if (typeof s === 'string') return { description: s };
    if (s && typeof s === 'object') {
      const obj = s as Record<string, unknown>;
      return {
        description: (obj.description as string) || (obj.action as string) || (obj.content as string) || JSON.stringify(s),
      };
    }
    return { description: String(s) };
  });

  const stepStatuses = useStepCompletion(normalizedSteps);
  const completedCount = stepStatuses.filter((s) => s === 'completed').length;
  const pipelineStatus = usePipelineStore((s) => s.status);
  const firstPendingIdx = stepStatuses.indexOf('pending');

  if (normalizedSteps.length === 0) return null;

  return (
    <div style={{
      background: '#fafafa',
      borderRadius: 8,
      padding: '12px 14px',
      marginBottom: 8,
      border: '1px solid #e8e8e8',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <ThunderboltOutlined style={{ color: '#fa8c16' }} />
        <Text strong style={{ fontSize: 13 }}>执行进度</Text>
        <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {completedCount}/{normalizedSteps.length}
        </Text>
      </div>

      <div>
        {normalizedSteps.map((step, i) => {
          const isDone = stepStatuses[i] === 'completed';
          const isRunning = pipelineStatus === 'running' && !isDone && i === firstPendingIdx;

          return (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: '4px 0',
              fontSize: 12,
            }}>
              {isDone ? (
                <CheckCircleOutlined style={{ color: '#52c41a', marginTop: 2, fontSize: 13 }} />
              ) : isRunning ? (
                <LoadingOutlined style={{ color: '#1890ff', marginTop: 2, fontSize: 13 }} />
              ) : (
                <ClockCircleOutlined style={{ color: '#d9d9d9', marginTop: 2, fontSize: 13 }} />
              )}
              <Text style={{
                color: isDone ? '#52c41a' : isRunning ? '#1890ff' : '#999',
                flex: 1,
                lineHeight: '18px',
              }}>
                {step.description}
              </Text>
            </div>
          );
        })}
      </div>

      {data.requiresApproval && pipelineStatus === 'plan_awaiting' && onApprove && (
        <div style={{ marginTop: 10, textAlign: 'center' }}>
          <Button
            type="primary"
            size="small"
            onClick={onApprove}
            style={{ borderRadius: 6, fontSize: 12 }}
          >
            确认执行
          </Button>
        </div>
      )}
    </div>
  );
}
