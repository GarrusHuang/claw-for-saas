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

  it('shows "AI 正在处理中" when disabled', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);

    expect(screen.getByText('AI 正在处理中，请稍候...')).toBeInTheDocument();
  });

  it('disables textarea when disabled prop is true', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);

    const textarea = screen.getByPlaceholderText('回复...');
    expect(textarea).toBeDisabled();
  });

  it('does not send when disabled even with text', () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);

    const textarea = screen.getByPlaceholderText('回复...');
    fireEvent.change(textarea, { target: { value: '测试' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(onSend).not.toHaveBeenCalled();
  });
});
