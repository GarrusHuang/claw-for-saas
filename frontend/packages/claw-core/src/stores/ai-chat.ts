/**
 * AI 对话框状态 Store — 从 app store 提取的 AI 侧状态。
 *
 * 管理对话框的打开/关闭、当前场景、Session 动作等。
 */

import { create } from 'zustand';
import { usePipelineStore } from './pipeline.ts';

export type ChatDialogState = 'closed' | 'fullscreen' | 'sidepanel';

export type ContentView = 'chat' | 'schedule' | 'skills';

export type SessionAction =
  | { type: 'new' }
  | { type: 'load'; sessionId: string }
  | null;

export interface AIChatState {
  chatDialogState: ChatDialogState;
  setChatDialogState: (state: ChatDialogState) => void;

  contentView: ContentView;
  setContentView: (view: ContentView) => void;

  activeScenario: string | null;
  setActiveScenario: (scenario: string | null) => void;

  sessionAction: SessionAction;
  dispatchSessionAction: (action: SessionAction) => void;
  clearSessionAction: () => void;

  openChat: (scenario: string) => void;
  closeChat: () => void;
}

export const useAIChatStore = create<AIChatState>((set) => ({
  chatDialogState: 'closed',
  setChatDialogState: (chatDialogState) => set({ chatDialogState }),

  contentView: 'chat',
  setContentView: (contentView) => set({ contentView }),

  activeScenario: null,
  setActiveScenario: (activeScenario) => set({ activeScenario }),

  sessionAction: null,
  dispatchSessionAction: (sessionAction) => set({ sessionAction, contentView: 'chat' }),
  clearSessionAction: () => set({ sessionAction: null }),

  openChat: (scenario) => {
    const currentScenario = useAIChatStore.getState().activeScenario;
    if (scenario !== currentScenario) {
      usePipelineStore.getState().reset();
    }
    set({ chatDialogState: 'fullscreen', activeScenario: scenario, contentView: 'chat' });
  },

  closeChat: () =>
    set({ chatDialogState: 'closed', activeScenario: null, contentView: 'chat' }),
}));
