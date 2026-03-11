/**
 * AI 对话框状态 Store — 从 app store 提取的 AI 侧状态。
 *
 * 管理对话框的打开/关闭、当前场景、Session 动作等。
 */

import { create } from 'zustand';
import { usePipelineStore } from './pipeline.ts';

export type ChatDialogState = 'closed' | 'fullscreen' | 'sidepanel';

export type SessionAction =
  | { type: 'new' }
  | { type: 'load'; sessionId: string }
  | null;

export interface AIChatState {
  chatDialogState: ChatDialogState;
  setChatDialogState: (state: ChatDialogState) => void;

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

  activeScenario: null,
  setActiveScenario: (activeScenario) => set({ activeScenario }),

  sessionAction: null,
  dispatchSessionAction: (sessionAction) => set({ sessionAction }),
  clearSessionAction: () => set({ sessionAction: null }),

  openChat: (scenario) => {
    const currentScenario = useAIChatStore.getState().activeScenario;
    // 场景切换时重置 pipeline (清除 sessionId 和所有结果)
    if (scenario !== currentScenario) {
      usePipelineStore.getState().reset();
    }
    set({ chatDialogState: 'fullscreen', activeScenario: scenario });
  },

  closeChat: () =>
    set({ chatDialogState: 'closed', activeScenario: null }),
}));
