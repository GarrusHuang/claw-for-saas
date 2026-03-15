/**
 * AI 后端 API 客户端 — 仅包含 AI Agent 相关的 API 函数。
 *
 * 宿主配置相关 API (getCandidateTypes, getFormFields 等) 由宿主应用自行实现。
 */

import { getAIConfig } from '../config.ts';

function getBaseUrl(): string {
  return getAIConfig().aiBaseUrl;
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const config = getAIConfig();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };

  // 动态 token 优先
  if (config.getAuthToken) {
    const token = await config.getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }

  return headers;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const { headers: optionHeaders, ...restOptions } = options || {};
  const mergedHeaders = {
    ...authHeaders,
    ...(optionHeaders instanceof Headers
      ? Object.fromEntries(optionHeaders.entries())
      : optionHeaders as Record<string, string> | undefined),
  };
  const res = await fetch(`${getBaseUrl()}${path}`, {
    ...restOptions,
    headers: mergedHeaders,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  if (res.status === 204) return {} as T;
  const ct = res.headers.get('content-type') || '';
  if (ct && !ct.includes('application/json')) {
    throw new Error(`API returned non-JSON content-type: ${ct}`);
  }
  return res.json() as Promise<T>;
}

// ── Sessions ──

export interface SessionInfo {
  session_id: string;
  type?: string;
  business_type?: string;
  created_at?: number;
  [key: string]: unknown;
}

export interface SessionDetail {
  session_id: string;
  user_id: string;
  messages: Array<{
    role: string;
    content: string;
    [key: string]: unknown;
  }>;
  message_count: number;
  plan_steps?: Array<{
    index: number;
    action: string;
    description: string;
    status: string;
    [key: string]: unknown;
  }>;
  timelines?: Array<{
    turn_index: number;
    entries: Array<{
      type: string;
      content?: string;
      iteration?: number;
      tool_name?: string;
      success?: boolean;
      blocked?: boolean;
      latency_ms?: number;
      args_summary?: Record<string, string>;
      result_summary?: string;
      ts: number;
    }>;
  }>;
  loaded_skills?: string[];
}

export async function listSessions(): Promise<SessionInfo[]> {
  const data = await apiFetch<{ sessions: SessionInfo[] }>(
    `/api/session/list`,
  );
  return data.sessions;
}

export interface SearchResult {
  session_id: string;
  title?: string;
  business_type?: string;
  created_at?: number;
  match_snippet?: string;
  title_match?: boolean;
  [key: string]: unknown;
}

export async function searchSessions(query: string): Promise<SearchResult[]> {
  const data = await apiFetch<{ results: SearchResult[]; total: number }>(
    `/api/session/search?q=${encodeURIComponent(query)}`,
  );
  return data.results;
}

export async function getSessionHistory(_userId: string, sessionId: string): Promise<SessionDetail> {
  return apiFetch(
    `/api/session/${encodeURIComponent(sessionId)}`,
  );
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch(`/api/session/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

// ── Memory ──

export interface MemoryStats {
  corrections: number | { total?: number; [key: string]: unknown };
  learning_entries: number;
  sessions?: { count?: number; [key: string]: unknown };
  learning?: { total?: number; total_uses?: number; avg_confidence?: number; [key: string]: unknown };
  [key: string]: unknown;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  return apiFetch('/api/memory/stats');
}

// ── Corrections ──

export async function submitCorrection(data: CorrectionPayload): Promise<CorrectionResult> {
  return apiFetch('/api/correction/submit', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getUserPreferences(
  userId: string, businessType: string, docType?: string,
): Promise<Record<string, unknown>> {
  let url = `/api/correction/preferences/${encodeURIComponent(userId)}/${encodeURIComponent(businessType)}`;
  if (docType) url += `?doc_type=${encodeURIComponent(docType)}`;
  return apiFetch(url);
}

// ── Skills ──

export interface SkillMetadata {
  name: string;
  version?: string;
  description?: string;
  type?: string;  // domain | scenario | capability
  applies_to?: string[];
  business_types?: string[];
  depends_on?: string[];
  tags?: string[];
  token_estimate?: number;
}

export interface SkillDetail {
  metadata: SkillMetadata;
  body: string;
}

export async function listSkills(): Promise<{ skills: SkillMetadata[]; total: number }> {
  return apiFetch('/api/skills');
}

export async function getSkillDetail(skillName: string): Promise<SkillDetail> {
  return apiFetch(`/api/skills/${skillName}`);
}

export interface SkillCreatePayload {
  name: string;
  description: string;
  type: string;
  version: string;
  applies_to: string[];
  business_types: string[];
  depends_on: string[];
  tags: string[];
  token_estimate?: number;
  body: string;
}

export async function createSkill(
  data: SkillCreatePayload,
): Promise<{ ok: boolean; name?: string; error?: string; warnings?: string[]; checks?: Record<string, boolean> }> {
  return apiFetch('/api/skills', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateSkill(
  name: string,
  data: SkillCreatePayload,
): Promise<{ ok: boolean; error?: string; warnings?: string[]; checks?: Record<string, boolean> }> {
  return apiFetch(`/api/skills/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteSkill(name: string): Promise<{ ok: boolean; error?: string }> {
  return apiFetch(`/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export async function importSkill(data: {
  url?: string; content?: string;
}): Promise<{ ok: boolean; name?: string; error?: string; warnings?: string[]; checks?: Record<string, boolean> }> {
  return apiFetch('/api/skills/import', { method: 'POST', body: JSON.stringify(data) });
}

// ── Correction API ──

export interface CorrectionPayload {
  user_id: string;
  business_type: string;
  doc_type?: string;
  field_id: string;
  agent_value: string;
  user_value: string;
  context_snapshot?: Record<string, unknown>;
}

export interface CorrectionResult {
  status: string;
  field_id: string;
  message: string;
}

// ── Files ──

export interface FileInfo {
  file_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at?: number;
}

export async function uploadFile(file: File, userId?: string, sessionId?: string): Promise<FileInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_id', userId || getAIConfig().defaultUserId);

  // Auth headers (without Content-Type — browser sets multipart boundary)
  const headers: Record<string, string> = {};
  const config = getAIConfig();
  if (config.getAuthToken) {
    const token = await config.getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }

  let url = `${getBaseUrl()}/api/files/upload`;
  if (sessionId) url += `?session_id=${encodeURIComponent(sessionId)}`;

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json() as Promise<FileInfo>;
}

export async function bindFilesToSession(fileIds: string[], sessionId: string): Promise<void> {
  await apiFetch('/api/files/bind-session', {
    method: 'POST',
    body: JSON.stringify({ file_ids: fileIds, session_id: sessionId }),
  });
}

export async function deleteFile(fileId: string): Promise<void> {
  await apiFetch(`/api/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
}

export async function listUserFiles(_userId?: string, sessionId?: string): Promise<FileInfo[]> {
  let url = `/api/files/`;
  if (sessionId) url += `?session_id=${encodeURIComponent(sessionId)}`;
  const data = await apiFetch<{ files: FileInfo[] }>(url);
  return data.files;
}

// ── Tools ──

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  read_only: boolean;
}

export async function listTools(): Promise<ToolInfo[]> {
  const data = await apiFetch<{ tools: ToolInfo[] }>('/api/tools');
  return data.tools.map((t) => ({ ...t, read_only: t.read_only ?? false }));
}

// ── Schedules ──

export interface RunRecord {
  started_at: number;
  status: string;
  duration_s: number;
  session_id: string;
  trigger: string;    // "scheduled" | "manual"
}

export interface ScheduledTask {
  id: string;
  name: string;
  cron: string;
  message: string;
  user_id: string;
  tenant_id: string;
  business_type: string;
  enabled: boolean;
  created_at: number;
  last_run_at: number | null;
  last_run_status: string;       // "success" | "failed" | ""
  next_run_at: number | null;
  scheduled_at: number | null;   // 一次性任务时间戳
  expires_at: number | null;
  run_history: RunRecord[];
}

export interface ScheduleCreatePayload {
  name: string;
  message: string;
  cron?: string;
  scheduled_at?: number;
  expires_at?: number;
  business_type?: string;
  timezone?: string;
}

export interface ScheduleUpdatePayload {
  name?: string;
  message?: string;
  cron?: string;
  scheduled_at?: number | null;
  expires_at?: number | null;
  business_type?: string;
  enabled?: boolean;
  timezone?: string;
}

export async function listSchedules(): Promise<{ tasks: ScheduledTask[]; total: number }> {
  return apiFetch('/api/schedules');
}

export async function createSchedule(data: ScheduleCreatePayload): Promise<ScheduledTask> {
  return apiFetch('/api/schedules', { method: 'POST', body: JSON.stringify(data) });
}

export async function getSchedule(taskId: string): Promise<ScheduledTask> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}`);
}

export async function updateSchedule(taskId: string, data: ScheduleUpdatePayload): Promise<ScheduledTask> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteSchedule(taskId: string): Promise<{ status: string; task_id: string }> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
}

export async function pauseSchedule(taskId: string): Promise<{ status: string; task_id: string }> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}/pause`, { method: 'POST' });
}

