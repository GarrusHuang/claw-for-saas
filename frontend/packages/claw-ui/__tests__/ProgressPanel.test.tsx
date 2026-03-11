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
}));

describe('ProgressPanel', () => {
  let ProgressPanel: typeof import('../src/chat/ProgressPanel.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockState = createMockState();
    const mod = await import('../src/chat/ProgressPanel.tsx');
    ProgressPanel = mod.default;
  });

  it('returns null when idle with no tool executions, no plan, and no planSteps', () => {
    const { container } = render(<ProgressPanel plan={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders "Progress" header when running', () => {
    mockState = createMockState({ status: 'running', startedAt: Date.now() });
    render(<ProgressPanel plan={null} />);
    expect(screen.getByText('Progress')).toBeInTheDocument();
  });

  it('shows "任务进度" title when planSteps exist without agentPlanProposed', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      agentPlanProposed: false,
      planSteps: [
        { step: 1, description: '推断报销类型', status: 'running', startedAt: Date.now(), completedAt: null },
        { step: 2, description: '填写表单', status: 'pending', startedAt: null, completedAt: null },
      ],
    });

    render(<ProgressPanel plan={null} />);

    expect(screen.getByText('任务进度')).toBeInTheDocument();
    expect(screen.getByText('推断报销类型')).toBeInTheDocument();
    expect(screen.getByText('填写表单')).toBeInTheDocument();
  });

  it('shows "任务进度" title when agentPlanProposed is true with planSteps', () => {
    mockState = createMockState({
      status: 'plan_awaiting',
      agentPlanProposed: true,
      planSteps: [
        { step: 1, description: '推断单据类型', status: 'pending', startedAt: null, completedAt: null },
        { step: 2, description: '填写表单', status: 'pending', startedAt: null, completedAt: null },
      ],
    });

    const plan = {
      summary: '报销创建方案',
      detail: '',
      steps: [
        { step: 1, description: '推断单据类型' },
        { step: 2, description: '填写表单' },
      ],
      estimatedActions: 10,
      requiresApproval: true,
    };

    render(<ProgressPanel plan={plan} />);

    expect(screen.getByText('任务进度')).toBeInTheDocument();
    expect(screen.getByText('推断单据类型')).toBeInTheDocument();
    expect(screen.getByText('填写表单')).toBeInTheDocument();
    expect(screen.getByText('待确认')).toBeInTheDocument();
  });

  it('shows "待确认" badge for plan_awaiting with requiresApproval', () => {
    mockState = createMockState({
      status: 'plan_awaiting',
      agentPlanProposed: true,
      planSteps: [
        { step: 1, description: '步骤1', status: 'pending', startedAt: null, completedAt: null },
      ],
    });

    const plan = {
      summary: '方案',
      detail: '',
      steps: [{ step: 1, description: '步骤1' }],
      estimatedActions: 5,
      requiresApproval: true,
    };

    render(<ProgressPanel plan={plan} />);

    expect(screen.getByText('待确认')).toBeInTheDocument();
    expect(screen.getByText('步骤1')).toBeInTheDocument();
  });

  it('shows iteration and tool call stats when running', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now() - 3000,
      agentIteration: { current: 3, max: 15, callingTools: [] },
      toolExecutions: [
        { id: 't1', toolName: 'get_user_profile', success: true, latencyMs: 100, timestamp: Date.now() },
        { id: 't2', toolName: 'classify_type', success: true, latencyMs: 200, timestamp: Date.now() },
      ],
    });

    render(<ProgressPanel plan={null} />);

    expect(screen.getByText('迭代 3/15')).toBeInTheDocument();
    expect(screen.getByText('2 次工具调用')).toBeInTheDocument();
  });

  it('shows workflow phase when running', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      workflowPhase: 'form_filling',
      workflowProgress: 0.6,
    });

    render(<ProgressPanel plan={null} />);

    expect(screen.getByText('工作流阶段')).toBeInTheDocument();
    expect(screen.getByText('表单填写')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  it('shows parallel review running state', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      parallelReview: {
        roles: ['data-validator', 'compliance-reviewer'],
        status: 'running',
        overallStatus: '',
        overallConfidence: 0,
        results: [],
        durationMs: 0,
      },
    });

    render(<ProgressPanel plan={null} />);

    expect(screen.getByText('多 Agent 审查')).toBeInTheDocument();
    expect(screen.getByText('并行审查中...')).toBeInTheDocument();
    expect(screen.getByText('data-validator')).toBeInTheDocument();
    expect(screen.getByText('compliance-reviewer')).toBeInTheDocument();
  });

  it('shows parallel review completed state', () => {
    mockState = createMockState({
      status: 'completed',
      durationMs: 5000,
      parallelReview: {
        roles: ['data-validator'],
        status: 'completed',
        overallStatus: '通过',
        overallConfidence: 0.92,
        results: [
          { agentRole: 'data-validator', conclusion: '通过', confidence: 0.92, findings: [] },
        ],
        durationMs: 3000,
      },
    });

    render(<ProgressPanel plan={null} />);

    expect(screen.getByText('多 Agent 审查')).toBeInTheDocument();
    expect(screen.getByText('通过')).toBeInTheDocument();
    expect(screen.getByText('data-validator')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
  });

  it('shows tool call log section when expanded', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      toolExecutions: [
        {
          id: 't1',
          toolName: 'get_expense_standards',
          success: true,
          latencyMs: 230,
          timestamp: Date.now(),
          argsSummary: { city: '上海', level: '处级' },
          resultSummary: '标准: 住宿≤500/晚',
        },
        {
          id: 't2',
          toolName: 'run_command',
          success: false,
          latencyMs: 50,
          timestamp: Date.now(),
          blocked: true,
          resultSummary: 'Hook blocked: 安全检查',
        },
      ],
    });

    render(<ProgressPanel plan={null} />);

    // Tool log section title should show
    expect(screen.getByText('工具调用')).toBeInTheDocument();
    expect(screen.getByText('(2)')).toBeInTheDocument();

    // Expand the tool log
    const user = userEvent.setup();
    await user.click(screen.getByText('工具调用'));

    // Tool names and details should be visible
    expect(screen.getByText('get_expense_standards')).toBeInTheDocument();
    expect(screen.getByText('run_command')).toBeInTheDocument();
    expect(screen.getByText('(230ms)')).toBeInTheDocument();
  });

  it('shows thinking section when showThinking and thinkingText present', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      thinkingText: '让我分析一下这份报销材料...',
      isStreaming: true,
    });

    render(<ProgressPanel plan={null} showThinking />);

    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(screen.getByText('让我分析一下这份报销材料...')).toBeInTheDocument();
  });

  it('hides thinking section when showThinking is false', () => {
    mockState = createMockState({
      status: 'running',
      startedAt: Date.now(),
      thinkingText: '思考中...',
    });

    render(<ProgressPanel plan={null} showThinking={false} />);

    expect(screen.queryByText('Thinking')).not.toBeInTheDocument();
  });

});
