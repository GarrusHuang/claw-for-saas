import { describe, it, expect, beforeEach } from 'vitest';
import { usePipelineStore } from '../src/stores/pipeline.ts';

describe('Pipeline Store', () => {
  beforeEach(() => {
    usePipelineStore.getState().reset();
  });

  // ── reset / softReset ──

  it('reset clears all state to initial', () => {
    const store = usePipelineStore.getState();

    store.setSessionId('sess-123');
    store.addConversationTurn('user', 'hello');
    store.startPipeline('reimbursement_create', ['step1']);
    store.setInferredType({ docType: 'travel', confidence: 0.95, reasoning: 'test' });

    store.reset();

    const s = usePipelineStore.getState();
    expect(s.status).toBe('idle');
    expect(s.sessionId).toBeNull();
    expect(s.conversationHistory).toHaveLength(0);
    expect(s.inferredType).toBeNull();
    expect(s.steps).toHaveLength(0);
    expect(s.scenario).toBe('');
  });

  it('softReset preserves sessionId and conversationHistory', () => {
    const store = usePipelineStore.getState();

    store.setSessionId('sess-456');
    store.addConversationTurn('user', 'hello');
    store.addConversationTurn('assistant', 'hi there');
    store.startPipeline('test', ['step1']);
    store.setInferredType({ docType: 'contract', confidence: 0.9, reasoning: '' });

    store.softReset();

    const s = usePipelineStore.getState();
    expect(s.status).toBe('idle');
    expect(s.sessionId).toBe('sess-456');
    expect(s.conversationHistory).toHaveLength(2);
    expect(s.inferredType).toBeNull();
    expect(s.steps).toHaveLength(0);
  });

  // ── startPipeline ──

  it('startPipeline sets running status, scenario, and steps', () => {
    const store = usePipelineStore.getState();

    store.setSessionId('existing-session');
    store.startPipeline('contract_draft', ['step_a', 'step_b', 'step_c']);

    const s = usePipelineStore.getState();
    expect(s.status).toBe('running');
    expect(s.scenario).toBe('contract_draft');
    expect(s.sessionId).toBe('existing-session');
    expect(s.steps).toHaveLength(3);
    expect(s.steps[0]).toEqual({ name: 'step_a', status: 'pending', component: '' });
    expect(s.startedAt).not.toBeNull();
  });

  // ── completePipeline ──

  it('completePipeline maps success to completed', () => {
    const store = usePipelineStore.getState();
    store.startPipeline('test', []);
    store.completePipeline('success', 1500);

    const s = usePipelineStore.getState();
    expect(s.status).toBe('completed');
    expect(s.durationMs).toBe(1500);
    expect(s.completedAt).not.toBeNull();
  });

  it('completePipeline maps plan_awaiting_approval to plan_awaiting', () => {
    const store = usePipelineStore.getState();
    store.startPipeline('test', []);
    store.completePipeline('plan_awaiting_approval', 800);
    expect(usePipelineStore.getState().status).toBe('plan_awaiting');
  });

  it('completePipeline maps error to failed', () => {
    const store = usePipelineStore.getState();
    store.startPipeline('test', []);
    store.completePipeline('error', 500);
    expect(usePipelineStore.getState().status).toBe('failed');
  });

  // ── addFieldValue ──

  it('addFieldValue replaces existing field with same ID', () => {
    const store = usePipelineStore.getState();

    store.addFieldValue({ fieldId: 'amount', value: 100, source: 'user', confidence: 0.5 });
    store.addFieldValue({ fieldId: 'category', value: 'travel', source: 'ai', confidence: 0.9 });
    expect(usePipelineStore.getState().fieldValues).toHaveLength(2);

    store.addFieldValue({ fieldId: 'amount', value: 200, source: 'ai', confidence: 0.95 });
    const fields = usePipelineStore.getState().fieldValues;
    expect(fields).toHaveLength(2);
    expect(fields.find(f => f.fieldId === 'amount')?.value).toBe(200);
    expect(fields.find(f => f.fieldId === 'amount')?.confidence).toBe(0.95);
  });

  // ── addToolExecution ──

  it('addToolExecution appends and removes from callingTools', () => {
    const store = usePipelineStore.getState();

    store.setCallingTools(['get_user_profile', 'get_expense_standards']);
    expect(usePipelineStore.getState().agentIteration.callingTools).toHaveLength(2);

    store.addToolExecution({
      id: 'tool-1',
      toolName: 'get_user_profile',
      success: true,
      latencyMs: 105,
      timestamp: Date.now(),
    });

    const s = usePipelineStore.getState();
    expect(s.toolExecutions).toHaveLength(1);
    expect(s.toolExecutions[0].toolName).toBe('get_user_profile');
    expect(s.agentIteration.callingTools).toHaveLength(1);
    expect(s.agentIteration.callingTools[0]).toBe('get_expense_standards');
  });

  // ── Streaming text ──

  it('appendStreamingText accumulates text and sets isStreaming', () => {
    const store = usePipelineStore.getState();
    expect(usePipelineStore.getState().isStreaming).toBe(false);

    store.appendStreamingText('Hello');
    store.appendStreamingText(' World');

    const s = usePipelineStore.getState();
    expect(s.streamingText).toBe('Hello World');
    expect(s.isStreaming).toBe(true);

    store.clearStreamingText();
    const s2 = usePipelineStore.getState();
    expect(s2.streamingText).toBe('');
    expect(s2.isStreaming).toBe(false);
  });

  // ── Plan ──

  it('setPlan and clearPlan work correctly', () => {
    const store = usePipelineStore.getState();

    const plan = {
      summary: 'test plan',
      detail: '# Plan',
      steps: [{ step: 1, description: 'step 1' }],
      estimatedActions: 10,
      requiresApproval: true,
    };

    store.setPlan(plan);
    expect(usePipelineStore.getState().plan).toEqual(plan);

    store.clearPlan();
    expect(usePipelineStore.getState().plan).toBeNull();
  });

  // ── Agent iteration ──

  it('setAgentIterationInfo updates current and max', () => {
    const store = usePipelineStore.getState();

    store.setAgentIterationInfo(3, 15);
    const s = usePipelineStore.getState();
    expect(s.agentIteration.current).toBe(3);
    expect(s.agentIteration.max).toBe(15);
    expect(s.agentIteration.callingTools).toEqual([]);
  });

  // ── Conversation turns ──

  it('addConversationTurn appends with timestamp', () => {
    const store = usePipelineStore.getState();

    const before = Date.now();
    store.addConversationTurn('user', 'hello');
    store.addConversationTurn('assistant', 'hi');

    const turns = usePipelineStore.getState().conversationHistory;
    expect(turns).toHaveLength(2);
    expect(turns[0].role).toBe('user');
    expect(turns[0].content).toBe('hello');
    expect(turns[0].timestamp).toBeGreaterThanOrEqual(before);
    expect(turns[1].role).toBe('assistant');
  });

  // ── Event log ──

  it('addEvent appends events to log', () => {
    const store = usePipelineStore.getState();

    store.addEvent({ type: 'type_inferred', data: { docType: 'travel' }, timestamp: Date.now() });
    store.addEvent({ type: 'field_update', data: { fieldId: 'amount' }, timestamp: Date.now() });

    expect(usePipelineStore.getState().eventLog).toHaveLength(2);
    expect(usePipelineStore.getState().eventLog[0].type).toBe('type_inferred');
  });

  // ── updateStepProgress ──

  it('updateStepProgress maps status correctly', () => {
    const store = usePipelineStore.getState();
    store.startPipeline('test', ['step_a', 'step_b']);

    store.updateStepProgress({ step: 'step_a', status: 'step_started', component: 'AgentA' });
    expect(usePipelineStore.getState().steps[0].status).toBe('running');
    expect(usePipelineStore.getState().steps[0].component).toBe('AgentA');

    store.updateStepProgress({ step: 'step_a', status: 'step_completed', duration_ms: 1200 });
    expect(usePipelineStore.getState().steps[0].status).toBe('completed');
    expect(usePipelineStore.getState().steps[0].durationMs).toBe(1200);

    store.updateStepProgress({ step: 'step_b', status: 'failed' });
    expect(usePipelineStore.getState().steps[1].status).toBe('failed');
    expect(usePipelineStore.getState().currentStep).toBe('step_b');
  });

  // ── ToolExecution with new fields (Phase 27) ──

  it('addToolExecution stores argsSummary, resultSummary, blocked', () => {
    const store = usePipelineStore.getState();

    store.addToolExecution({
      id: 'tool-27-1',
      toolName: 'get_expense_standards',
      success: true,
      latencyMs: 230,
      timestamp: Date.now(),
      argsSummary: { city: '上海', level: '处级' },
      resultSummary: '标准: 住宿≤500/晚',
    });

    store.addToolExecution({
      id: 'tool-27-2',
      toolName: 'run_command',
      success: false,
      latencyMs: 50,
      timestamp: Date.now(),
      blocked: true,
      resultSummary: 'Hook blocked: 安全检查',
    });

    const s = usePipelineStore.getState();
    expect(s.toolExecutions).toHaveLength(2);
    expect(s.toolExecutions[0].argsSummary).toEqual({ city: '上海', level: '处级' });
    expect(s.toolExecutions[0].resultSummary).toBe('标准: 住宿≤500/晚');
    expect(s.toolExecutions[1].blocked).toBe(true);
  });

  // ── Thinking text ──

  it('appendThinkingText joins with double newlines', () => {
    const store = usePipelineStore.getState();

    store.appendThinkingText('analyzing...');
    expect(usePipelineStore.getState().thinkingText).toBe('analyzing...');

    store.appendThinkingText('determined type');
    expect(usePipelineStore.getState().thinkingText).toBe('analyzing...\n\ndetermined type');
  });

  // ── setError ──

  it('setError sets error message and failed status', () => {
    const store = usePipelineStore.getState();

    store.startPipeline('test', []);
    store.setError('Connection timeout');

    const s = usePipelineStore.getState();
    expect(s.error).toBe('Connection timeout');
    expect(s.status).toBe('failed');
  });

  // ── agentMessage ──

  it('setAgentMessage stores agent reply', () => {
    const store = usePipelineStore.getState();

    store.setAgentMessage('I have completed the task');
    expect(usePipelineStore.getState().agentMessage).toBe('I have completed the task');
  });

  // ── adoptDocument ──

  it('adoptDocument stores adopted document', () => {
    const store = usePipelineStore.getState();
    const doc = {
      documentType: '合同',
      title: '采购合同',
      content: '# 合同内容',
      metadata: {},
    };

    store.adoptDocument(doc);
    expect(usePipelineStore.getState().adoptedDocument).toEqual(doc);
  });

  it('reset clears adoptedDocument', () => {
    const store = usePipelineStore.getState();
    store.adoptDocument({
      documentType: '合同',
      title: '采购合同',
      content: '# content',
      metadata: {},
    });

    store.reset();
    expect(usePipelineStore.getState().adoptedDocument).toBeNull();
  });

  // ── Plan step tracking (后端驱动) ──

  it('initPlanSteps creates pending steps', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: '推断类型' },
      { step: 2, description: '查询数据' },
      { step: 3, description: '填写表单' },
    ]);

    const s = usePipelineStore.getState();
    expect(s.planSteps).toHaveLength(3);
    expect(s.planSteps[0].status).toBe('pending');
    expect(s.planSteps[0].description).toBe('推断类型');
    expect(s.planSteps[2].step).toBe(3);
  });

  it('startPlanStep sets step to running', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: 'A' },
      { step: 2, description: 'B' },
    ]);

    store.startPlanStep(0);
    const s = usePipelineStore.getState();
    expect(s.planSteps[0].status).toBe('running');
    expect(s.planSteps[0].startedAt).not.toBeNull();
    expect(s.planSteps[1].status).toBe('pending');
  });

  it('completePlanStep sets step to completed', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: 'A' },
      { step: 2, description: 'B' },
    ]);

    store.startPlanStep(0);
    store.completePlanStep(0, 150);
    const s = usePipelineStore.getState();
    expect(s.planSteps[0].status).toBe('completed');
    expect(s.planSteps[0].completedAt).not.toBeNull();
  });

  it('failPlanStep sets step to failed', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: 'A' },
    ]);

    store.startPlanStep(0);
    store.failPlanStep(0);
    const s = usePipelineStore.getState();
    expect(s.planSteps[0].status).toBe('failed');
    expect(s.planSteps[0].completedAt).not.toBeNull();
  });

  it('completePlanSteps marks all remaining as completed', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: 'A' },
      { step: 2, description: 'B' },
      { step: 3, description: 'C' },
    ]);

    store.startPlanStep(0);
    store.completePlanStep(0);
    store.completePlanSteps();

    const s = usePipelineStore.getState();
    expect(s.planSteps[0].status).toBe('completed');
    expect(s.planSteps[1].status).toBe('completed');
    expect(s.planSteps[2].status).toBe('completed');
  });

  it('softReset resets plan steps to pending', () => {
    const store = usePipelineStore.getState();
    store.initPlanSteps([
      { step: 1, description: 'A' },
      { step: 2, description: 'B' },
    ]);
    store.startPlanStep(0);
    store.completePlanStep(0);
    store.startPlanStep(1);

    store.softReset();
    const s = usePipelineStore.getState();
    expect(s.planSteps[0].status).toBe('pending');
    expect(s.planSteps[0].startedAt).toBeNull();
    expect(s.planSteps[1].status).toBe('pending');
  });

});
