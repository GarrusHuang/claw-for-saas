import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';

// ── Mocks — must be defined before imports ──

vi.mock('@claw/core', () => ({
  useAIChatStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      dispatchSessionAction: vi.fn(),
      chatDialogState: 'closed',
      activeScenario: null,
      contentView: 'chat',
      setContentView: vi.fn(),
    };
    return selector(state);
  }),
  usePipelineStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
      const state = {
        sessionId: null,
        status: 'idle',
      };
      return selector(state);
    }),
    { getState: () => ({ sessionId: null, status: 'idle' }) },
  ),
  useSessionStatusStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      unreadIds: new Set(),
      runningIds: new Set(),
      markRead: vi.fn(),
    };
    return selector(state);
  }),
  aiApi: {
    listSessions: vi.fn().mockResolvedValue([]),
  },
  getAIConfig: vi.fn(() => ({ defaultUserId: 'U001' })),
  useNotifications: vi.fn(),
}));

// ── Tests ──

describe('CoworkSidebar', () => {
  it('renders "新任务" entry', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    await act(async () => {
      render(<CoworkSidebar />);
    });

    expect(screen.getByText('新建任务')).toBeInTheDocument();
  });

  it('renders Recents section title', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    await act(async () => {
      render(<CoworkSidebar />);
    });

    expect(screen.getByText('最近')).toBeInTheDocument();
  });

  it('shows "暂无会话" when no sessions', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    await act(async () => {
      render(<CoworkSidebar />);
    });

    expect(screen.getByText('暂无会话')).toBeInTheDocument();
  });

  it('renders function entries (Skills, Search, etc.)', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    await act(async () => {
      render(<CoworkSidebar />);
    });

    expect(screen.getByText('技能')).toBeInTheDocument();
    expect(screen.getByText('搜索')).toBeInTheDocument();
    expect(screen.getByText('定时任务')).toBeInTheDocument();
  });
});
