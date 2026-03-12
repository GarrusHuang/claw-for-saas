import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// ── Mock @claw/core ──
const mockCreateSchedule = vi.fn().mockResolvedValue({ id: 'new-1' });
const mockUpdateSchedule = vi.fn().mockResolvedValue({ id: 'edit-1' });

vi.mock('@claw/core', () => ({
  aiApi: {
    createSchedule: (...args: unknown[]) => mockCreateSchedule(...args),
    updateSchedule: (...args: unknown[]) => mockUpdateSchedule(...args),
  },
}));

import ScheduleForm from '../src/schedule/ScheduleForm.tsx';

function makeTask(overrides = {}): import('@claw/core').ScheduledTask {
  return {
    id: 'task-edit-1',
    name: '已有任务',
    cron: '30 14 * * 1-5',
    message: '执行审计',
    user_id: 'U001',
    tenant_id: 'default',
    business_type: 'audit_task',
    enabled: true,
    created_at: Date.now() / 1000,
    last_run_at: null,
    last_run_status: '',
    next_run_at: null,
    ...overrides,
  };
}

describe('ScheduleForm', () => {
  const mockBack = vi.fn();
  const mockSuccess = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Create mode ──

  it('shows "创建任务" title in create mode', () => {
    const { container } = render(<ScheduleForm editTask={null} onBack={mockBack} onSuccess={mockSuccess} />);
    expect(container.querySelector('h2')?.textContent).toBe('创建任务');
  });

  it('shows back button with "返回任务列表"', () => {
    render(<ScheduleForm editTask={null} onBack={mockBack} onSuccess={mockSuccess} />);
    expect(screen.getByText('返回任务列表')).toBeInTheDocument();
  });

  it('shows form labels', () => {
    render(<ScheduleForm editTask={null} onBack={mockBack} onSuccess={mockSuccess} />);
    expect(screen.getByText('标题')).toBeInTheDocument();
    expect(screen.getByText('提示词')).toBeInTheDocument();
    expect(screen.getByText('计划')).toBeInTheDocument();
    expect(screen.getByText('业务类型')).toBeInTheDocument();
  });

  it('has cancel and submit buttons in create mode', () => {
    const { container } = render(<ScheduleForm editTask={null} onBack={mockBack} onSuccess={mockSuccess} />);
    const buttons = container.querySelectorAll('button');
    // Ant Design inserts spaces in short CJK button text (取 消), normalize
    const texts = Array.from(buttons).map((b) => b.textContent?.replace(/\s/g, ''));
    expect(texts).toContain('取消');
    expect(texts).toContain('创建任务');
  });

  // ── Edit mode ──

  it('shows "更新任务" in edit mode', () => {
    const { container } = render(<ScheduleForm editTask={makeTask()} onBack={mockBack} onSuccess={mockSuccess} />);
    expect(container.querySelector('h2')?.textContent).toBe('更新任务');
    const buttons = container.querySelectorAll('button');
    const texts = Array.from(buttons).map((b) => b.textContent);
    expect(texts).toContain('更新任务');
  });
});
