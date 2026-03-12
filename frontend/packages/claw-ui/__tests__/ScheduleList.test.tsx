import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// ── Mock @claw/core ──
const mockPauseSchedule = vi.fn().mockResolvedValue({ status: 'ok' });
const mockResumeSchedule = vi.fn().mockResolvedValue({ status: 'ok' });
const mockDeleteSchedule = vi.fn().mockResolvedValue({ status: 'ok' });

vi.mock('@claw/core', () => ({
  aiApi: {
    pauseSchedule: (...args: unknown[]) => mockPauseSchedule(...args),
    resumeSchedule: (...args: unknown[]) => mockResumeSchedule(...args),
    deleteSchedule: (...args: unknown[]) => mockDeleteSchedule(...args),
  },
}));

import ScheduleList from '../src/schedule/ScheduleList.tsx';

// ── Helper: create mock task ──
function makeTask(overrides = {}): import('@claw/core').ScheduledTask {
  return {
    id: 'task-1',
    name: '每日报告',
    cron: '0 9 * * *',
    message: '生成日报',
    user_id: 'U001',
    tenant_id: 'default',
    business_type: 'scheduled_task',
    enabled: true,
    created_at: Date.now() / 1000,
    last_run_at: null,
    last_run_status: '',
    next_run_at: Date.now() / 1000 + 3600,
    ...overrides,
  };
}

describe('ScheduleList', () => {
  const mockRefresh = vi.fn();
  const mockCreate = vi.fn();
  const mockEdit = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders header with title and create button', () => {
    render(
      <ScheduleList tasks={[]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('定时任务')).toBeInTheDocument();
    expect(screen.getByText('新建任务')).toBeInTheDocument();
  });

  it('shows empty state when no tasks', () => {
    render(
      <ScheduleList tasks={[]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('暂无定时任务')).toBeInTheDocument();
  });

  it('renders task name in table', () => {
    render(
      <ScheduleList tasks={[makeTask()]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('每日报告')).toBeInTheDocument();
  });

  it('renders cron as readable Chinese — daily', () => {
    render(
      <ScheduleList tasks={[makeTask({ cron: '0 9 * * *' })]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('每天 09:00')).toBeInTheDocument();
  });

  it('renders cron as readable Chinese — weekday', () => {
    render(
      <ScheduleList tasks={[makeTask({ cron: '30 8 * * 1-5' })]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('工作日 08:30')).toBeInTheDocument();
  });

  it('renders cron as readable Chinese — weekly', () => {
    render(
      <ScheduleList tasks={[makeTask({ cron: '0 14 * * 3' })]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('每周三 14:00')).toBeInTheDocument();
  });

  it('renders cron as readable Chinese — monthly', () => {
    render(
      <ScheduleList tasks={[makeTask({ cron: '0 10 15 * *' })]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('每月 15 日 10:00')).toBeInTheDocument();
  });

  it('shows "-" when last_run_at is null', () => {
    render(
      <ScheduleList tasks={[makeTask({ last_run_at: null })]} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('shows relative time for recent last_run_at', () => {
    const nowSec = Date.now() / 1000;
    render(
      <ScheduleList
        tasks={[makeTask({ last_run_at: nowSec - 120, last_run_status: 'success' })]}
        loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit}
      />
    );
    expect(screen.getByText('2分钟前')).toBeInTheDocument();
  });

  it('renders multiple tasks', () => {
    const tasks = [
      makeTask({ id: 't1', name: '任务A' }),
      makeTask({ id: 't2', name: '任务B' }),
      makeTask({ id: 't3', name: '任务C' }),
    ];
    render(
      <ScheduleList tasks={tasks} loading={false} onRefresh={mockRefresh} onCreate={mockCreate} onEdit={mockEdit} />
    );
    expect(screen.getByText('任务A')).toBeInTheDocument();
    expect(screen.getByText('任务B')).toBeInTheDocument();
    expect(screen.getByText('任务C')).toBeInTheDocument();
  });
});