export async function resumeSchedule(taskId: string): Promise<{ status: string; task_id: string }> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}/resume`, { method: 'POST' });
}

export async function runScheduleNow(taskId: string): Promise<{ status: string; task_id: string }> {
  return apiFetch(`/api/schedules/${encodeURIComponent(taskId)}/run`, { method: 'POST' });
}

// ── Knowledge Base ──

export interface KBFileInfo {
  file_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  owner_id: string;
  tenant_id: string;
  scope: string;       // "global" | "user"
  created_at: number;
  description: string;
  sha256: string;
}

export async function listKnowledgeFiles(): Promise<{ files: KBFileInfo[]; total: number }> {
  return apiFetch('/api/knowledge/');
}

export async function uploadKnowledgeFile(file: File, scope: string = 'user', description: string = ''): Promise<KBFileInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('scope', scope);
  formData.append('description', description);

  const headers: Record<string, string> = {};
  const config = getAIConfig();
  if (config.getAuthToken) {
    const token = await config.getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }

  const res = await fetch(`${getBaseUrl()}/api/knowledge/upload`, {
    method: 'POST', headers, body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json() as Promise<KBFileInfo>;
}

export async function deleteKnowledgeFile(fileId: string): Promise<{ status: string }> {
  return apiFetch(`/api/knowledge/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
}

