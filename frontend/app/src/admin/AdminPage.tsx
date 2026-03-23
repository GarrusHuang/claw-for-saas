/**
 * 管理后台页面 — 顶部租户选择器 + Tabs 切换五个管理模块。
 */
import { useState, useEffect, useCallback } from 'react';
import { Select, Tabs, message } from 'antd';
import { useAuthStore } from '@claw/core';
import { listTenants, type Tenant } from './admin-api';
import TenantManager from './TenantManager';
import UserManager from './UserManager';
import ApiKeyManager from './ApiKeyManager';
import InviteCodeManager from './InviteCodeManager';
import UsageDashboard from './UsageDashboard';

export default function AdminPage() {
  const authTenantId = useAuthStore((s) => s.tenantId);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedTenant, setSelectedTenant] = useState<string>(authTenantId || 'default');
  const [loading, setLoading] = useState(false);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listTenants();
      setTenants(list);
      // 如果当前选中的租户不在列表中，选中第一个
      if (list.length > 0 && !list.some(t => t.tenant_id === selectedTenant)) {
        setSelectedTenant(list[0].tenant_id);
      }
    } catch (e) {
      message.error(`加载租户列表失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [selectedTenant]);

  useEffect(() => {
    loadTenants();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const tabItems = [
    {
      key: 'tenants',
      label: '租户',
      children: <TenantManager onTenantsChange={loadTenants} />,
    },
    {
      key: 'users',
      label: '用户',
      children: <UserManager tenantId={selectedTenant} />,
    },
    {
      key: 'apikeys',
      label: 'API Key',
      children: <ApiKeyManager tenantId={selectedTenant} />,
    },
    {
      key: 'invites',
      label: '邀请码',
      children: <InviteCodeManager tenantId={selectedTenant} />,
    },
    {
      key: 'usage',
      label: '用量',
      children: <UsageDashboard tenantId={selectedTenant} />,
    },
  ];

  return (
    <div className="admin-page">
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 500, color: '#333' }}>租户:</span>
        <Select
          value={selectedTenant}
          onChange={setSelectedTenant}
          loading={loading}
          style={{ minWidth: 200 }}
          options={tenants.map(t => ({
            value: t.tenant_id,
            label: `${t.name} (${t.tenant_id})`,
          }))}
        />
      </div>
      <Tabs items={tabItems} />
    </div>
  );
}
