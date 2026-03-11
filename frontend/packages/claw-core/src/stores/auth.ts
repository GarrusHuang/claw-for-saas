/**
 * Auth Store — JWT token 管理 + 登录状态。
 *
 * F3: 配合 A1 后端认证，前端 token 管理 + 自动刷新。
 */

import { create } from 'zustand';
import { getAIConfig } from '../config.ts';

export interface AuthState {
  /** JWT token */
  token: string | null;
  /** 用户 ID (from login response) */
  userId: string | null;
  /** 租户 ID */
  tenantId: string | null;
  /** token 过期时间戳 (ms) */
  expiresAt: number | null;
  /** 登录中 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;

  /** 用户名密码登录 */
  login: (username: string, password: string, tenantId?: string) => Promise<boolean>;
  /** 登出 */
  logout: () => void;
  /** 从 localStorage 恢复 */
  restore: () => void;
  /** 是否已认证 */
  isAuthenticated: () => boolean;
}

const TOKEN_KEY = 'claw_auth_token';
const USER_KEY = 'claw_auth_user';

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  userId: null,
  tenantId: null,
  expiresAt: null,
  loading: false,
  error: null,

  login: async (username, password, tenantId = 'default') => {
    set({ loading: true, error: null });
    try {
      const baseUrl = getAIConfig().aiBaseUrl;
      const res = await fetch(`${baseUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, tenant_id: tenantId }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        const msg = body.detail || `Login failed: ${res.status}`;
        set({ loading: false, error: msg });
        return false;
      }

      const data = await res.json();
      const expiresAt = Date.now() + (data.expires_in || 86400) * 1000;

      // Persist
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY, JSON.stringify({
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
      }));

      set({
        token: data.token,
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
        loading: false,
        error: null,
      });

      return true;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : 'Network error' });
      return false;
    }
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ token: null, userId: null, tenantId: null, expiresAt: null, error: null });
  },

  restore: () => {
    const token = localStorage.getItem(TOKEN_KEY);
    const userStr = localStorage.getItem(USER_KEY);
    if (!token || !userStr) return;

    try {
      const user = JSON.parse(userStr);
      // Check expiry
      if (user.expiresAt && Date.now() > user.expiresAt) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        set({ token: null, userId: null, tenantId: null, expiresAt: null });
        return;
      }
      set({
        token,
        userId: user.userId,
        tenantId: user.tenantId,
        expiresAt: user.expiresAt,
      });
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      set({ token: null, userId: null, tenantId: null, expiresAt: null });
    }
  },

  isAuthenticated: () => {
    const { token, expiresAt } = get();
    if (!token) return false;
    if (expiresAt && Date.now() > expiresAt) return false;
    return true;
  },
}));
