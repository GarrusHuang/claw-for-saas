import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// ── Mocks — must be defined before imports ──

vi.mock('@claw/core', () => ({
  useAIChatStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      dispatchSessionAction: vi.fn(),
      chatDialogState: 'closed',
      activeScenario: null,
    };
    return selector(state);
  }),
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      sessionId: null,
      status: 'idle',
    };
    return selector(state);
  }),
  aiApi: {
    listSessions: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue({ skills: [], total: 0 }),
    listTools: vi.fn().mockResolvedValue([]),
    getSkillDetail: vi.fn().mockResolvedValue({}),
    deleteSkill: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

vi.mock('../src/skills/SkillEditorModal.tsx', () => ({
  default: () => null,
}));

vi.mock('../src/skills/ImportModal.tsx', () => ({
  default: () => null,
}));

// ── Tests ──

describe('CoworkSidebar', () => {
  it('renders "新对话" button', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    render(<CoworkSidebar />);

    expect(screen.getByText('新对话')).toBeInTheDocument();
  });

  it('renders Sessions section title', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    render(<CoworkSidebar />);

    expect(screen.getByText('Sessions')).toBeInTheDocument();
  });

  it('shows "暂无会话" when no sessions', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    render(<CoworkSidebar />);

    expect(screen.getByText('暂无会话')).toBeInTheDocument();
  });

  it('renders Skills and MCP Tools collapse panels', async () => {
    const { default: CoworkSidebar } = await import(
      '../src/chat/CoworkSidebar.tsx'
    );

    render(<CoworkSidebar />);

    expect(screen.getByText('Skills')).toBeInTheDocument();
    expect(screen.getByText('MCP Tools')).toBeInTheDocument();
  });
});
