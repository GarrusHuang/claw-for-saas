/**
 * Session Status Store — 追踪运行中和未读的会话。
 */

import { create } from 'zustand';

interface SessionStatusState {
  /** 后端正在运行的 session IDs */
  runningIds: Set<string>;
  /** 有更新但用户未查看的 session IDs */
  unreadIds: Set<string>;

  addRunning: (id: string) => void;
  removeRunning: (id: string) => void;
  addUnread: (id: string) => void;
  markRead: (id: string) => void;
}

export const useSessionStatusStore = create<SessionStatusState>((set) => ({
  runningIds: new Set(),
  unreadIds: new Set(),

  addRunning: (id) =>
    set((state) => {
      const next = new Set(state.runningIds);
      next.add(id);
      return { runningIds: next };
    }),

  removeRunning: (id) =>
    set((state) => {
      if (!state.runningIds.has(id)) return state;
      const next = new Set(state.runningIds);
      next.delete(id);
      return { runningIds: next };
    }),

  addUnread: (id) =>
    set((state) => {
      const next = new Set(state.unreadIds);
      next.add(id);
      return { unreadIds: next };
    }),

  markRead: (id) =>
    set((state) => {
      if (!state.unreadIds.has(id)) return state;
      const next = new Set(state.unreadIds);
      next.delete(id);
      return { unreadIds: next };
    }),
}));
