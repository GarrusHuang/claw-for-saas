/**
 * 任务进度面板 — TodoList + 工具调用日志 + Thinking + 并行审查 + 实时统计。
 */

import { useState } from 'react';
import { Typography, Tag, Spin, Progress } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  CodeOutlined,
  BulbOutlined,
  DownOutlined,
  RightOutlined,
  TeamOutlined,
  ToolOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { usePipelineStore } from '@claw/core';
import type { PlanProposal, PlanStepTracking, ToolExecution } from '@claw/core';

const { Text } = Typography;

/** Phase 9: 工作流阶段标签映射 */
const PHASE_LABELS: Record<string, string> = {
  initializing: '初始化',
  classifying: '类型推断',
  form_filling: '表单填写',
  auditing: '审计检查',
  reviewing: '审查验证',
  generating: '文档生成',
  completing: '完成收尾',
};

interface ProgressPanelProps {
  plan: PlanProposal | null;
  showThinking?: boolean;
}

export default function ProgressPanel({ plan, showThinking = false }: ProgressPanelProps) {
  const pipelineStatus = usePipelineStore((s) => s.status);
  const toolExecutions = usePipelineStore((s) => s.toolExecutions);
  const agentIteration = usePipelineStore((s) => s.agentIteration);
  const agentPlanProposed = usePipelineStore((s) => s.agentPlanProposed);
  const planSteps = usePipelineStore((s) => s.planSteps);
  const startedAt = usePipelineStore((s) => s.startedAt);
  const durationMs = usePipelineStore((s) => s.durationMs);
  const thinkingText = usePipelineStore((s) => s.thinkingText);
  const isStreaming = usePipelineStore((s) => s.isStreaming);
  // Phase 9
  const workflowPhase = usePipelineStore((s) => s.workflowPhase);
  const workflowProgress = usePipelineStore((s) => s.workflowProgress);
  // Phase 13
  const parallelReview = usePipelineStore((s) => s.parallelReview);

  const [thinkingExpanded, setThinkingExpanded] = useState(true);
  const [toolLogExpanded, setToolLogExpanded] = useState(false);

  const isRunning = pipelineStatus === 'running';
  const isCompleted = pipelineStatus === 'completed';
  const isFailed = pipelineStatus === 'failed';
  const isPlanAwaiting = pipelineStatus === 'plan_awaiting';

  const elapsed = isRunning && startedAt
    ? Math.round((Date.now() - startedAt) / 1000 * 10) / 10
    : durationMs > 0
      ? Math.round(durationMs / 100) / 10
      : 0;

  if (pipelineStatus === 'idle' && toolExecutions.length === 0 && !plan && planSteps.length === 0) {
    return null;
  }

  const hasPlanSteps = planSteps.length > 0;

  return (
    <div className="progress-panel">
      {/* ── 标题 ── */}
      <div className="progress-panel-header">
        <ThunderboltOutlined style={{ color: '#fa8c16' }} />
        <span>Progress</span>
        {isRunning && (
          <LoadingOutlined style={{ color: '#1890ff', fontSize: 12, marginLeft: 'auto' }} />
        )}
        {isCompleted && (
          <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12, marginLeft: 'auto' }} />
        )}
        {isFailed && (
          <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 12, marginLeft: 'auto' }} />
        )}
      </div>

      {/* ── 任务进度 TodoList (纯执行追踪，方案内容由聊天区 PlanCard 展示) ── */}
      {hasPlanSteps && (
        <div className="progress-section">
          <div className="progress-section-title">
            <CodeOutlined style={{ fontSize: 11 }} />
            <span>任务进度</span>
            {isPlanAwaiting && (
              <span style={{ marginLeft: 'auto', fontSize: 10, color: '#faad14' }}>待确认</span>
            )}
            {isRunning && (
              <span style={{ marginLeft: 'auto', fontSize: 10, color: '#52c41a' }}>执行中</span>
            )}
          </div>
          <div className="progress-plan-steps">
            {planSteps.map((step: PlanStepTracking, i: number) => (
              <div key={i} className={`progress-plan-step progress-plan-step--${step.status}`}>
                <span className="progress-plan-step-icon">
                  {step.status === 'completed' && (
                    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
                  )}
                  {step.status === 'running' && (
                    <LoadingOutlined style={{ color: '#1890ff', fontSize: 12 }} />
                  )}
                  {step.status === 'failed' && (
                    <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 12 }} />
                  )}
                  {step.status === 'pending' && (
                    <ClockCircleOutlined style={{ color: '#d9d9d9', fontSize: 12 }} />
                  )}
                </span>
                <Text
                  style={{ fontSize: 11, flex: 1 }}
                  type={step.status === 'pending' ? 'secondary' : undefined}
                >
                  {step.description}
                </Text>
                {step.status === 'completed' && step.startedAt && step.completedAt && (
                  <span style={{ fontSize: 10, color: '#999', whiteSpace: 'nowrap' }}>
                    {((step.completedAt - step.startedAt) / 1000).toFixed(1)}s
                  </span>
                )}
                {step.status === 'running' && step.startedAt && (
                  <span style={{ fontSize: 10, color: '#1890ff', whiteSpace: 'nowrap' }}>...</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Phase 27: 工具调用日志 ── */}
      {toolExecutions.length > 0 && (
        <div className="progress-section">
          <div
            className="progress-section-title"
            style={{ cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setToolLogExpanded((v) => !v)}
          >
            <ToolOutlined style={{ fontSize: 11, color: '#722ed1' }} />
            <span>工具调用</span>
            <span style={{ marginLeft: 4, fontSize: 10, color: '#999' }}>
              ({toolExecutions.length})
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 10, color: '#999' }}>
              {toolLogExpanded ? <DownOutlined /> : <RightOutlined />}
            </span>
          </div>
          {toolLogExpanded && (
            <div className="progress-tool-log">
              {toolExecutions.map((te: ToolExecution) => (
                <div key={te.id} className="progress-tool-item">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span className="progress-tool-icon">
                      {te.blocked ? (
                        <StopOutlined style={{ color: '#faad14', fontSize: 11 }} />
                      ) : te.success ? (
                        <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
                      ) : (
                        <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />
                      )}
                    </span>
                    <span className="progress-tool-name">{te.toolName}</span>
                    <span className="progress-tool-latency">
                      ({Math.round(te.latencyMs)}ms)
                    </span>
                  </div>
                  {te.argsSummary && Object.keys(te.argsSummary).length > 0 && (
                    <div className="progress-tool-args">
                      {'→ '}
                      {Object.entries(te.argsSummary)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ')}
                    </div>
                  )}
                  {te.resultSummary && (
                    <div className="progress-tool-result">
                      {'← '}
                      {te.resultSummary}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Phase 9: 工作流阶段 ── */}
      {workflowPhase && isRunning && (
        <div className="progress-section">
          <div className="progress-section-title">
            <ThunderboltOutlined style={{ fontSize: 11, color: '#1890ff' }} />
            <span>工作流阶段</span>
          </div>
          <div style={{ padding: '4px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <Tag color="blue" style={{ fontSize: 10 }}>
                {PHASE_LABELS[workflowPhase] || workflowPhase}
              </Tag>
              {workflowProgress > 0 && (
                <Text type="secondary" style={{ fontSize: 10 }}>
                  {Math.round(workflowProgress * 100)}%
                </Text>
              )}
            </div>
            {workflowProgress > 0 && (
              <Progress
                percent={Math.round(workflowProgress * 100)}
                size="small"
                showInfo={false}
                strokeColor="#1890ff"
              />
            )}
          </div>
        </div>
      )}

      {/* ── Phase 13: 并行审查状态 ── */}
      {parallelReview && (
        <div className="progress-section">
          <div className="progress-section-title">
            <TeamOutlined style={{ fontSize: 11, color: '#2f54eb' }} />
            <span>多 Agent 审查</span>
            {parallelReview.status === 'running' && (
              <LoadingOutlined style={{ fontSize: 10, color: '#1890ff', marginLeft: 'auto' }} />
            )}
            {parallelReview.status === 'completed' && (
              <Tag
                color={parallelReview.overallStatus === '通过' ? 'green' : parallelReview.overallStatus === '警告' ? 'orange' : 'red'}
                style={{ fontSize: 10, marginLeft: 'auto' }}
              >
                {parallelReview.overallStatus}
              </Tag>
            )}
          </div>

          {parallelReview.status === 'running' && (
            <div style={{ padding: '6px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <Spin size="small" />
                <Text type="secondary" style={{ fontSize: 11 }}>并行审查中...</Text>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {parallelReview.roles.map((r) => (
                  <Tag key={r} style={{ fontSize: 10 }}>{r}</Tag>
                ))}
              </div>
            </div>
          )}

          {parallelReview.status === 'completed' && (
            <div style={{ padding: '4px 0' }}>
              {parallelReview.results.map((r) => (
                <div key={r.agentRole} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 0', fontSize: 11 }}>
                  {r.conclusion === '通过' ? (
                    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
                  ) : r.conclusion === '警告' ? (
                    <ClockCircleOutlined style={{ color: '#faad14', fontSize: 11 }} />
                  ) : (
                    <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />
                  )}
                  <Text style={{ fontSize: 11 }}>{r.agentRole}</Text>
                  <Text type="secondary" style={{ fontSize: 10, marginLeft: 'auto' }}>
                    {Math.round(r.confidence * 100)}%
                  </Text>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Thinking 思考过程 ── */}
      {showThinking && thinkingText && (
        <div className="progress-section">
          <div
            className="progress-section-title"
            style={{ cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setThinkingExpanded((v) => !v)}
          >
            <BulbOutlined style={{ fontSize: 11, color: '#faad14' }} />
            <span>Thinking</span>
            {isStreaming && (
              <LoadingOutlined style={{ fontSize: 10, color: '#1890ff', marginLeft: 4 }} />
            )}
            <span style={{ marginLeft: 'auto', fontSize: 10, color: '#999' }}>
              {thinkingExpanded ? <DownOutlined /> : <RightOutlined />}
            </span>
          </div>
          {thinkingExpanded && (
            <div className="progress-thinking-content">
              {thinkingText}
            </div>
          )}
        </div>
      )}

      {/* ── 实时统计 ── */}
      {(isRunning || isCompleted || isFailed || isPlanAwaiting) && (
        <div className="progress-stats">
          {agentIteration.current > 0 && (
            <span className="progress-stat-item">
              迭代 {agentIteration.current}/{agentIteration.max}
            </span>
          )}
          {toolExecutions.length > 0 && (
            <span className="progress-stat-item">
              {toolExecutions.length} 次工具调用
            </span>
          )}
          {elapsed > 0 && (
            <span className="progress-stat-item">
              ⏱ {elapsed}s
            </span>
          )}
        </div>
      )}
    </div>
  );
}
