/**
 * Auth Store — JWT token 管理 + 登录状态 + 自动刷新。
 *
 * F3: 配合 A1 后端认证，前端 token 管理。
 * 4.4: Token 自动刷新 — 到期前 80% 时间自动调 /api/auth/refresh。
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
  /** 用户角色 */
  roles: string[];
  /** 是否管理员 */
  isAdmin: boolean;
  /** 登录中 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;

  /** 用户名密码登录 */
  login: (username: string, password: string, tenantId?: string) => Promise<boolean>;
  /** 邀请码注册 */
  register: (inviteCode: string, username: string, password: string) => Promise<boolean>;
  /** 登出 */
  logout: () => void;
  /** 从 localStorage 恢复 */
  restore: () => void;
  /** 刷新 token */
  refreshToken: () => Promise<boolean>;
  /** 是否已认证 */
  isAuthenticated: boolean;
}

const TOKEN_KEY = 'claw_auth_token';
const USER_KEY = 'claw_auth_user';

/** 刷新定时器 ID */
let _refreshTimerId: ReturnType<typeof setTimeout> | null = null;

function _clearRefreshTimer(): void {
  if (_refreshTimerId !== null) {
    clearTimeout(_refreshTimerId);
    _refreshTimerId = null;
  }
}

function _startRefreshTimer(expiresAt: number, getState: () => AuthState): void {
  _clearRefreshTimer();
  const now = Date.now();
  const ttl = expiresAt - now;
  if (ttl <= 0) return;
  // 在 80% 过期时间点刷新，最低 60s
  const delay = Math.max(ttl * 0.8, 60_000);
  _refreshTimerId = setTimeout(() => {
    getState().refreshToken();
  }, delay);
}

/** 同步从 localStorage 恢复初始状态，避免首帧闪登录页 */
function getInitialAuthState() {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const userStr = localStorage.getItem(USER_KEY);
    if (!token || !userStr) return null;
    const user = JSON.parse(userStr);
    if (!user.userId || !user.tenantId) return null;
    if (user.expiresAt && Date.now() > user.expiresAt) return null;
    return { token, userId: user.userId as string, tenantId: user.tenantId as string, expiresAt: user.expiresAt as number, roles: (user.roles as string[]) ?? [] };
  } catch {
    return null;
  }
}

const _initial = getInitialAuthState();

export const useAuthStore = create<AuthState>((set, get) => ({
  token: _initial?.token ?? null,
  userId: _initial?.userId ?? null,
  tenantId: _initial?.tenantId ?? null,
  expiresAt: _initial?.expiresAt ?? null,
  roles: _initial?.roles ?? [],
  isAdmin: (_initial?.roles ?? []).includes('admin'),
  loading: false,
  error: null,
  isAuthenticated: !!_initial,

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

      const roles: string[] = data.roles ?? [];

      // Persist
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY, JSON.stringify({
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
        roles,
      }));

      set({
        token: data.token,
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
        roles,
        isAdmin: roles.includes('admin'),
        loading: false,
        error: null,
        isAuthenticated: true,
      });

      _startRefreshTimer(expiresAt, get);

      return true;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : 'Network error' });
      return false;
    }
  },

  register: async (inviteCode, username, password) => {
    set({ loading: true, error: null });
    try {
      const baseUrl = getAIConfig().aiBaseUrl;
      const res = await fetch(`${baseUrl}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: inviteCode, username, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        const msg = body.detail || `Registration failed: ${res.status}`;
        set({ loading: false, error: msg });
        return false;
      }

      const data = await res.json();
      const expiresAt = Date.now() + (data.expires_in || 86400) * 1000;

      const roles: string[] = data.roles ?? [];

      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY, JSON.stringify({
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
        roles,
      }));

      set({
        token: data.token,
        userId: data.user_id,
        tenantId: data.tenant_id,
        expiresAt,
        roles,
        isAdmin: roles.includes('admin'),
        loading: false,
        error: null,
        isAuthenticated: true,
      });

      _startRefreshTimer(expiresAt, get);
      return true;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : 'Network error' });
      return false;
    }
  },

  logout: () => {
    _clearRefreshTimer();
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ token: null, userId: null, tenantId: null, expiresAt: null, roles: [], isAdmin: false, error: null, isAuthenticated: false });
  },

  restore: () => {
    const token = localStorage.getItem(TOKEN_KEY);
    const userStr = localStorage.getItem(USER_KEY);
    if (!token || !userStr) return;

    try {
      const user = JSON.parse(userStr);
      if (!user.userId || !user.tenantId) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        return;
      }
      // Check expiry
      if (user.expiresAt && Date.now() > user.expiresAt) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        set({ token: null, userId: null, tenantId: null, expiresAt: null, isAuthenticated: false });
        return;
      }
      const roles: string[] = user.roles ?? [];
      set({
        token,
        userId: user.userId,
        tenantId: user.tenantId,
        expiresAt: user.expiresAt,
        roles,
        isAdmin: roles.includes('admin'),
        isAuthenticated: true,
      });

      // 旧数据无 roles 字段时，异步调 /api/auth/me 补全
      if (!user.roles) {
        const baseUrl = getAIConfig().aiBaseUrl;
        fetch(`${baseUrl}/api/auth/me`, {
          headers: { 'Authorization': `Bearer ${token}` },
        }).then(r => r.ok ? r.json() : null).then(me => {
          if (me?.roles) {
            const freshRoles: string[] = me.roles;
            localStorage.setItem(USER_KEY, JSON.stringify({ ...user, roles: freshRoles }));
            set({ roles: freshRoles, isAdmin: freshRoles.includes('admin') });
          }
        }).catch(() => {});
      }

      _startRefreshTimer(user.expiresAt, get);
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      set({ token: null, userId: null, tenantId: null, expiresAt: null, roles: [], isAdmin: false, isAuthenticated: false });
    }
  },

  refreshToken: async () => {
    const state = get();
    if (!state.token) {
      get().logout();
      return false;
    }
    // Already expired
    if (state.expiresAt && Date.now() > state.expiresAt) {
      get().logout();
      return false;
    }

    try {
      const baseUrl = getAIConfig().aiBaseUrl;
      const res = await fetch(`${baseUrl}/api/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${state.token}`,
        },
      });

      if (!res.ok) {
        get().logout();
        return false;
      }

      const data = await res.json();
      const expiresAt = Date.now() + (data.expires_in || 86400) * 1000;

      // Update store + localStorage
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY, JSON.stringify({
        userId: data.user_id || state.userId,
        tenantId: data.tenant_id || state.tenantId,
        expiresAt,
        roles: state.roles,
      }));

      set({
        token: data.token,
        expiresAt,
      });

      _startRefreshTimer(expiresAt, get);
      return true;
    } catch {
      get().logout();
      return false;
    }
  },
}));

// Start refresh timer on initial load if we have a valid token
if (_initial?.expiresAt) {
  _startRefreshTimer(_initial.expiresAt, useAuthStore.getState);
}
