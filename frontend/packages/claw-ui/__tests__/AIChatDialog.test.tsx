import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// ── Mock state for controlling chatDialogState per test ──
let mockChatDialogState = 'closed';
const mockCloseChat = vi.fn();
const mockSendMessage = vi.fn();

vi.mock('@claw/core', () => ({
  useAIChatStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      chatDialogState: mockChatDialogState,
      contentView: 'chat',
      closeChat: mockCloseChat,
      activeScenario: null,
    };
    return selector(state);
  }),
  useAIChat: vi.fn(() => ({
    messages: [],
    sendMessage: mockSendMessage,
    isRunning: false,
  })),
  usePipelineStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
      const state = {
        status: 'idle',
        fieldValues: [],
        toolExecutions: [],
        scenario: null,
        thinkingText: '',
        isStreaming: false,
        pendingInteraction: null,
        resolveInteraction: vi.fn(),
      };
      return selector(state);
    }),
    { getState: () => ({ status: 'idle' }) },
  ),
  useAuthStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      logout: vi.fn(),
      userId: 'test-user',
    };
    return selector(state);
  }),
  aiApi: {
    listKnowledgeFiles: vi.fn(),
    uploadKnowledgeFile: vi.fn(),
    deleteKnowledgeFile: vi.fn(),
    uploadFile: vi.fn(),
  },
}));

// Mock child components to isolate AIChatDialog tests
vi.mock('../src/chat/ChatMessageList.tsx', () => ({
  default: () => <div data-testid="chat-message-list">ChatMessageList</div>,
}));

vi.mock('../src/chat/ChatInput.tsx', () => ({
  default: (props: { onSend: () => void; disabled: boolean; placeholder: string }) => (
    <div data-testid="chat-input">ChatInput</div>
  ),
}));

vi.mock('../src/chat/CoworkSidebar.tsx', () => ({
  default: () => <div data-testid="cowork-sidebar">CoworkSidebar</div>,
}));

vi.mock('../src/chat/ProgressPanel.tsx', () => ({
  default: () => <div data-testid="progress-panel">ProgressPanel</div>,
}));

vi.mock('../src/schedule/ScheduleView.tsx', () => ({
  default: () => <div data-testid="schedule-view">ScheduleView</div>,
}));

vi.mock('../src/skills/SkillsView.tsx', () => ({
  default: () => <div data-testid="skills-view">SkillsView</div>,
}));

vi.mock('../src/knowledge/KnowledgeView.tsx', () => ({
  default: () => <div data-testid="knowledge-view">KnowledgeView</div>,
}));

describe('AIChatDialog', () => {
  let AIChatDialog: typeof import('../src/AIChatDialog.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockChatDialogState = 'fullscreen';
    const mod = await import('../src/AIChatDialog.tsx');
    AIChatDialog = mod.default;
  });

  // ── F2 三栏布局 (Cowork 固定布局，无 tab 切换) ──

  describe('Three-column layout', () => {
    it('always shows CoworkSidebar', () => {
      render(<AIChatDialog />);
      expect(screen.getByTestId('cowork-sidebar')).toBeInTheDocument();
    });

    it('always shows ProgressPanel', () => {
      render(<AIChatDialog />);
      expect(screen.getByTestId('progress-panel')).toBeInTheDocument();
    });

    it('shows WelcomeScreen when no messages', () => {
      render(<AIChatDialog />);
      // WelcomeScreen includes ChatInput and welcome text
      expect(screen.getByText('Xisoft Claw', { selector: 'div' })).toBeInTheDocument();
    });

    it('shows ChatInput (in WelcomeScreen)', () => {
      render(<AIChatDialog />);
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    it('has no tab buttons', () => {
      render(<AIChatDialog />);
      expect(screen.queryByText('Chat')).toBeNull();
      expect(screen.queryByText('Code')).toBeNull();
    });
  });

  // ── F2 Expand/Collapse mode ──

  describe('Expand/Collapse mode', () => {
    it('does not render when chatDialogState is closed', async () => {
      mockChatDialogState = 'closed';
      const mod = await import('../src/AIChatDialog.tsx');
      const Dialog = mod.default;

      const { container } = render(<Dialog />);
      expect(container.querySelector('.ai-chat-dialog')).toBeNull();
    });

    it('renders when chatDialogState is fullscreen', () => {
      mockChatDialogState = 'fullscreen';
      render(<AIChatDialog />);

      expect(screen.getAllByText('Xisoft Claw').length).toBeGreaterThan(0);
    });

    it('renders when chatDialogState is sidepanel', async () => {
      mockChatDialogState = 'sidepanel';
      const mod = await import('../src/AIChatDialog.tsx');
      const Dialog = mod.default;

      render(<Dialog />);
      expect(screen.getAllByText('Xisoft Claw').length).toBeGreaterThan(0);
    });

    it('calls onResize with correct mode', async () => {
      const onResize = vi.fn();
      mockChatDialogState = 'fullscreen';

      const mod = await import('../src/AIChatDialog.tsx');
      const Dialog = mod.default;

      render(<Dialog onResize={onResize} />);

      // fullscreen → 'expanded'
      expect(onResize).toHaveBeenCalledWith('expanded');
    });
  });
});
