import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Default mock state factory
function createMockState(overrides: Record<string, unknown> = {}) {
  return {
    status: 'idle',
    toolExecutions: [],
    agentIteration: { current: 0, max: 15, callingTools: [] },
    agentPlanProposed: false,
    planSteps: [],
    startedAt: null,
    durationMs: 0,
    thinkingText: '',
    isStreaming: false,
    workflowPhase: '',
    workflowProgress: 0,
    parallelReview: null,
    ...overrides,
  };
}

let mockState = createMockState();

vi.mock('@claw/core', () => ({
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    return selector(mockState);
  }),
  useAIChatStore: vi.fn((selector?: (state: Record<string, unknown>) => unknown) => {
    const state = { chatDialogState: 'closed', activeScenario: null };
    return selector ? selector(state) : state;
  }),
  aiApi: {
    listTools: vi.fn().mockResolvedValue([]),
    listKnowledgeFiles: vi.fn().mockResolvedValue({ files: [] }),
    listUserFiles: vi.fn().mockResolvedValue([]),
  },
  getAIConfig: vi.fn(() => ({ aiBaseUrl: '' })),
}));

describe('ProgressPanel', () => {
  let ProgressPanel: typeof import('../src/chat/ProgressPanel.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockState = createMockState();
    const mod = await import('../src/chat/ProgressPanel.tsx');
    ProgressPanel = mod.default;
  });

  it('renders Progress section header', () => {
    mockState = createMockState({ status: 'running', startedAt: Date.now() });
    render(<ProgressPanel />);
    expect(screen.getByText('进度')).toBeInTheDocument();
  });

  it('renders Artifacts section', () => {
    mockState = createMockState({ status: 'running', startedAt: Date.now() });
    render(<ProgressPanel />);
    expect(screen.getByText('制品')).toBeInTheDocument();
  });

  it('renders Knowledge Base section', () => {
    mockState = createMockState({ status: 'running', startedAt: Date.now() });
    render(<ProgressPanel />);
    expect(screen.getByText('知识库')).toBeInTheDocument();
  });

  it('shows plan steps when they exist', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      planSteps: [
        { step: 1, description: '推断报销类型', status: 'running', startedAt: Date.now(), completedAt: null },
        { step: 2, description: '填写表单', status: 'pending', startedAt: null, completedAt: null },
      ],
    });

    render(<ProgressPanel />);

    expect(screen.getByText('推断报销类型')).toBeInTheDocument();
    expect(screen.getByText('填写表单')).toBeInTheDocument();
  });

  it('shows "暂无活跃任务" when no plan steps', () => {
    mockState = createMockState({ status: 'running', startedAt: Date.now() });
    render(<ProgressPanel />);
    expect(screen.getByText('暂无活跃任务')).toBeInTheDocument();
  });

  it('shows artifacts from write_source_file tool executions', () => {
    mockState = createMockState({
      status: 'completed',
      durationMs: 5000,
      toolExecutions: [
        {
          id: 't1',
          toolName: 'write_source_file',
          success: true,
          latencyMs: 100,
          timestamp: Date.now(),
          argsSummary: { file_path: '/tmp/report.docx' },
        },
      ],
    });

    render(<ProgressPanel />);
    expect(screen.getByText('report.docx')).toBeInTheDocument();
  });
});
