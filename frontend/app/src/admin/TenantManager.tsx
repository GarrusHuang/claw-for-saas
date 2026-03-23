/**
 * 租户管理 — 列表 + 新建/编辑/删除。
 */
import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, InputNumber, Tag, Popconfirm, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { listTenants, createTenant, updateTenant, deleteTenant, type Tenant } from './admin-api';

interface Props {
  onTenantsChange: () => void;
}

export default function TenantManager({ onTenantsChange }: Props) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Tenant | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTenants(await listTenants());
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (t: Tenant) => {
    setEditing(t);
    form.setFieldsValue({ tenant_id: t.tenant_id, name: t.name, max_users: t.max_users });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await updateTenant(editing.tenant_id, { name: values.name, max_users: values.max_users });
        message.success('租户已更新');
      } else {
        await createTenant({ tenant_id: values.tenant_id, name: values.name, max_users: values.max_users });
        message.success('租户已创建');
      }
      setModalOpen(false);
      load();
      onTenantsChange();
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (tenantId: string) => {
    try {
      await deleteTenant(tenantId);
      message.success('租户已删除');
      load();
      onTenantsChange();
    } catch (e) {
      message.error(`删除失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const columns = [
    { title: '租户 ID', dataIndex: 'tenant_id', key: 'tenant_id' },
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={s === 'active' ? 'green' : 'default'}>{s}</Tag>,
    },
    { title: '最大用户数', dataIndex: 'max_users', key: 'max_users' },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: Tenant) => (
        <span style={{ display: 'flex', gap: 8 }}>
          <a onClick={() => openEdit(record)}>编辑</a>
          <Popconfirm title="确认删除该租户？(将级联删除用户和 API Key)" onConfirm={() => handleDelete(record.tenant_id)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </span>
      ),
    },
  ];

  return (
    <>
      <div className="admin-toolbar">
        <span />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建租户</Button>
      </div>
      <Table
        dataSource={tenants}
        columns={columns}
        rowKey="tenant_id"
        loading={loading}
        pagination={false}
        size="middle"
      />
      <Modal
        title={editing ? '编辑租户' : '新建租户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="tenant_id" label="租户 ID" rules={[{ required: true }]}>
            <Input disabled={!!editing} placeholder="如: tenant-001" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="租户显示名称" />
          </Form.Item>
          <Form.Item name="max_users" label="最大用户数" initialValue={100}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
