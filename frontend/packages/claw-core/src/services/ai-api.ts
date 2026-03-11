/**
 * AI 后端 API 客户端 — 仅包含 AI Agent 相关的 API 函数。
 *
 * 宿主配置相关 API (getCandidateTypes, getFormFields 等) 由宿主应用自行实现。
 */

import { getAIConfig } from '../config.ts';

function getBaseUrl(): string {
  return getAIConfig().aiBaseUrl;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ── Sessions ──

export interface SessionInfo {
  session_id: string;
  type?: string;
  business_type?: string;
  created_at?: string;
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
}

export async function listSessions(userId: string): Promise<SessionInfo[]> {
  const data = await apiFetch<{ sessions: SessionInfo[] }>(
    `/api/session/${encodeURIComponent(userId)}/list`,
  );
  return data.sessions;
}

export async function getSessionHistory(userId: string, sessionId: string): Promise<SessionDetail> {
  return apiFetch(
    `/api/session/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`,
  );
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

export async function uploadFile(file: File, userId: string = 'U001'): Promise<FileInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_id', userId);

  const res = await fetch(`${getBaseUrl()}/api/files/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json() as Promise<FileInfo>;
}

export async function listUserFiles(userId: string = 'U001'): Promise<FileInfo[]> {
  const data = await apiFetch<{ files: FileInfo[] }>(
    `/api/files/${encodeURIComponent(userId)}`,
  );
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

// ── Error Utilities (re-export from sse.ts, single source of truth) ──

export { isNetworkError } from './sse.ts';

