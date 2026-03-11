import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// ── Mock state for controlling chatDialogState per test ──
let mockChatDialogState = 'closed';
const mockCloseChat = vi.fn();
const mockSendMessage = vi.fn();

vi.mock('@claw/core', () => ({
  useAIChatStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      chatDialogState: mockChatDialogState,
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
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
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

describe('AIChatDialog', () => {
  let AIChatDialog: typeof import('../src/AIChatDialog.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockChatDialogState = 'fullscreen';
    const mod = await import('../src/AIChatDialog.tsx');
    AIChatDialog = mod.default;
  });

  // ── F2 Tab switching ──

  describe('Tab switching', () => {
    it('defaults to cowork tab', () => {
      render(<AIChatDialog />);

      const coworkTab = screen.getByText('Cowork');
      expect(coworkTab).toHaveClass('header-tab--active');
    });

    it('switches to Chat tab when clicked', () => {
      render(<AIChatDialog />);

      const chatTab = screen.getByText('Chat');
      fireEvent.click(chatTab);

      expect(chatTab).toHaveClass('header-tab--active');
    });

    it('switches to Code tab when clicked', () => {
      render(<AIChatDialog />);

      const codeTab = screen.getByText('Code');
      fireEvent.click(codeTab);

      expect(codeTab).toHaveClass('header-tab--active');
    });

    it('shows CoworkSidebar only in cowork tab', () => {
      render(<AIChatDialog />);

      // Default is cowork — sidebar visible
      expect(screen.getByTestId('cowork-sidebar')).toBeInTheDocument();

      // Switch to chat — sidebar hidden
      fireEvent.click(screen.getByText('Chat'));
      expect(screen.queryByTestId('cowork-sidebar')).not.toBeInTheDocument();
    });

    it('shows ProgressPanel only in cowork tab', () => {
      render(<AIChatDialog />);

      // Default is cowork — panel visible
      expect(screen.getByTestId('progress-panel')).toBeInTheDocument();

      // Switch to code — panel hidden
      fireEvent.click(screen.getByText('Code'));
      expect(screen.queryByTestId('progress-panel')).not.toBeInTheDocument();
    });
  });

  // ── F2 Expand/Collapse mode ──

  describe('Expand/Collapse mode', () => {
    it('does not render when chatDialogState is closed', async () => {
      mockChatDialogState = 'closed';
      // Re-import to pick up new state
      const mod = await import('../src/AIChatDialog.tsx');
      const Dialog = mod.default;

      const { container } = render(<Dialog />);
      expect(container.querySelector('.ai-chat-dialog')).toBeNull();
    });

    it('renders when chatDialogState is fullscreen', () => {
      mockChatDialogState = 'fullscreen';
      render(<AIChatDialog />);

      expect(screen.getByText('Claw')).toBeInTheDocument();
      expect(screen.getByTestId('chat-message-list')).toBeInTheDocument();
    });

    it('renders when chatDialogState is sidepanel', async () => {
      mockChatDialogState = 'sidepanel';
      const mod = await import('../src/AIChatDialog.tsx');
      const Dialog = mod.default;

      render(<Dialog />);
      expect(screen.getByText('Claw')).toBeInTheDocument();
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
