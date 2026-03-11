import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Polyfill scrollIntoView for jsdom
Element.prototype.scrollIntoView = vi.fn();

// ── Track Markdown renders ──
const mockMarkdown = vi.fn();
const mockRemarkGfm = vi.fn();

vi.mock('react-markdown', () => ({
  default: (props: { children: string; remarkPlugins?: unknown[] }) => {
    mockMarkdown(props);
    return <div data-testid="markdown">{props.children}</div>;
  },
}));

vi.mock('remark-gfm', () => ({
  default: mockRemarkGfm,
}));

// ── Mock stores ──
let mockPipelineState: Record<string, unknown> = {};

vi.mock('@claw/core', () => ({
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    return selector(mockPipelineState);
  }),
}));

// Mock sub-components to isolate ChatMessageList
vi.mock('../src/chat/ChatResultCards.tsx', () => ({
  MiniTypeInference: () => null,
  MiniFieldUpdates: () => null,
  MiniAuditSummary: () => null,
}));

vi.mock('../src/results/DocumentPresenter.tsx', () => ({
  default: () => null,
}));

vi.mock('../src/chat/InlineUploader.tsx', () => ({
  default: () => null,
}));

vi.mock('../src/chat/InteractiveMessage.tsx', () => ({
  default: () => null,
}));

vi.mock('../src/chat/CollapsibleBlock.tsx', () => ({
  default: ({ children, summary }: { children: React.ReactNode; summary: string }) => (
    <div data-testid="collapsible-block">{summary}{children}</div>
  ),
}));

describe('ChatMessageList', () => {
  let ChatMessageList: typeof import('../src/chat/ChatMessageList.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockPipelineState = {
      status: 'idle',
      scenario: null,
      thinkingText: '',
      isStreaming: false,
      pendingInteraction: null,
      resolveInteraction: vi.fn(),
      toolExecutions: [],
      fieldValues: [],
      inferredType: null,
      auditSummary: null,
      document: null,
      plan: null,
      agentPlanProposed: false,
      durationMs: 0,
    };
    const mod = await import('../src/chat/ChatMessageList.tsx');
    ChatMessageList = mod.default;
  });

  it('renders AI messages with Markdown component', () => {
    const messages = [
      { id: '1', role: 'assistant' as const, content: '**Hello** world', timestamp: Date.now() },
    ];

    render(<ChatMessageList messages={messages} />);

    expect(mockMarkdown).toHaveBeenCalled();
    const call = mockMarkdown.mock.calls[0][0];
    expect(call.children).toBe('**Hello** world');
  });

  it('passes remarkGfm plugin to Markdown', () => {
    const messages = [
      { id: '1', role: 'assistant' as const, content: 'GFM table test', timestamp: Date.now() },
    ];

    render(<ChatMessageList messages={messages} />);

    const call = mockMarkdown.mock.calls[0][0];
    expect(call.remarkPlugins).toBeDefined();
    expect(call.remarkPlugins).toContain(mockRemarkGfm);
  });

  it('renders user messages with msg-user class', () => {
    const messages = [
      { id: '1', role: 'user' as const, content: 'User question', timestamp: Date.now() },
    ];

    render(<ChatMessageList messages={messages} />);

    const userMsg = screen.getByText('User question');
    // The msg-user class is on the parent div
    expect(userMsg.closest('.msg-user')).not.toBeNull();
  });

  it('renders PlanCard markdown with GFM when plan is proposed', () => {
    mockPipelineState = {
      ...mockPipelineState,
      status: 'running',
      scenario: 'some_scenario',
      plan: {
        summary: 'Test plan',
        detail: '## Plan detail\n\n| Col1 | Col2 |\n|------|------|\n| a | b |',
        steps: [],
        estimatedActions: 3,
      },
      agentPlanProposed: true,
    };

    const messages: { id: string; role: 'user' | 'assistant'; content: string; timestamp: number }[] = [];

    render(<ChatMessageList messages={messages} showPipelineProgress />);

    // PlanCard should render Markdown with remarkGfm for plan.detail
    const markdownCalls = mockMarkdown.mock.calls;
    const planCall = markdownCalls.find(
      (call) => call[0].children && call[0].children.includes('Plan detail'),
    );
    expect(planCall).toBeDefined();
    expect(planCall![0].remarkPlugins).toContain(mockRemarkGfm);
  });
});
