/**
 * 右栏面板 — Progress + Files + Instructions + Context
 */

import { useState, useEffect, useCallback } from 'react';
import { Typography } from 'antd';
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
} from '@ant-design/icons';
import { usePipelineStore, aiApi } from '@claw/core';
import type { PlanStepTracking, ToolExecution } from '@claw/core';

const { Text } = Typography;

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

      // Build memory summary from stats
      const parts: string[] = [];
      const corrCount = typeof memStats.corrections === 'number'
        ? memStats.corrections
        : (memStats.corrections as { total?: number })?.total ?? 0;
      if (corrCount > 0) parts.push(`${corrCount} corrections`);
      if (memStats.learning_entries > 0) parts.push(`${memStats.learning_entries} learnings`);
      const sessCount = (memStats.sessions as { count?: number })?.count ?? 0;
      if (sessCount > 0) parts.push(`${sessCount} sessions`);
      setMemorySummary(parts.length > 0 ? parts.join(', ') : 'No data');
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadContext();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="progress-panel">
      {/* ── Section 1: Progress ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <ThunderboltOutlined style={{ fontSize: 11, color: '#fa8c16' }} />
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
        {hasPlanSteps ? (
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
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '8px 0' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>No active tasks</Text>
          </div>
        )}
      </div>

      {/* ── Section 2: Files ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <FileOutlined style={{ fontSize: 11, color: '#1890ff' }} />
          <span>Files</span>
          {fileNames.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 10, color: '#999' }}>
              {fileNames.length}
            </span>
          )}
        </div>
        {fileNames.length > 0 ? (
          <div style={{ padding: '4px 0' }}>
            {fileNames.map((name) => (
              <div key={name} style={{ fontSize: 11, color: '#333', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
                <FileOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '8px 0' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>No files yet</Text>
          </div>
        )}
      </div>

      {/* ── Section 3: Instructions ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <BookOutlined style={{ fontSize: 11, color: '#722ed1' }} />
          <span>Instructions</span>
        </div>
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontSize: 11, color: '#333', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
            <FileOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
            <span>soul.md</span>
          </div>
          <div style={{ fontSize: 11, color: '#333', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
            <FileOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
            <span>Scratchpad</span>
          </div>
        </div>
      </div>

      {/* ── Section 4: Context ── */}
      <div className="progress-section">
        <div className="progress-section-title">
          <DatabaseOutlined style={{ fontSize: 11, color: '#13c2c2' }} />
          <span>Context</span>
        </div>
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontSize: 11, color: '#333', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
            <ToolOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
            <span>MCP Tools ({toolCount})</span>
          </div>
          <div style={{ fontSize: 11, color: '#333', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
            <DatabaseOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
            <span>Memory — {memorySummary}</span>
          </div>
          <div style={{ fontSize: 11, color: '#999', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, textAlign: 'center', fontSize: 10 }}>○</span>
            <span>Connectors</span>
          </div>
        </div>
      </div>
    </div>
  );
}
