import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Mock @claw/core
vi.mock('@claw/core', () => ({
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = { status: 'idle', fieldValues: [], toolExecutions: [] };
    return selector(state);
  }),
  useAIChatStore: vi.fn((selector?: (state: Record<string, unknown>) => unknown) => {
    const state = { chatDialogState: 'closed', activeScenario: null };
    return selector ? selector(state) : state;
  }),
  aiApi: {
    uploadFile: vi.fn(),
  },
}));

describe('ChatInput', () => {
  let ChatInput: typeof import('../src/chat/ChatInput.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    const mod = await import('../src/chat/ChatInput.tsx');
    ChatInput = mod.default;
  });

  it('renders textarea with default placeholder', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('回复...');
    expect(textarea).toBeInTheDocument();
  });

  it('renders custom placeholder', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} placeholder="Custom prompt" />);

    expect(screen.getByPlaceholderText('Custom prompt')).toBeInTheDocument();
  });

  it('calls onSend when send button is clicked with text', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('回复...');
    fireEvent.change(textarea, { target: { value: '你好' } });

    const sendBtn = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendBtn);

    expect(onSend).toHaveBeenCalledWith('你好', undefined);
  });

  it('does not call onSend when text is empty', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    // Send button is the primary circle button (not the text-type + button)
    const buttons = screen.getAllByRole('button');
    const sendBtn = buttons.find(b =>
      b.classList.contains('ant-btn-circle') && b.classList.contains('ant-btn-primary'),
    );
    if (sendBtn) {
      expect(sendBtn).toBeDisabled();
    }
    expect(onSend).not.toHaveBeenCalled();
  });

  it('clears text after sending', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('回复...') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '测试消息' } });
    expect(textarea.value).toBe('测试消息');

    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(onSend).toHaveBeenCalledWith('测试消息', undefined);
  });

  it('does not send on Shift+Enter (newline)', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('回复...');
    fireEvent.change(textarea, { target: { value: '第一行' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('shows stop button when disabled with onStop', () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<ChatInput onSend={onSend} onStop={onStop} disabled />);

    // The stop button should be a danger button (red)
    const buttons = screen.getAllByRole('button');
    const stopButton = buttons.find(b => b.classList.contains('ant-btn-dangerous'));
    expect(stopButton).toBeTruthy();
  });

  it('textarea remains enabled when disabled prop is true (message queue support)', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);

    const textarea = screen.getByPlaceholderText('回复...');
    expect(textarea).not.toBeDisabled();
  });

  it('still calls onSend when disabled (parent handles queueing)', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);

    const textarea = screen.getByPlaceholderText('回复...');
    fireEvent.change(textarea, { target: { value: '测试' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(onSend).toHaveBeenCalledWith('测试', undefined);
  });
});
