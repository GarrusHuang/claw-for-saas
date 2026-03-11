import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock @claw/core stores used by ChatResultCards
vi.mock('@claw/core', () => ({
  usePipelineStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      inferredType: null,
      fieldValues: [],
      auditSummary: null,
      document: null,
      status: 'idle',
    };
    return selector(state);
  }),
  useAIChatStore: vi.fn((selector?: (state: Record<string, unknown>) => unknown) => {
    const state = { chatDialogState: 'closed', activeScenario: null };
    return selector ? selector(state) : state;
  }),
}));

describe('MiniTypeInference', () => {
  it('renders doc type tag and confidence', async () => {
    const { MiniTypeInference } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniTypeInference
        data={{
          docType: 'travel_reimbursement',
          confidence: 0.95,
          reasoning: '材料包含差旅信息',
        }}
      />,
    );

    expect(screen.getByText('类型推断')).toBeInTheDocument();
    expect(screen.getByText('travel_reimbursement')).toBeInTheDocument();
    expect(screen.getByText('材料包含差旅信息')).toBeInTheDocument();
  });
});

describe('MiniFieldUpdates', () => {
  it('renders field count and values', async () => {
    const { MiniFieldUpdates } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniFieldUpdates
        fields={[
          { fieldId: 'amount', value: 1500, source: 'ai', confidence: 0.9 },
          { fieldId: 'category', value: '差旅费', source: 'ai', confidence: 0.85 },
          { fieldId: 'department', value: '心内科', source: 'known', confidence: 1.0 },
        ]}
      />,
    );

    expect(screen.getByText(/表单填写 — 3 个字段/)).toBeInTheDocument();
  });

  it('returns null for empty fields', async () => {
    const { MiniFieldUpdates } = await import('../src/chat/ChatResultCards.tsx');

    const { container } = render(<MiniFieldUpdates fields={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows +N more when fields exceed 6', async () => {
    const { MiniFieldUpdates } = await import('../src/chat/ChatResultCards.tsx');

    const fields = Array.from({ length: 8 }, (_, i) => ({
      fieldId: `field_${i}`,
      value: `val_${i}`,
      source: 'ai',
      confidence: 0.9,
    }));

    render(<MiniFieldUpdates fields={fields} />);

    expect(screen.getByText('+2 更多')).toBeInTheDocument();
  });
});

describe('MiniAuditSummary', () => {
  it('renders all-pass audit result', async () => {
    const { MiniAuditSummary } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniAuditSummary
        data={{
          results: [],
          passCount: 5,
          failCount: 0,
          warningCount: 0,
          conclusion: '全部通过',
        }}
      />,
    );

    expect(screen.getByText('审计结果')).toBeInTheDocument();
    expect(screen.getByText('通过 5')).toBeInTheDocument();
    expect(screen.getByText('全部通过')).toBeInTheDocument();
  });

  it('renders mixed audit result with failures and warnings', async () => {
    const { MiniAuditSummary } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniAuditSummary
        data={{
          results: [],
          passCount: 3,
          failCount: 2,
          warningCount: 1,
          conclusion: '存在不合规项',
        }}
      />,
    );

    expect(screen.getByText('通过 3')).toBeInTheDocument();
    expect(screen.getByText('失败 2')).toBeInTheDocument();
    expect(screen.getByText('警告 1')).toBeInTheDocument();
  });
});

describe('MiniDocumentPreview', () => {
  it('renders document title and type tag', async () => {
    const { MiniDocumentPreview } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniDocumentPreview
        data={{
          documentType: 'audit_report',
          title: '差旅报销审核报告',
          content: '审核意见：本次报销材料齐全，金额合规。',
          metadata: {},
        }}
      />,
    );

    expect(screen.getByText('差旅报销审核报告')).toBeInTheDocument();
    expect(screen.getByText('audit_report')).toBeInTheDocument();
  });

  it('truncates content longer than 200 characters', async () => {
    const { MiniDocumentPreview } = await import('../src/chat/ChatResultCards.tsx');

    const longContent = '这是一段很长的文档内容。'.repeat(30);
    render(
      <MiniDocumentPreview
        data={{
          documentType: 'contract',
          title: '合同文本',
          content: longContent,
          metadata: {},
        }}
      />,
    );

    // Content should be truncated with ...
    const textElement = screen.getByText(/这是一段很长的文档内容.*\.\.\./);
    expect(textElement).toBeInTheDocument();
  });
});

describe('MiniPlanCard', () => {
  it('renders steps with progress counter', async () => {
    const { MiniPlanCard } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniPlanCard
        data={{
          summary: '报销创建方案',
          detail: '',
          steps: [
            { step: 1, description: '推断单据类型' },
            { step: 2, description: '填写表单字段' },
            { step: 3, description: '执行审计规则' },
          ],
          estimatedActions: 15,
          requiresApproval: false,
        }}
      />,
    );

    expect(screen.getByText('执行进度')).toBeInTheDocument();
    expect(screen.getByText('推断单据类型')).toBeInTheDocument();
    expect(screen.getByText('填写表单字段')).toBeInTheDocument();
    expect(screen.getByText('执行审计规则')).toBeInTheDocument();
    expect(screen.getByText('0/3')).toBeInTheDocument();
  });

  it('returns null when steps array is empty', async () => {
    const { MiniPlanCard } = await import('../src/chat/ChatResultCards.tsx');

    const { container } = render(
      <MiniPlanCard
        data={{
          summary: 'test',
          detail: '',
          steps: [],
          estimatedActions: 0,
          requiresApproval: false,
        }}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it('handles string steps gracefully', async () => {
    const { MiniPlanCard } = await import('../src/chat/ChatResultCards.tsx');

    render(
      <MiniPlanCard
        data={{
          summary: 'test',
          detail: '',
          steps: ['step one', 'step two'] as unknown as Array<{ step: number; description: string }>,
          estimatedActions: 5,
          requiresApproval: false,
        }}
      />,
    );

    expect(screen.getByText('step one')).toBeInTheDocument();
    expect(screen.getByText('step two')).toBeInTheDocument();
  });
});
