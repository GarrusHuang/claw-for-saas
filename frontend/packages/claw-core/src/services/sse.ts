/**
 * SSE 客户端 — 连接后端 Agent Pipeline 事件流。
 *
 * 使用 fetch + ReadableStream 实现 POST-based SSE，
 * 因为浏览器原生 EventSource 只支持 GET 请求。
 *
 * Phase 9/13: 新增 agent_partial_result, parallel_review_started, parallel_review_result 事件
 */

export type SSEEventType =
  | 'pipeline_started'
  | 'agent_progress'
  | 'agent_message'
  | 'text_delta'
  | 'thinking'
  | 'thinking_complete'
  | 'type_inferred'
  | 'field_update'
  | 'audit_result'
  | 'document_ready'
  | 'plan_proposed'
  | 'skill_created'
  | 'skill_updated'
  | 'tool_executed'
  | 'browser_action'
  | 'browser_screenshot'
  | 'agent_partial_result'       // Phase 9: 中途失败时的部分结果
  | 'parallel_review_started'    // Phase 13: 并行审查开始
  | 'parallel_review_result'     // Phase 13: 并行审查结果
  | 'request_upload'             // Phase 24: Agent 请求上传文件
  | 'request_confirmation'       // Phase 24: Agent 请求用户确认
  | 'request_input'              // Phase 24: Agent 请求用户输入
  | 'pipeline_complete'
  | 'error'
  | 'heartbeat'
  | 'keepalive';

export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface SSEClientOptions {
  maxRetries?: number;
  retryDelayMs?: number;
  connectionTimeoutMs?: number;
  onRetry?: (attempt: number, maxRetries: number, error: Error) => void;
}

type EventHandler = (data: Record<string, unknown>) => void;

/** 检查是否为网络错误 */
export function isNetworkError(err: unknown): boolean {
  if (err instanceof TypeError && err.message.includes('fetch')) return true;
  if (err instanceof DOMException && err.name === 'NetworkError') return true;
  return false;
}

export class AgentSSEClient {
  private url: string;
  private requestBody: Record<string, unknown>;
  private handlers: Map<string, EventHandler[]> = new Map();
  private abortController: AbortController | null = null;
  private _connected = false;
  private _userCancelled = false;
  private _retryCount = 0;

  private maxRetries: number;
  private retryDelayMs: number;
  private connectionTimeoutMs: number;
  private onRetry?: (attempt: number, maxRetries: number, error: Error) => void;

  constructor(
    url: string,
    requestBody: Record<string, unknown>,
    options: SSEClientOptions = {},
  ) {
    this.url = url;
    this.requestBody = requestBody;
    this.maxRetries = options.maxRetries ?? 3;
    this.retryDelayMs = options.retryDelayMs ?? 1000;
    this.connectionTimeoutMs = options.connectionTimeoutMs ?? 30_000;
    this.onRetry = options.onRetry;
  }

  on(eventType: string, handler: EventHandler): this {
    const existing = this.handlers.get(eventType) || [];
    existing.push(handler);
    this.handlers.set(eventType, existing);
    return this;
  }

  off(eventType: string, handler: EventHandler): this {
    const existing = this.handlers.get(eventType) || [];
    this.handlers.set(eventType, existing.filter((h) => h !== handler));
    return this;
  }

  get connected(): boolean { return this._connected; }
  get retryCount(): number { return this._retryCount; }

  async connect(): Promise<void> {
    this._userCancelled = false;
    this._retryCount = 0;
    await this._connectWithRetry();
  }

  close(): void {
    this._userCancelled = true;
    this.abortController?.abort();
    this._connected = false;
  }

  private async _connectWithRetry(): Promise<void> {
    while (true) {
      try {
        await this._connectOnce();
        return;
      } catch (err: unknown) {
        if (this._userCancelled) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;

        const isRecoverable = isNetworkError(err) || this._isServerError(err);
        if (!isRecoverable || this._retryCount >= this.maxRetries) {
          this._dispatch('error', JSON.stringify({
            code: 'SSE_ERROR',
            message: err instanceof Error ? err.message : String(err),
            recoverable: false,
            retryCount: this._retryCount,
          }));
          return;
        }

        this._retryCount += 1;
        const delay = this.retryDelayMs * Math.pow(2, this._retryCount - 1);
        if (this.onRetry) {
          this.onRetry(this._retryCount, this.maxRetries,
            err instanceof Error ? err : new Error(String(err)));
        }
        await this._sleep(delay);
        if (this._userCancelled) return;
      }
    }
  }

  private async _connectOnce(): Promise<void> {
    this.abortController = new AbortController();

    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    try {
      // Build headers with auth token BEFORE starting timeout
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const { getAIConfig } = await import('../config.ts');
      const config = getAIConfig();
      if (config.getAuthToken) {
        const token = await config.getAuthToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
      } else if (config.authToken) {
        headers['Authorization'] = `Bearer ${config.authToken}`;
      }

      // Start timeout AFTER auth resolution
      timeoutId = setTimeout(() => {
        this.abortController?.abort();
      }, this.connectionTimeoutMs);

      const response = await fetch(this.url, {
        method: 'POST',
        headers,
        body: JSON.stringify(this.requestBody),
        signal: this.abortController.signal,
      });
      if (timeoutId) clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      this._connected = true;

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      this._retryCount = 0;
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = '';
      let currentData = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const value = line.slice(5).trim();
            currentData = currentData ? currentData + '\n' + value : value;
          } else if (line.trim() === '') {
            if (currentData) {
              this._dispatch(currentEvent || 'message', currentData);
            }
            currentEvent = '';
            currentData = '';
          }
        }
      }
    } catch (err: unknown) {
      if (timeoutId) clearTimeout(timeoutId);
      if (this._userCancelled) return;
      throw err;
    } finally {
      this._connected = false;
    }
  }

  private _isServerError(err: unknown): boolean {
    if (err instanceof Error) {
      const match = err.message.match(/^HTTP (\d{3})/);
      if (match) {
        const status = Number(match[1]);
        return status >= 500 || status === 429;
      }
    }
    return false;
  }

  private _sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private _dispatch(eventType: string, rawData: string): void {
    try {
      const data = JSON.parse(rawData) as Record<string, unknown>;
      const handlers = this.handlers.get(eventType) || [];
      handlers.forEach((h) => h(data));
      const wildcardHandlers = this.handlers.get('*') || [];
      wildcardHandlers.forEach((h) => h({ type: eventType, ...data }));
    } catch (e) {
      console.warn('[SSE] Failed to parse event data:', eventType, e);
    }
  }
}
