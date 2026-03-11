import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Mock @claw/core
vi.mock('@claw/core', () => ({
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = { status: 'idle' };
    return selector(state);
  }),
  useAIChatStore: vi.fn((selector?: (state: Record<string, unknown>) => unknown) => {
    const state = { chatDialogState: 'closed', activeScenario: null };
    return selector ? selector(state) : state;
  }),
  getAllScenarios: vi.fn(() => [
    {
      key: 'reimbursement_create',
      title: '报销创建',
      promptDescription: '创建差旅报销单',
      promptSubtext: '自动填写报销表单',
      action: 'create',
      businessType: '报销',
      smartButtonLabel: '智能填单',
      routePath: '/reimbursement/create',
      sampleMaterial: '',
      candidateTypes: [],
      formFields: [],
      auditRules: [],
      knownValues: [],
      formSections: [],
    },
    {
      key: 'reimbursement_review',
      title: '报销审核',
      promptDescription: '审核报销单据',
      promptSubtext: '智能审计检查',
      action: 'review',
      businessType: '报销',
      smartButtonLabel: '智能审核',
      routePath: '/reimbursement/review',
      sampleMaterial: '',
      candidateTypes: [],
      formFields: [],
      auditRules: [],
      knownValues: [],
      formSections: [],
    },
  ]),
}));

describe('PromptCards', () => {
  let PromptCards: typeof import('../src/chat/PromptCards.tsx').default;

  beforeEach(async () => {
    vi.clearAllMocks();
    const mod = await import('../src/chat/PromptCards.tsx');
    PromptCards = mod.default;
  });

  it('renders welcome title "Claw AI助手"', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText('Claw AI助手')).toBeInTheDocument();
  });

  it('renders welcome subtitle', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText(/Claw AI/)).toBeInTheDocument();
  });

  it('renders 4 capability tags', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText('智能填单')).toBeInTheDocument();
    expect(screen.getByText('智能审核')).toBeInTheDocument();
    expect(screen.getByText('智能起草')).toBeInTheDocument();
    expect(screen.getByText('智能鉴审')).toBeInTheDocument();
  });

  it('renders suggested questions', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText('What can Claw do?')).toBeInTheDocument();
    expect(screen.getByText('报销流程多久能审批完成？')).toBeInTheDocument();
  });

  it('calls onAsk when suggested question clicked', () => {
    const onSelect = vi.fn();
    const onAsk = vi.fn();
    render(<PromptCards onSelect={onSelect} onAsk={onAsk} />);

    fireEvent.click(screen.getByText('What can Claw do?'));
    expect(onAsk).toHaveBeenCalledWith('What can Claw do?');
  });

  it('renders scenario cards from getAllScenarios', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText('创建差旅报销单')).toBeInTheDocument();
    expect(screen.getByText('审核报销单据')).toBeInTheDocument();
  });

  it('calls onSelect when scenario card clicked', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    fireEvent.click(screen.getByText('创建差旅报销单'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'reimbursement_create' }),
    );
  });

  it('renders "或选择具体业务场景" label', () => {
    const onSelect = vi.fn();
    render(<PromptCards onSelect={onSelect} />);

    expect(screen.getByText('或选择具体业务场景：')).toBeInTheDocument();
  });
});
