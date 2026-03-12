/**
 * Schedule API 测试 — F5 定时任务 CRUD
 *
 * 覆盖: listSchedules, createSchedule, getSchedule,
 *       updateSchedule, deleteSchedule, pauseSchedule, resumeSchedule
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { configureAI } from '../src/config.ts';
import {
  listSchedules,
  createSchedule,
  getSchedule,
  updateSchedule,
  deleteSchedule,
  pauseSchedule,
  resumeSchedule,
} from '../src/services/ai-api.ts';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

function mockJsonResponse(body: unknown) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: new Headers(),
  });
}

function mockErrorResponse(status: number, detail: string) {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    status,
    statusText: 'Error',
    json: async () => ({ detail }),
    text: async () => JSON.stringify({ detail }),
    headers: new Headers(),
  });
}

describe('Schedule API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configureAI({ aiBaseUrl: 'http://test-api' });
  });

  // ── listSchedules ──

  it('listSchedules calls GET /api/schedules', async () => {
    mockJsonResponse({ tasks: [], total: 0 });

    const result = await listSchedules();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules');
    expect(opts.method ?? 'GET').toBe('GET');
    expect(result.tasks).toEqual([]);
    expect(result.total).toBe(0);
  });

  it('listSchedules returns tasks array', async () => {
    mockJsonResponse({
      tasks: [
        { id: 't1', name: '日报', cron: '0 9 * * *', enabled: true },
        { id: 't2', name: '周报', cron: '0 9 * * 1', enabled: false },
      ],
      total: 2,
    });

    const result = await listSchedules();
    expect(result.tasks).toHaveLength(2);
    expect(result.tasks[0].name).toBe('日报');
    expect(result.total).toBe(2);
  });

  // ── createSchedule ──

  it('createSchedule calls POST /api/schedules with payload', async () => {
    mockJsonResponse({ id: 'new-1', name: '新任务', cron: '0 9 * * *' });

    const result = await createSchedule({
      name: '新任务',
      cron: '0 9 * * *',
      message: '执行日报',
    });

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body);
    expect(body.name).toBe('新任务');
    expect(body.cron).toBe('0 9 * * *');
    expect(body.message).toBe('执行日报');
    expect(result.id).toBe('new-1');
  });

  // ── getSchedule ──

  it('getSchedule calls GET /api/schedules/:id', async () => {
    mockJsonResponse({ id: 'task-1', name: '日报' });

    const result = await getSchedule('task-1');

    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/task-1');
    expect(result.name).toBe('日报');
  });

  it('getSchedule encodes special characters in taskId', async () => {
    mockJsonResponse({ id: 'a/b', name: 'test' });

    await getSchedule('a/b');

    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/a%2Fb');
  });

  // ── updateSchedule ──

  it('updateSchedule calls PUT /api/schedules/:id with partial payload', async () => {
    mockJsonResponse({ id: 'task-1', name: '新名称' });

    await updateSchedule('task-1', { name: '新名称', cron: '0 10 * * *' });

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/task-1');
    expect(opts.method).toBe('PUT');
    const body = JSON.parse(opts.body);
    expect(body.name).toBe('新名称');
    expect(body.cron).toBe('0 10 * * *');
  });

  // ── deleteSchedule ──

  it('deleteSchedule calls DELETE /api/schedules/:id', async () => {
    mockJsonResponse({ status: 'deleted', task_id: 'task-1' });

    const result = await deleteSchedule('task-1');

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/task-1');
    expect(opts.method).toBe('DELETE');
    expect(result.status).toBe('deleted');
  });

  // ── pauseSchedule ──

  it('pauseSchedule calls POST /api/schedules/:id/pause', async () => {
    mockJsonResponse({ status: 'paused', task_id: 'task-1' });

    const result = await pauseSchedule('task-1');

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/task-1/pause');
    expect(opts.method).toBe('POST');
    expect(result.status).toBe('paused');
  });

  // ── resumeSchedule ──

  it('resumeSchedule calls POST /api/schedules/:id/resume', async () => {
    mockJsonResponse({ status: 'resumed', task_id: 'task-1' });

    const result = await resumeSchedule('task-1');

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('http://test-api/api/schedules/task-1/resume');
    expect(opts.method).toBe('POST');
    expect(result.status).toBe('resumed');
  });

  // ── Auth header ──

  it('schedule API calls include auth header', async () => {
    configureAI({ aiBaseUrl: 'http://test-api', authToken: 'my-token' });
    mockJsonResponse({ tasks: [], total: 0 });

    await listSchedules();

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers['Authorization']).toBe('Bearer my-token');
  });
});
