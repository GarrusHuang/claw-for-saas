import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import CronPicker from '../src/schedule/CronPicker.tsx';

describe('CronPicker', () => {
  const mockOnChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visual mode rendering ──

  it('renders frequency selector in visual mode', () => {
    render(<CronPicker value="0 9 * * *" onChange={mockOnChange} />);
    // Ant Select renders the selected value as text
    expect(screen.getByText('每天')).toBeInTheDocument();
  });

  it('renders "手动输入" link in visual mode', () => {
    render(<CronPicker value="0 9 * * *" onChange={mockOnChange} />);
    expect(screen.getByText('手动输入')).toBeInTheDocument();
  });

  it('shows weekday frequency correctly', () => {
    render(<CronPicker value="0 9 * * 1-5" onChange={mockOnChange} />);
    expect(screen.getByText('工作日')).toBeInTheDocument();
  });

  it('shows weekly frequency with day selector', () => {
    render(<CronPicker value="0 9 * * 3" onChange={mockOnChange} />);
    expect(screen.getByText('每周')).toBeInTheDocument();
    // Day-of-week selector should show 周三
    expect(screen.getByText('周三')).toBeInTheDocument();
  });

  it('shows monthly frequency with date selector', () => {
    render(<CronPicker value="0 9 15 * *" onChange={mockOnChange} />);
    expect(screen.getByText('每月')).toBeInTheDocument();
    // Date selector should show 15 日
    expect(screen.getByText('15 日')).toBeInTheDocument();
  });

  // ── Fallback mode ──

  it('falls back to raw input for unparseable cron', () => {
    render(<CronPicker value="*/5 * * * *" onChange={mockOnChange} />);
    // */5 is not parseable by the simple parser → fallback mode
    expect(screen.getByPlaceholderText('Cron 表达式 (例: 0 9 * * *)')).toBeInTheDocument();
    expect(screen.getByText('可视化')).toBeInTheDocument();
  });

  // ── Default state ──

  it('defaults to daily 09:00 when no value', () => {
    render(<CronPicker onChange={mockOnChange} />);
    expect(screen.getByText('每天')).toBeInTheDocument();
  });
});
