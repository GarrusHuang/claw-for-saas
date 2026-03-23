/**
 * Admin API 调用层 — 租户/用户/API Key/邀请码/用量管理。
 */
import { apiFetch } from '@claw/core';

// ── Types ──

export interface Tenant {
  tenant_id: string;
  name: string;
  status: string;
  max_users: number;
}

export interface User {
  user_id: string;
  tenant_id: string;
  username: string;
  roles: string[];
  status: string;
}

export interface ApiKey {
  key_id: string;
  tenant_id: string;
  description: string;
  status: string;
  created_at: number;
  expires_at: number | null;
}

export interface ApiKeyCreateResult extends ApiKey {
  key: string;
  warning: string;
}

export interface InviteCode {
  code: string;
  tenant_id: string;
  roles: string[];
  max_uses: number;
  used_count: number;
  expires_at: number | null;
  created_by: string;
  created_at: number;
  status: string;
}

export interface UsageSummary {
  total_requests: number;
  total_tokens: number;
  success_count: number;
  failed_count: number;
  avg_tokens_per_request: number;
  avg_duration_ms: number;
}

export interface DailyUsage {
  date: string;
  total_requests: number;
  total_tokens: number;
  total_tool_calls: number;
  success_count: number;
  failed_count: number;
}

export interface UserRanking {
  user_id: string;
  total_requests: number;
  total_tokens: number;
  total_tool_calls: number;
}

export interface ToolUsage {
  tool_name: string;
  call_count: number;
}

export interface StorageUsage {
  sessions_bytes: number;
  files_bytes: number;
  total_bytes: number;
}

// ── Tenant CRUD ──

export async function listTenants(): Promise<Tenant[]> {
  return apiFetch('/api/admin/tenants');
}

export async function getTenant(tenantId: string): Promise<Tenant> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}`);
}

export async function createTenant(data: { tenant_id: string; name: string; max_users?: number }): Promise<Tenant> {
  return apiFetch('/api/admin/tenants', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateTenant(tenantId: string, data: { name?: string; status?: string; max_users?: number }): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteTenant(tenantId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}`, { method: 'DELETE' });
}

// ── User CRUD ──

export async function listUsers(tenantId: string): Promise<User[]> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/users`);
}

export async function createUser(tenantId: string, data: { user_id: string; username: string; password: string; roles?: string[] }): Promise<User> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/users`, { method: 'POST', body: JSON.stringify(data) });
}

export async function updateUser(tenantId: string, userId: string, data: { password?: string; roles?: string[]; status?: string }): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/users/${encodeURIComponent(userId)}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteUser(tenantId: string, userId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/users/${encodeURIComponent(userId)}`, { method: 'DELETE' });
}

// ── API Key ──

export async function listApiKeys(tenantId: string): Promise<ApiKey[]> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/api-keys`);
}

export async function createApiKey(tenantId: string, data: { description?: string; expires_in_days?: number | null }): Promise<ApiKeyCreateResult> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/api-keys`, { method: 'POST', body: JSON.stringify(data) });
}

export async function revokeApiKey(tenantId: string, keyId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/api-keys/${encodeURIComponent(keyId)}/revoke`, { method: 'POST' });
}

export async function deleteApiKey(tenantId: string, keyId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
}

// ── Invite Code ──

export async function listInviteCodes(tenantId: string): Promise<InviteCode[]> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/invite-codes`);
}

export async function createInviteCode(tenantId: string, data: { roles?: string[]; max_uses?: number; expires_in_days?: number | null }): Promise<{ code: string; tenant_id: string; roles: string[]; max_uses: number; expires_at: number | null }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/invite-codes`, { method: 'POST', body: JSON.stringify(data) });
}

export async function revokeInviteCode(tenantId: string, code: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/invite-codes/${encodeURIComponent(code)}/revoke`, { method: 'POST' });
}

// ── Usage ──

export async function getUsageSummary(tenantId: string, startDate?: string, endDate?: string): Promise<UsageSummary> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString();
  return apiFetch(`/api/admin/usage/tenant/${encodeURIComponent(tenantId)}${qs ? `?${qs}` : ''}`);
}

export async function getDailyUsage(tenantId: string, startDate?: string, endDate?: string): Promise<DailyUsage[]> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString();
  return apiFetch(`/api/admin/usage/tenant/${encodeURIComponent(tenantId)}/daily${qs ? `?${qs}` : ''}`);
}

export async function getUserRanking(tenantId: string, startDate?: string, endDate?: string, limit = 20): Promise<UserRanking[]> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  params.set('limit', String(limit));
  return apiFetch(`/api/admin/usage/tenant/${encodeURIComponent(tenantId)}/users?${params}`);
}

export async function getToolUsage(tenantId: string, startDate?: string, endDate?: string): Promise<ToolUsage[]> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString();
  return apiFetch(`/api/admin/usage/tenant/${encodeURIComponent(tenantId)}/tools${qs ? `?${qs}` : ''}`);
}

export async function getStorageUsage(tenantId: string): Promise<StorageUsage> {
  return apiFetch(`/api/admin/usage/tenant/${encodeURIComponent(tenantId)}/storage`);
}
