/**
 * useAIChat hook 集成测试
 *
 * hook 现在来自 @claw/core，使用真实的 Zustand stores，
 * 仅 mock 网络层 (SSE/API)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAIChatStore, usePipelineStore, configureAI } from '@claw/core';

// Mock fetch globally to prevent real network calls
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ([]),
  body: null,
  headers: new Headers(),
});
vi.stubGlobal('fetch', mockFetch);

// ── Tests ──

describe('useAIChat (from @claw/core)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset stores
    useAIChatStore.setState({
      chatDialogState: 'closed',
      activeScenario: null,
      sessionAction: null,
    });
    usePipelineStore.getState().reset();
    // Configure AI with minimal config
    configureAI({
      aiBaseUrl: '',
      defaultUserId: 'U001',
      scenarios: {},
    });
  });

  it('useAIChatStore openChat sets fullscreen state', () => {
    const store = useAIChatStore.getState();
    store.openChat('reimbursement_create');

    const s = useAIChatStore.getState();
    expect(s.chatDialogState).toBe('fullscreen');
    expect(s.activeScenario).toBe('reimbursement_create');
  });

  it('useAIChatStore closeChat resets state', () => {
    const store = useAIChatStore.getState();
    store.openChat('reimbursement_create');
    expect(useAIChatStore.getState().chatDialogState).toBe('fullscreen');

    store.closeChat();
    expect(useAIChatStore.getState().chatDialogState).toBe('closed');
    expect(useAIChatStore.getState().activeScenario).toBeNull();
  });

  // ── F5: contentView ──

  it('contentView defaults to chat', () => {
    expect(useAIChatStore.getState().contentView).toBe('chat');
  });

  it('setContentView switches to schedule', () => {
    useAIChatStore.getState().setContentView('schedule');
    expect(useAIChatStore.getState().contentView).toBe('schedule');
  });

  it('openChat resets contentView to chat', () => {
    useAIChatStore.getState().setContentView('schedule');
    useAIChatStore.getState().openChat('test');
    expect(useAIChatStore.getState().contentView).toBe('chat');
  });

  it('closeChat resets contentView to chat', () => {
    useAIChatStore.getState().setContentView('schedule');
    useAIChatStore.getState().closeChat();
    expect(useAIChatStore.getState().contentView).toBe('chat');
  });

  it('dispatchSessionAction resets contentView to chat', () => {
    useAIChatStore.getState().setContentView('schedule');
    useAIChatStore.getState().dispatchSessionAction({ type: 'new' });
    expect(useAIChatStore.getState().contentView).toBe('chat');
  });
});