export async function getKBFileText(fileId: string): Promise<{ file_id: string; text: string }> {
  return apiFetch(`/api/knowledge/${encodeURIComponent(fileId)}/text`);
}

// ── Pipeline Snapshot (事件重放快照) ──

export interface PipelineSnapshot {
  session_id: string;
  trace_id: string;
  status: string;
  streaming_text: string;
  thinking_text: string;
  tool_executions: Array<{
    tool: string;
    success: boolean;
    latency_ms: number;
    args_summary?: Record<string, string>;
    result_summary?: string;
    blocked?: boolean;
    ts: number;
  }>;
  plan: { summary: string; steps: unknown[]; detail: string; estimated_actions: number } | null;
  plan_steps: Array<{ index: number; status: string }>;
  agent_iteration: { current: number; max: number };
  agent_message: string | null;
  loaded_skills: string[];
  file_artifacts: Array<{
    path: string;
    filename: string;
    size_bytes: number;
    content_type: string;
    session_id: string;
  }>;
  is_complete: boolean;
  error: string | null;
}

export async function fetchPipelineSnapshot(sessionId: string): Promise<PipelineSnapshot> {
  return apiFetch(`/api/chat/${encodeURIComponent(sessionId)}/events`);
}

export async function fetchRunningSessions(): Promise<string[]> {
  const data = await apiFetch<{ session_ids: string[] }>('/api/chat/running');
  return data.session_ids;
}

// ── Inject (real-time message injection while pipeline is running) ──

export async function injectMessage(
  sessionId: string,
  message: string,
  files?: { fileId: string; filename: string }[],
): Promise<void> {
  await apiFetch(`/api/chat/${encodeURIComponent(sessionId)}/inject`, {
    method: 'POST',
    body: JSON.stringify({ message, files }),
  });
}


