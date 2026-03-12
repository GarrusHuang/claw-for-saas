/**
 * Auth Store 测试 — F3 认证系统
 *
 * 覆盖: login (success/failure/network error/missing expires_in),
 *       logout, restore (valid/expired/corrupted), isAuthenticated, custom tenantId
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuthStore, configureAI } from '@claw/core';

// ── Mock localStorage ──
const storage: Record<string, string> = {};
const mockLocalStorage = {
  getItem: vi.fn((key: string) => storage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { storage[key] = value; }),
  removeItem: vi.fn((key: string) => { delete storage[key]; }),
  clear: vi.fn(() => { for (const k of Object.keys(storage)) delete storage[k]; }),
  get length() { return Object.keys(storage).length; },
  key: vi.fn((i: number) => Object.keys(storage)[i] ?? null),
};
vi.stubGlobal('localStorage', mockLocalStorage);

// ── Mock fetch ──
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// ── Helpers ──
const TOKEN_KEY = 'claw_auth_token';
const USER_KEY = 'claw_auth_user';

function resetStore() {
  useAuthStore.setState({
    token: null,
    userId: null,
    tenantId: null,
    expiresAt: null,
    loading: false,
    error: null,
  });
}

function clearStorage() {
  for (const k of Object.keys(storage)) delete storage[k];
}

// ── Tests ──

describe('useAuthStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
    clearStorage();
    configureAI({ aiBaseUrl: 'http://localhost:8000' });
  });

  // ─── Login ───

  describe('login', () => {
    it('success — state updated and localStorage set', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: 'jwt-abc',
          user_id: 'U100',
          tenant_id: 'T1',
          expires_in: 3600,
        }),
      });

      const result = await useAuthStore.getState().login('admin', 'pass');

      expect(result).toBe(true);
      const s = useAuthStore.getState();
      expect(s.token).toBe('jwt-abc');
      expect(s.userId).toBe('U100');
      expect(s.tenantId).toBe('T1');
      expect(s.expiresAt).toBeTypeOf('number');
      expect(s.loading).toBe(false);
      expect(s.error).toBeNull();

      // localStorage persisted
      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(TOKEN_KEY, 'jwt-abc');
      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
        USER_KEY,
        expect.stringContaining('"userId":"U100"'),
      );
    });

    it('failure (401) — error set, returns false', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ detail: 'Invalid credentials' }),
      });

      const result = await useAuthStore.getState().login('bad', 'cred');

      expect(result).toBe(false);
      const s = useAuthStore.getState();
      expect(s.error).toBe('Invalid credentials');
      expect(s.token).toBeNull();
      expect(s.loading).toBe(false);
    });

    it('network error — error set to message', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Failed to fetch'));

      const result = await useAuthStore.getState().login('u', 'p');

      expect(result).toBe(false);
      expect(useAuthStore.getState().error).toBe('Failed to fetch');
      expect(useAuthStore.getState().loading).toBe(false);
    });

    it('missing expires_in — uses default 86400', async () => {
      const before = Date.now();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: 'tok',
          user_id: 'U1',
          tenant_id: 'T1',
          // no expires_in
        }),
      });

      await useAuthStore.getState().login('u', 'p');

      const s = useAuthStore.getState();
      // Default 86400s = 24h
      const expectedMin = before + 86400 * 1000;
      const expectedMax = Date.now() + 86400 * 1000;
      expect(s.expiresAt).toBeGreaterThanOrEqual(expectedMin);
      expect(s.expiresAt).toBeLessThanOrEqual(expectedMax);
    });

    it('custom tenantId — sent to backend', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: 't', user_id: 'u', tenant_id: 'custom-tenant', expires_in: 60,
        }),
      });

      await useAuthStore.getState().login('u', 'p', 'custom-tenant');

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/login',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ username: 'u', password: 'p', tenant_id: 'custom-tenant' }),
        }),
      );
    });
  });

  // ─── Logout ───

  describe('logout', () => {
    it('clears state and localStorage', async () => {
      // Setup authenticated state
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ token: 'tok', user_id: 'U1', tenant_id: 'T1', expires_in: 3600 }),
      });
      await useAuthStore.getState().login('u', 'p');
      expect(useAuthStore.getState().token).toBe('tok');

      useAuthStore.getState().logout();

      const s = useAuthStore.getState();
      expect(s.token).toBeNull();
      expect(s.userId).toBeNull();
      expect(s.tenantId).toBeNull();
      expect(s.expiresAt).toBeNull();
      expect(s.error).toBeNull();
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(TOKEN_KEY);
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(USER_KEY);
    });
  });

  // ─── Restore ───

  describe('restore', () => {
    it('valid token — state populated', () => {
      const expiresAt = Date.now() + 3600_000;
      storage[TOKEN_KEY] = 'saved-tok';
      storage[USER_KEY] = JSON.stringify({ userId: 'U5', tenantId: 'T5', expiresAt });

      useAuthStore.getState().restore();

      const s = useAuthStore.getState();
      expect(s.token).toBe('saved-tok');
      expect(s.userId).toBe('U5');
      expect(s.tenantId).toBe('T5');
      expect(s.expiresAt).toBe(expiresAt);
    });

    it('expired token — state NOT populated, localStorage cleaned', () => {
      const expiresAt = Date.now() - 1000; // past
      storage[TOKEN_KEY] = 'old-tok';
      storage[USER_KEY] = JSON.stringify({ userId: 'U5', tenantId: 'T5', expiresAt });

      useAuthStore.getState().restore();

      expect(useAuthStore.getState().token).toBeNull();
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(TOKEN_KEY);
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(USER_KEY);
    });

    it('corrupted JSON — silent cleanup', () => {
      storage[TOKEN_KEY] = 'tok';
      storage[USER_KEY] = '{not-valid-json!!!';

      // Should not throw
      useAuthStore.getState().restore();

      expect(useAuthStore.getState().token).toBeNull();
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(TOKEN_KEY);
      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith(USER_KEY);
    });
  });

  // ─── isAuthenticated ───

  describe('isAuthenticated', () => {
    it('no token — false', () => {
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });

    it('valid token — true after login sets it', () => {
      useAuthStore.setState({
        token: 'tok',
        expiresAt: Date.now() + 3600_000,
        isAuthenticated: true,
      });
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    it('logged out — false', () => {
      useAuthStore.setState({
        token: 'tok',
        expiresAt: Date.now() + 3600_000,
        isAuthenticated: true,
      });
      useAuthStore.getState().logout();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });
  });
});
