/**
 * API Key 管理 — 列表 + 创建(显示 key) + 撤销/删除。
 */
import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, InputNumber, Tag, Popconfirm, Typography, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { listApiKeys, createApiKey, revokeApiKey, deleteApiKey, type ApiKey } from './admin-api';

interface Props {
  tenantId: string;
}

function formatTime(ts: number | null): string {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString('zh-CN');
}

export default function ApiKeyManager({ tenantId }: Props) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setKeys(await listApiKeys(tenantId));
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const result = await createApiKey(tenantId, {
        description: values.description || '',
        expires_in_days: values.expires_in_days || null,
      });
      setCreatedKey(result.key);
      setCreateModalOpen(false);
      form.resetFields();
      load();
    } catch (e) {
      message.error(`创建失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    try {
      await revokeApiKey(tenantId, keyId);
      message.success('已撤销');
      load();
    } catch (e) {
      message.error(`撤销失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const handleDelete = async (keyId: string) => {
    try {
      await deleteApiKey(tenantId, keyId);
      message.success('已删除');
      load();
    } catch (e) {
      message.error(`删除失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const statusColor = (s: string) => {
    if (s === 'active') return 'green';
    if (s === 'revoked') return 'red';
    return 'default';
  };

  const columns = [
    { title: 'Key ID', dataIndex: 'key_id', key: 'key_id', ellipsis: true },
    { title: '描述', dataIndex: 'description', key: 'description' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={statusColor(s)}>{s}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: formatTime },
    { title: '过期时间', dataIndex: 'expires_at', key: 'expires_at', render: formatTime },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: ApiKey) => (
        <span style={{ display: 'flex', gap: 8 }}>
          {record.status === 'active' && (
            <Popconfirm title="确认撤销？" onConfirm={() => handleRevoke(record.key_id)}>
              <a>撤销</a>
            </Popconfirm>
          )}
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.key_id)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </span>
      ),
    },
  ];

  return (
    <>
      <div className="admin-toolbar">
        <span style={{ fontSize: 13, color: '#8c8c8c' }}>租户: {tenantId}</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setCreateModalOpen(true); }}>
          创建 API Key
        </Button>
      </div>
      <Table
        dataSource={keys}
        columns={columns}
        rowKey="key_id"
        loading={loading}
        pagination={false}
        size="middle"
      />

      {/* 创建表单 */}
      <Modal
        title="创建 API Key"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreate}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="description" label="描述">
            <Input placeholder="用途描述 (可选)" />
          </Form.Item>
          <Form.Item name="expires_in_days" label="过期天数 (留空=永不过期)">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如: 90" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建成功弹窗 — 显示 key */}
      <Modal
        title="API Key 已创建"
        open={!!createdKey}
        onCancel={() => setCreatedKey(null)}
        onOk={() => setCreatedKey(null)}
        closable={false}
        maskClosable={false}
      >
        <div style={{ marginBottom: 12 }}>
          <Typography.Text type="warning" strong>
            请立即复制保存，此 Key 仅此时可见！
          </Typography.Text>
        </div>
        <Typography.Text code copyable style={{ wordBreak: 'break-all', fontSize: 13 }}>
          {createdKey}
        </Typography.Text>
      </Modal>
    </>
  );
}
