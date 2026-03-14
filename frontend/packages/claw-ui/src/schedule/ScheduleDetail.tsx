import { useCallback } from 'react';
import { Button, Popconfirm, Tag, message } from 'antd';
import { ArrowLeftOutlined, EditOutlined, CaretRightOutlined, DeleteOutlined } from '@ant-design/icons';
import { aiApi, useAIChatStore, type ScheduledTask, type RunRecord } from '@claw/core';

interface ScheduleDetailProps {
  task: ScheduledTask;
  onBack: () => void;
  onEdit: () => void;
  onRefresh: () => void;
}

/** Describe schedule type */
function describeSchedule(task: ScheduledTask): string {
  if (task.cron) {
    return describeCron(task.cron);
  }
  if (task.scheduled_at) {
    return `一次性 ${formatTime(task.scheduled_at)}`;
  }
  return '-';
}

function describeCron(cron: string): string {
  if (!cron) return '一次性';
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [minS, hourS, domS, , dowS] = parts;
  const time = `${hourS.padStart(2, '0')}:${minS.padStart(2, '0')}`;
  if (dowS === '*' && domS === '*') return `每天 ${time}`;
  if (dowS === '1-5' && domS === '*') return `工作日 ${time}`;
  if (dowS !== '*' && domS === '*') {
    const dayMap: Record<string, string> = { '0': '日', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六' };
    return `每周${dayMap[dowS] || dowS} ${time}`;
  }
  if (dowS === '*' && domS !== '*') return `每月 ${domS} 日 ${time}`;
  return cron;
}

function formatTime(ts: number | null): string {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m${s}s` : `${m}m`;
}

export default function ScheduleDetail({ task, onBack, onEdit, onRefresh }: ScheduleDetailProps) {
  const dispatchSessionAction = useAIChatStore((s) => s.dispatchSessionAction);

  const handleRunNow = useCallback(async () => {
    try {
      await aiApi.runScheduleNow(task.id);
      message.success('任务已触发');
      onRefresh();
    } catch {
      message.error('运行失败');
    }
  }, [task.id, onRefresh]);

  const handleDelete = useCallback(async () => {
    try {
      await aiApi.deleteSchedule(task.id);
      message.success('任务已删除');
      onBack();
    } catch {
      message.error('删除失败');
    }
  }, [task.id, onBack]);

  const handleViewSession = useCallback((sessionId: string) => {
    if (!sessionId) return;
    dispatchSessionAction({ type: 'load', sessionId });
  }, [dispatchSessionAction]);

  const runHistory = (task.run_history || []) as RunRecord[];
  // Show newest first
  const sortedHistory = [...runHistory].reverse();

  return (
    <div className="schedule-detail-container">
      {/* Header */}
      <div
        className="schedule-form-back"
        role="button"
        tabIndex={0}
        onClick={onBack}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onBack(); } }}
      >
        <ArrowLeftOutlined style={{ fontSize: 12 }} />
        <span>返回任务列表</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '16px 0 24px' }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: '#333' }}>
          {task.name}
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<EditOutlined />} onClick={onEdit}>编辑</Button>
          <Button icon={<CaretRightOutlined />} onClick={handleRunNow}>立即运行</Button>
          <Popconfirm
            title={`确定删除 "${task.name}"?`}
            onConfirm={handleDelete}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, size: 'small' }}
            cancelButtonProps={{ size: 'small' }}
          >
            <Button danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </div>
      </div>

      {/* 提示词 */}
      <div className="schedule-detail-section">
        <div className="schedule-detail-section-title">提示词</div>
        <div className="schedule-detail-prompt">{task.message}</div>
      </div>

      {/* 配置信息 */}
      <div className="schedule-detail-section">
        <div className="schedule-detail-section-title">配置信息</div>
        <div className="schedule-detail-grid">
          <div className="schedule-detail-grid-item">
            <span className="schedule-detail-label">计划</span>
            <span className="schedule-detail-value">{describeSchedule(task)}</span>
          </div>
          <div className="schedule-detail-grid-item">
            <span className="schedule-detail-label">启用任务</span>
            <span className="schedule-detail-value">
              <Tag color={task.enabled ? 'green' : 'default'}>
                {task.enabled ? '已启用' : '已禁用'}
              </Tag>
            </span>
          </div>
          <div className="schedule-detail-grid-item">
            <span className="schedule-detail-label">到期时间</span>
            <span className="schedule-detail-value">
              {task.expires_at ? formatTime(task.expires_at) : '永不过期'}
            </span>
          </div>
        </div>
      </div>

      {/* 运行状态 */}
      <div className="schedule-detail-section">
        <div className="schedule-detail-section-title">运行状态</div>
        <div className="schedule-detail-grid">
          <div className="schedule-detail-grid-item">
            <span className="schedule-detail-label">上次运行</span>
            <span className="schedule-detail-value">
              {task.last_run_at ? (
                <>
                  <Tag color={task.last_run_status === 'success' ? 'green' : 'red'} style={{ marginRight: 8 }}>
                    {task.last_run_status === 'success' ? '成功' : '失败'}
                  </Tag>
                  {formatTime(task.last_run_at)}
                </>
              ) : '-'}
            </span>
          </div>
          <div className="schedule-detail-grid-item">
            <span className="schedule-detail-label">下次运行</span>
            <span className="schedule-detail-value">
              {task.next_run_at ? formatTime(task.next_run_at) : '-'}
            </span>
          </div>
          {runHistory.length > 0 && (
            <div className="schedule-detail-grid-item">
              <span className="schedule-detail-label">上次耗时</span>
              <span className="schedule-detail-value">
                {formatDuration(runHistory[runHistory.length - 1].duration_s)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 运行历史 */}
      <div className="schedule-detail-section">
        <div className="schedule-detail-section-title">运行历史</div>
        {sortedHistory.length === 0 ? (
          <div style={{ color: '#999', fontSize: 13 }}>暂无运行记录</div>
        ) : (
          <div className="schedule-detail-history">
            {sortedHistory.map((record, i) => (
              <div key={i} className="schedule-detail-history-item">
                <span className={`schedule-status-dot schedule-status-dot--${record.status === 'success' ? 'success' : 'failed'}`} />
                <span className="schedule-detail-history-time">{formatTime(record.started_at)}</span>
                <Tag style={{ fontSize: 11 }}>{record.trigger === 'manual' ? '手动' : '定时'}</Tag>
                <span className="schedule-detail-history-duration">{formatDuration(record.duration_s)}</span>
                {record.session_id && (
                  <Button
                    type="link"
                    size="small"
                    style={{ fontSize: 12, padding: 0 }}
                    onClick={() => handleViewSession(record.session_id)}
                  >
                    查看会话
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
