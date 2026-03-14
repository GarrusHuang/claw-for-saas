import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

// ── Mock @claw/core ──
const mockListSchedules = vi.fn();
const mockPauseSchedule = vi.fn().mockResolvedValue({ status: 'ok' });
const mockResumeSchedule = vi.fn().mockResolvedValue({ status: 'ok' });
const mockDeleteSchedule = vi.fn().mockResolvedValue({ status: 'ok' });
const mockCreateSchedule = vi.fn().mockResolvedValue({ id: 'new-1' });
const mockUpdateSchedule = vi.fn().mockResolvedValue({ id: 'edit-1' });

vi.mock('@claw/core', () => ({
  aiApi: {
    listSchedules: (...args: unknown[]) => mockListSchedules(...args),
    pauseSchedule: (...args: unknown[]) => mockPauseSchedule(...args),
    resumeSchedule: (...args: unknown[]) => mockResumeSchedule(...args),
    deleteSchedule: (...args: unknown[]) => mockDeleteSchedule(...args),
    createSchedule: (...args: unknown[]) => mockCreateSchedule(...args),
    updateSchedule: (...args: unknown[]) => mockUpdateSchedule(...args),
  },
}));

import ScheduleView from '../src/schedule/ScheduleView.tsx';

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
    scheduled_at: null,
    expires_at: null,
    run_history: [],
    ...overrides,
  };
}

describe('ScheduleView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── List view (default) ──

  it('fetches tasks on mount and shows list view', async () => {
    mockListSchedules.mockResolvedValue({ tasks: [makeTask()], total: 1 });

    await act(async () => {
      render(<ScheduleView />);
    });

    expect(mockListSchedules).toHaveBeenCalledTimes(1);
    expect(screen.getByText('每日报告')).toBeInTheDocument();
    expect(screen.getByText('定时任务')).toBeInTheDocument();
  });

  it('shows empty table when no tasks', async () => {
    mockListSchedules.mockResolvedValue({ tasks: [], total: 0 });

    await act(async () => {
      render(<ScheduleView />);
    });

    expect(screen.getByText('暂无定时任务')).toBeInTheDocument();
  });

  it('handles API error gracefully', async () => {
    mockListSchedules.mockRejectedValue(new Error('Network error'));

    // Should not throw
    await act(async () => {
      render(<ScheduleView />);
    });

    // Should show empty table
    expect(screen.getByText('暂无定时任务')).toBeInTheDocument();
  });

  // ── View switching ──

  it('clicking "新建任务" switches to create form', async () => {
    mockListSchedules.mockResolvedValue({ tasks: [], total: 0 });

    await act(async () => {
      render(<ScheduleView />);
    });

    await act(async () => {
      screen.getByText('新建任务').click();
    });

    // Should show create form — use heading to avoid multiple match with button
    expect(screen.getByRole('heading', { name: '创建任务' })).toBeInTheDocument();
    expect(screen.getByText('返回任务列表')).toBeInTheDocument();
  });

  it('"返回任务列表" goes back to list and refetches', async () => {
    mockListSchedules.mockResolvedValue({ tasks: [], total: 0 });

    await act(async () => {
      render(<ScheduleView />);
    });

    // Go to create form
    await act(async () => {
      screen.getByText('新建任务').click();
    });
    expect(screen.getByRole('heading', { name: '创建任务' })).toBeInTheDocument();

    // Go back
    await act(async () => {
      screen.getByText('返回任务列表').click();
    });

    // Should show list again
    expect(screen.getByRole('heading', { name: '定时任务' })).toBeInTheDocument();
    expect(screen.getByText('新建任务')).toBeInTheDocument();
  });

  // ── Multiple tasks ──

  it('renders multiple tasks from API', async () => {
    mockListSchedules.mockResolvedValue({
      tasks: [
        makeTask({ id: 't1', name: '日报', cron: '0 9 * * *' }),
        makeTask({ id: 't2', name: '周报', cron: '0 9 * * 1' }),
        makeTask({ id: 't3', name: '月报', cron: '0 9 1 * *' }),
      ],
      total: 3,
    });

    await act(async () => {
      render(<ScheduleView />);
    });

    expect(screen.getByText('日报')).toBeInTheDocument();
    expect(screen.getByText('周报')).toBeInTheDocument();
    expect(screen.getByText('月报')).toBeInTheDocument();
  });
});
