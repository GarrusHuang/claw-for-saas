/**
 * Auth Header Injection & Config Token Handling Tests
 *
 * Covers: configureAI token config, auth header injection in ai-api.ts,
 *         and SSE auth header propagation.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { configureAI, getAIConfig, getAllScenarios } from '../src/config.ts';
import { listSessions, uploadFile } from '../src/services/ai-api.ts';
import { AgentSSEClient } from '../src/services/sse.ts';

// -- Mock fetch globally --
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// -- Helper: reset config to defaults before each test --
function resetConfig() {
  configureAI({
    aiBaseUrl: '',
    defaultUserId: 'U001',
    scenarios: {},
    authToken: undefined,
    getAuthToken: undefined,
  });
}

// -- Helper: mock a successful JSON response --
function mockJsonResponse(body: unknown) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: new Headers(),
  });
}

// -- Helper: mock a readable stream response for SSE --
function mockSSEResponse() {
  const encoder = new TextEncoder();
  mockFetch.mockResolvedValueOnce({
    ok: true,
    headers: new Headers(),
    body: {
      getReader: () => ({
        read: vi.fn()
          .mockResolvedValueOnce({
            done: false,
            value: encoder.encode('event: heartbeat\ndata: {}\n\n'),
          })
          .mockResolvedValue({ done: true }),
      }),
    },
  });
}

// ================================================================
// Tests
// ================================================================

describe('Config Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfig();
  });

  it('configureAI merges partial config with defaults', () => {
    configureAI({ aiBaseUrl: 'http://localhost:9000' });

    const cfg = getAIConfig();
    expect(cfg.aiBaseUrl).toBe('http://localhost:9000');
    expect(cfg.defaultUserId).toBe('U001');
  });

  it('configureAI stores getAuthToken callback', () => {
    const tokenFn = () => 'dynamic-token';
    configureAI({ getAuthToken: tokenFn });

    const cfg = getAIConfig();
    expect(cfg.getAuthToken).toBe(tokenFn);
  });

  it('configureAI stores static authToken', () => {
    configureAI({ authToken: 'static-secret' });

    const cfg = getAIConfig();
    expect(cfg.authToken).toBe('static-secret');
  });

  it('multiple configureAI calls merge incrementally', () => {
    configureAI({ aiBaseUrl: 'http://host-a' });
    configureAI({ authToken: 'tok-b' });

    const cfg = getAIConfig();
    expect(cfg.aiBaseUrl).toBe('http://host-a');
    expect(cfg.authToken).toBe('tok-b');
  });

  it('getAllScenarios returns configured scenarios', () => {
    configureAI({
      scenarios: {
        s1: { key: 's1', title: 'Scenario 1', action: 'a1', businessType: 'b1' } as any,
        s2: { key: 's2', title: 'Scenario 2', action: 'a2', businessType: 'b2' } as any,
      },
    });

    const scenarios = getAllScenarios();
    expect(scenarios).toHaveLength(2);
    expect(scenarios.map((s: any) => s.key).sort()).toEqual(['s1', 's2']);
  });
});

describe('Auth Header Injection (ai-api.ts)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfig();
    configureAI({ aiBaseUrl: 'http://test-api' });
  });

  it('getAuthHeaders includes Bearer token from getAuthToken', async () => {
    configureAI({ getAuthToken: () => 'test-token' });
    mockJsonResponse({ sessions: [] });

    await listSessions();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer test-token');
  });

  it('getAuthHeaders uses static authToken when no getAuthToken', async () => {
    configureAI({ authToken: 'static-tok' });
    mockJsonResponse({ sessions: [] });

    await listSessions();

    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer static-tok');
  });

  it('getAuthHeaders omits Authorization when no token', async () => {
    mockJsonResponse({ sessions: [] });

    await listSessions();

    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBeUndefined();
    expect(callHeaders['Content-Type']).toBe('application/json');
  });

  it('getAuthToken is called dynamically on each request', async () => {
    const tokenFn = vi.fn().mockReturnValue('dynamic-tok');
    configureAI({ getAuthToken: tokenFn });

    mockJsonResponse({ sessions: [] });
    await listSessions();

    mockJsonResponse({ sessions: [] });
    await listSessions();

    expect(tokenFn).toHaveBeenCalledTimes(2);
  });

  it('uploadFile includes auth header without Content-Type', async () => {
    configureAI({ authToken: 'upload-tok' });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ file_id: 'f1', filename: 'test.txt', content_type: 'text/plain', size_bytes: 10 }),
    });

    // Create a minimal File-like object for node environment
    const blob = new Blob(['hello'], { type: 'text/plain' });
    const file = new File([blob], 'test.txt', { type: 'text/plain' });

    await uploadFile(file, 'user1');

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer upload-tok');
    // Content-Type must NOT be set (browser sets multipart boundary automatically)
    expect(callHeaders['Content-Type']).toBeUndefined();
  });

  it('apiFetch custom headers issue - options.headers override auth', async () => {
    // Documents BUG: apiFetch spreads ...options AFTER setting headers,
    // so if options contains headers, it will override the auth headers entirely.
    configureAI({ authToken: 'my-token' });
    mockJsonResponse({ sessions: [] });

    await listSessions();

    // The normal case works — auth header is present
    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer my-token');

    // BUG: If someone were to call apiFetch with custom headers in options,
    // the spread `{ headers: authHeaders, ...options }` would replace
    // authHeaders entirely with options.headers.
    // This test documents the behavior: the auth headers are set first,
    // then options spreads over them. Since listSessions doesn't pass
    // custom headers, auth works fine here. But the pattern is fragile.
  });
});

describe('SSE Auth Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfig();
    configureAI({ aiBaseUrl: 'http://test-api' });
  });

  it('SSE client includes auth header from getAuthToken', async () => {
    configureAI({ getAuthToken: async () => 'sse-dynamic-token' });
    mockSSEResponse();

    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    await client.connect();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer sse-dynamic-token');
  });

  it('SSE client uses static authToken fallback', async () => {
    configureAI({ authToken: 'sse-static-token' });
    mockSSEResponse();

    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    await client.connect();

    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBe('Bearer sse-static-token');
  });

  it('SSE client omits auth header when no token', async () => {
    mockSSEResponse();

    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    await client.connect();

    const callHeaders = mockFetch.mock.calls[0][1].headers;
    expect(callHeaders['Authorization']).toBeUndefined();
    expect(callHeaders['Content-Type']).toBe('application/json');
  });
});

// ── B9: connected 标志位 ──

describe('SSE Connected Flag (B9)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfig();
    configureAI({ aiBaseUrl: 'http://test-api' });
  });

  it('connected is false before connect', () => {
    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    expect(client.connected).toBe(false);
  });

  it('connected is false after stream ends', async () => {
    mockSSEResponse();
    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    await client.connect();
    // 流结束后 connected 应为 false
    expect(client.connected).toBe(false);
  });

  it('connected is false on HTTP error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      headers: new Headers(),
    });
    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    client.maxRetries = 0;
    try { await client.connect(); } catch { /* expected */ }
    expect(client.connected).toBe(false);
  });
});

// ── B10: 多行 SSE data 累加 ──

describe('SSE Multi-line Data (B10)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfig();
    configureAI({ aiBaseUrl: 'http://test-api' });
  });

  it('accumulates multi-line data fields into valid JSON', async () => {
    const encoder = new TextEncoder();
    const dispatched: Record<string, unknown>[] = [];

    // 模拟多行 data 的 SSE 流 — JSON 拆成多行 (符合 SSE 规范)
    // 完整 JSON: {"key":"value","num":42}
    // 拆为: data: {"key":"value", 和 data: "num":42}
    mockFetch.mockResolvedValueOnce({
      ok: true,
      headers: new Headers(),
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              done: false,
              value: encoder.encode(
                'event: test\ndata: {"key":"value",\ndata: "num":42}\n\n'
              ),
            })
            .mockResolvedValue({ done: true }),
        }),
      },
    });

    const client = new AgentSSEClient('http://test-api/api/chat', { message: 'hi' });
    client.on('test', (data: Record<string, unknown>) => {
      dispatched.push(data);
    });
    await client.connect();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].key).toBe('value');
    expect(dispatched[0].num).toBe(42);
  });
});
